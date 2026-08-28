import { beforeEach, describe, expect, it, vi } from 'vitest';

import { magasinCookies, reinitialiserCookies } from '@/test/faux-cookies';

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
const { resetRateLimits } = await import('@/lib/rate-limit');
const { POST: postLogin } = await import('@/app/api/auth/login/route');
const { POST: postLogout } = await import('@/app/api/auth/logout/route');
const { GET: getMe } = await import('@/app/api/me/route');

const IDENTITE = {
  user: { id: 7, name: 'Gilles', login: 'gilles' },
  role: 'logistician' as const,
  cash_actor: 'Gilles',
  cash_actor_configured: true,
  capabilities: { intake_create: true, payment_create: true, supervise: false },
};

function requeteLogin(corps: unknown, enTetes: Record<string, string> = {}): Request {
  return new Request('https://ops.example.test/api/auth/login', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-forwarded-for': '203.0.113.9', ...enTetes },
    body: typeof corps === 'string' ? corps : JSON.stringify(corps),
  });
}

beforeEach(() => {
  reinitialiserCookies();
  resetRateLimits();
  vi.mocked(authenticate).mockReset();
  vi.mocked(fetchIdentity).mockReset();
  vi.mocked(destroySession).mockReset();
  vi.mocked(destroySession).mockResolvedValue(undefined);
});

describe('POST /api/auth/login', () => {
  it('renvoie l’identité et pose le cookie quand les identifiants sont bons', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);

    const reponse = await postLogin(requeteLogin({ login: 'gilles', password: 'x' }));
    expect(reponse.status).toBe(200);
    await expect(reponse.json()).resolves.toEqual({ success: true, data: IDENTITE });
    expect(magasinCookies.has(OPS_COOKIE)).toBe(true);
  });

  it('n’est jamais mis en cache', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);
    const reponse = await postLogin(requeteLogin({ login: 'gilles', password: 'x' }));
    expect(reponse.headers.get('cache-control')).toBe('no-store');
  });

  it('donne le même message à tous les refus', async () => {
    const messages = new Set<string>();

    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    messages.add(
      ((await (await postLogin(requeteLogin({ login: 'inconnu', password: 'x' }))).json()) as {
        error: string;
      }).error,
    );

    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockRejectedValue(new OpsGatewayError('forbidden'));
    messages.add(
      ((await (await postLogin(requeteLogin({ login: 'compta', password: 'x' }))).json()) as {
        error: string;
      }).error,
    );

    messages.add(
      ((await (await postLogin(requeteLogin({ login: '', password: '' }))).json()) as {
        error: string;
      }).error,
    );

    // Trois causes distinctes, une seule phrase : le formulaire ne devient pas
    // un annuaire des comptes existants ni des comptes habilités.
    expect(messages.size).toBe(1);
    expect([...messages][0]).toBe('Identifiants invalides.');
  });

  it('ne pose aucun cookie pour un compte sans rôle Ops', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockRejectedValue(new OpsGatewayError('forbidden'));

    const reponse = await postLogin(requeteLogin({ login: 'compta', password: 'x' }));
    expect(reponse.status).toBe(401);
    expect(magasinCookies.has(OPS_COOKIE)).toBe(false);
  });

  it('refuse une requête qui n’est pas du JSON', async () => {
    // Un formulaire d'un autre site ne peut pas émettre `application/json`
    // sans requête préalable CORS : exiger ce type ferme le CSRF par
    // formulaire.
    const reponse = await postLogin(
      requeteLogin({ login: 'gilles', password: 'x' }, { 'content-type': 'text/plain' }),
    );
    expect(reponse.status).toBe(415);
    expect(authenticate).not.toHaveBeenCalled();
  });

  it('refuse un corps illisible sans interroger Odoo', async () => {
    const reponse = await postLogin(requeteLogin('{ pas du json'));
    expect(reponse.status).toBe(400);
    expect(authenticate).not.toHaveBeenCalled();
  });

  it('finit par refuser un martèlement du même compte', async () => {
    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    let dernier = 0;
    for (let essai = 0; essai < 10; essai += 1) {
      dernier = (await postLogin(requeteLogin({ login: 'gilles', password: 'x' }))).status;
    }
    expect(dernier).toBe(429);
  });

  it('ne verrouille pas une adresse d’où l’équipe se connecte normalement', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);
    // Tous les téléphones d'un entrepôt sortent par la même adresse publique.
    let dernier = 0;
    for (let essai = 0; essai < 40; essai += 1) {
      dernier = (
        await postLogin(requeteLogin({ login: `operateur${essai}`, password: 'x' }))
      ).status;
    }
    expect(dernier).toBe(200);
  });

  it('finit par refuser un balayage de comptes depuis une même adresse', async () => {
    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    let dernier = 0;
    for (let essai = 0; essai < 40; essai += 1) {
      dernier = (
        await postLogin(requeteLogin({ login: `victime${essai}`, password: 'x' }))
      ).status;
    }
    // Chaque compte reste sous sa propre limite : c'est le budget de
    // l'adresse qui arrête l'essayage.
    expect(dernier).toBe(429);
  });

  it('ne verrouille pas un compte qui se connecte avec succès', async () => {
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);
    // Un poste d'entrepôt est partagé : compter les réussites finirait par
    // verrouiller une équipe qui travaille.
    let dernier = 0;
    for (let essai = 0; essai < 15; essai += 1) {
      dernier = (await postLogin(requeteLogin({ login: 'gilles', password: 'x' }))).status;
    }
    expect(dernier).toBe(200);
  });

  it('remet le budget du compte à neuf après une réussite', async () => {
    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    for (let essai = 0; essai < 5; essai += 1) {
      await postLogin(requeteLogin({ login: 'gilles', password: 'x' }));
    }
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);
    expect((await postLogin(requeteLogin({ login: 'gilles', password: 'bon' }))).status).toBe(200);

    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    expect((await postLogin(requeteLogin({ login: 'gilles', password: 'x' }))).status).toBe(401);
  });

  it('ne relâche pas le budget de l’adresse sur une connexion réussie', async () => {
    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    for (let essai = 0; essai < 29; essai += 1) {
      await postLogin(requeteLogin({ login: `victime${essai}`, password: 'x' }));
    }
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);
    await postLogin(requeteLogin({ login: 'gilles', password: 'bon' }));

    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    await postLogin(requeteLogin({ login: 'victime99', password: 'x' }));
    // Sinon un balayage se remettrait à zéro en intercalant une connexion
    // valide.
    expect((await postLogin(requeteLogin({ login: 'victime98', password: 'x' }))).status).toBe(429);
  });

  it('garde un compte verrouillé même si le bon mot de passe arrive ensuite', async () => {
    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    for (let essai = 0; essai < 8; essai += 1) {
      await postLogin(requeteLogin({ login: 'gilles', password: 'x' }));
    }
    vi.mocked(authenticate).mockResolvedValue('session-odoo');
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);
    // Sinon la limite ne coûterait rien à qui finit par trouver le mot de passe.
    expect((await postLogin(requeteLogin({ login: 'gilles', password: 'bon' }))).status).toBe(429);
  });

  it('indique un délai de réessai quand il limite', async () => {
    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    let reponse = await postLogin(requeteLogin({ login: 'gilles', password: 'x' }));
    for (let essai = 0; essai < 10; essai += 1) {
      reponse = await postLogin(requeteLogin({ login: 'gilles', password: 'x' }));
    }
    expect(Number(reponse.headers.get('retry-after'))).toBeGreaterThan(0);
  });

  it('distingue « c’est le serveur » de « c’est vous »', async () => {
    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('unavailable'));
    const reponse = await postLogin(requeteLogin({ login: 'gilles', password: 'x' }));
    // Le message reste générique, mais le statut permet au poste terrain de
    // savoir qu'il peut réessayer.
    expect(reponse.status).toBe(503);
  });

  it('ne renvoie jamais le mot de passe soumis', async () => {
    vi.mocked(authenticate).mockRejectedValue(new OpsGatewayError('invalid_credentials'));
    const reponse = await postLogin(
      requeteLogin({ login: 'gilles', password: 'motdepasse-reconnaissable' }),
    );
    expect(await reponse.text()).not.toContain('motdepasse-reconnaissable');
  });
});

