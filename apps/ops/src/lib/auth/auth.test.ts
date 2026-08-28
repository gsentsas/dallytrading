import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ecrituresCookies, magasinCookies, reinitialiserCookies } from '@/test/faux-cookies';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return {
    ...original,
    authenticate: vi.fn(),
    fetchIdentity: vi.fn(),
    destroySession: vi.fn(async () => undefined),
  };
});

const { OPS_COOKIE, sealSession } = await import('@/lib/auth/session');
const { authenticate, destroySession, fetchIdentity, OpsGatewayError } = await import(
  '@/lib/auth/odoo-ops'
);
const { currentIdentity, loginOps, logoutOps, readOpsSession, MESSAGE_ECHEC_CONNEXION } =
  await import('@/lib/auth/auth');

/** La classe vient d'un import dynamique : son nom n'est pas utilisable comme type. */
type ErreurPasserelle = { readonly code: string };

const IDENTITE = {
  user: { id: 7, name: 'Gilles', login: 'gilles' },
  role: 'logistician' as const,
  cash_actor: 'Gilles',
  cash_actor_configured: true,
  capabilities: { intake_create: true, payment_create: true, supervise: false },
};

beforeEach(() => {
  reinitialiserCookies();
  vi.mocked(authenticate).mockReset();
  vi.mocked(fetchIdentity).mockReset();
  vi.mocked(destroySession).mockReset();
  vi.mocked(destroySession).mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('connexion d’un opérateur', () => {
  it('scelle un cookie et renvoie l’identité quand tout va bien', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);

    await expect(loginOps('gilles', 'motdepasse', 'corr')).resolves.toEqual(IDENTITE);
    expect(magasinCookies.has(OPS_COOKIE)).toBe(true);
  });

  it('demande l’identité AVANT de sceller le cookie', async () => {
    const ordre: string[] = [];
    vi.mocked(authenticate).mockImplementation(async () => {
      ordre.push('authenticate');
      return 'session-odoo';
    });
    vi.mocked(fetchIdentity).mockImplementation(async () => {
      // À cet instant, aucun cookie ne doit exister : sinon il subsisterait
      // une fenêtre pendant laquelle un compte non habilité dispose d'une
      // session scellée valide.
      ordre.push(magasinCookies.has(OPS_COOKIE) ? 'cookie-avant-verification' : 'verification');
      return IDENTITE;
    });

    await loginOps('gilles', 'motdepasse', 'corr');
    expect(ordre).toEqual(['authenticate', 'verification']);
  });

  it('ne scelle aucun cookie pour un compte sans rôle Ops', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockRejectedValue(new OpsGatewayError('forbidden'));

    await expect(loginOps('compta', 'motdepasse', 'corr')).rejects.toMatchObject({
      code: 'invalid_credentials',
    });
    expect(magasinCookies.has(OPS_COOKIE)).toBe(false);
  });

  it('détruit la session Odoo ouverte pour un compte sans rôle Ops', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockRejectedValue(new OpsGatewayError('forbidden'));

    await loginOps('compta', 'motdepasse', 'corr').catch(() => undefined);
    // Sans cela, un jeton Odoo valide resterait ouvert après un refus.
    expect(destroySession).toHaveBeenCalledWith('session-odoo', 'corr');
  });

  it('rend un compte non habilité indiscernable d’un mot de passe faux', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockRejectedValue(new OpsGatewayError('forbidden'));
    const nonHabilite = await loginOps('compta', 'x', 'corr').catch(
      (e: ErreurPasserelle) => e.code,
    );

    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    const mauvaisMotDePasse = await loginOps('gilles', 'x', 'corr').catch(
      (e: ErreurPasserelle) => e.code,
    );

    expect(nonHabilite).toBe(mauvaisMotDePasse);
  });

  it('ne place jamais le mot de passe dans le cookie', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);
    await loginOps('gilles', 'motdepasse-tres-reconnaissable', 'corr');
    const scelle = magasinCookies.get(OPS_COOKIE) ?? '';
    expect(scelle).not.toContain('motdepasse-tres-reconnaissable');
  });

  it('écrit un cookie httpOnly limité au même site', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);
    await loginOps('gilles', 'motdepasse', 'corr');
    expect(ecrituresCookies.at(-1)?.options).toMatchObject({
      httpOnly: true,
      sameSite: 'lax',
      path: '/',
    });
  });

  it('ne propose qu’un seul message d’échec', () => {
    expect(MESSAGE_ECHEC_CONNEXION).toBe('Identifiants invalides.');
  });
});

describe('lecture de la session', () => {
  it('ignore un cookie illisible plutôt que de lever', async () => {
    magasinCookies.set(OPS_COOKIE, 'jeton-forge');
    await expect(readOpsSession()).resolves.toBeNull();
  });

  it('ignore un cookie périmé', async () => {
    magasinCookies.set(
      OPS_COOKIE,
      sealSession({ odooSessionId: 'a', issuedAt: Date.now() - 9 * 60 * 60 * 1000 }),
    );
    await expect(readOpsSession()).resolves.toBeNull();
  });
});

describe('identité courante', () => {
  it('interroge réellement Odoo à chaque appel', async () => {
    magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);

    await currentIdentity('corr-1');
    await currentIdentity('corr-2');
    // Aucun cache : un droit retiré dans Odoo s'applique à la requête suivante.
    expect(fetchIdentity).toHaveBeenCalledTimes(2);
  });

  it('efface le cookie quand Odoo ne reconnaît plus la session', async () => {
    magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
    vi.mocked(fetchIdentity).mockRejectedValue(new OpsGatewayError('forbidden'));

    await expect(currentIdentity('corr')).resolves.toBeNull();
    expect(magasinCookies.has(OPS_COOKIE)).toBe(false);
  });

  it('renvoie null sans appeler Odoo quand il n’y a pas de cookie', async () => {
    await expect(currentIdentity('corr')).resolves.toBeNull();
    expect(fetchIdentity).not.toHaveBeenCalled();
  });
});

describe('déconnexion', () => {
  it('efface le cookie et ferme la session Odoo', async () => {
    magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
    await logoutOps('corr');
    expect(destroySession).toHaveBeenCalledWith('sX', 'corr');
    expect(magasinCookies.has(OPS_COOKIE)).toBe(false);
  });

  it('reste sans effet supplémentaire au deuxième appel', async () => {
    magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
    await logoutOps('corr');
    await expect(logoutOps('corr')).resolves.toBeUndefined();
    expect(destroySession).toHaveBeenCalledTimes(1);
  });

  it('efface le cookie même sans session préalable', async () => {
    await expect(logoutOps('corr')).resolves.toBeUndefined();
    expect(ecrituresCookies.at(-1)?.options.maxAge).toBe(0);
  });
});