describe('GET /api/me', () => {
  it('interroge Odoo et renvoie l’identité', async () => {
    magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
    vi.mocked(fetchIdentity).mockResolvedValue(IDENTITE);

    const reponse = await getMe();
    expect(reponse.status).toBe(200);
    // La route ne déduit rien du cookie : elle demande.
    expect(fetchIdentity).toHaveBeenCalledTimes(1);
    await expect(reponse.json()).resolves.toEqual({ success: true, data: IDENTITE });
  });

  it('renvoie 401 sans cookie', async () => {
    const reponse = await getMe();
    expect(reponse.status).toBe(401);
    expect(fetchIdentity).not.toHaveBeenCalled();
  });

  it('renvoie 401 quand Odoo ne reconnaît plus la session', async () => {
    magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
    vi.mocked(fetchIdentity).mockRejectedValue(new OpsGatewayError('forbidden'));
    expect((await getMe()).status).toBe(401);
  });

  it('n’est jamais mis en cache', async () => {
    const reponse = await getMe();
    expect(reponse.headers.get('cache-control')).toBe('no-store');
  });
});

describe('POST /api/auth/logout', () => {
  it('ferme la session et efface le cookie', async () => {
    magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
    const reponse = await postLogout();
    expect(reponse.status).toBe(200);
    expect(destroySession).toHaveBeenCalledWith('sX', expect.any(String));
    expect(magasinCookies.has(OPS_COOKIE)).toBe(false);
  });

  it('réussit sans cookie', async () => {
    expect((await postLogout()).status).toBe(200);
  });

  it('réussit deux fois de suite', async () => {
    magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
    expect((await postLogout()).status).toBe(200);
    expect((await postLogout()).status).toBe(200);
  });
});
