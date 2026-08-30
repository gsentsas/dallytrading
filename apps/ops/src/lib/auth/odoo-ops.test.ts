import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  OpsGatewayError,
  authenticate,
  destroySession,
  fetchIdentity,
  opsGet,
  opsPost,
  opsPostFichier,
} from '@/lib/auth/odoo-ops';

const SOURCE = readFileSync(fileURLToPath(new URL('./odoo-ops.ts', import.meta.url)), 'utf8');

function reponseJson(charge: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(charge), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

function reponseAuthentifiee(uid: number, sessionId: string): Response {
  const enTetes = new Headers({ 'content-type': 'application/json' });
  enTetes.append('set-cookie', `session_id=${sessionId}; Path=/; HttpOnly`);
  return new Response(JSON.stringify({ jsonrpc: '2.0', result: { uid } }), {
    status: 200,
    headers: enTetes,
  });
}

const IDENTITE = {
  user: { name: 'Gilles', login: 'gilles' },
  role: 'logistician' as const,
  cash_actor: 'Gilles',
  cash_actor_configured: true,
  capabilities: { intake_create: true, payment_create: true, supervise: false },
};

let appelsFetch: Array<{ url: string; init: RequestInit }>;

beforeEach(() => {
  appelsFetch = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function espionner(reponse: Response | (() => Promise<Response>)) {
  const faux = vi.fn(async (url: string | URL, init: RequestInit = {}) => {
    appelsFetch.push({ url: String(url), init });
    return typeof reponse === 'function' ? reponse() : reponse;
  });
  vi.stubGlobal('fetch', faux);
  return faux;
}

describe('incapacité structurelle d’utiliser une clé privilégiée', () => {
  it('ne mentionne aucune clé d’intégration dans son code source', () => {
    // Ce test est un garde-fou de conception : si quelqu'un ajoute un jour une
    // clé ici, la passerelle cesserait de transporter uniquement la session de
    // l'opérateur et emprunterait les droits d'une intégration.
    for (const interdit of [
      'DALLY_FREIGHT_SYNC_API_KEY',
      'DALLY_FREIGHT_BILLING_API_KEY',
      'ODOO_API_KEY',
      'X-API-Key',
      'Authorization',
    ]) {
      // Le nom apparaît dans la documentation en tête de fichier ; on ne
      // cherche donc qu'en dehors des commentaires.
      const code = SOURCE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
      expect(code).not.toContain(interdit);
    }
  });

  it('ne lit jamais process.env directement', () => {
    // Toute la configuration passe par `opsEnv()`, dont le schéma ne comporte
    // aucune clé. Lire `process.env` ici court-circuiterait cette garantie.
    const code = SOURCE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    expect(code).not.toContain('process.env');
  });

  it('n’envoie que Content-Type, X-Request-ID et le cookie de session', async () => {
    espionner(reponseJson({ success: true, data: IDENTITE }));
    await fetchIdentity('session-abc', 'corr-1');
    const enTetes = appelsFetch[0]?.init.headers as Record<string, string>;
    expect(Object.keys(enTetes).sort()).toEqual(['Content-Type', 'Cookie', 'X-Request-ID']);
    expect(enTetes.Cookie).toBe('session_id=session-abc');
  });
});

describe('liste blanche des chemins', () => {
  it('refuse un chemin hors du périmètre Ops avant toute émission', async () => {
    const faux = espionner(reponseJson({}));
    // `fetchIdentity` ne permet pas de choisir le chemin ; on prouve la
    // barrière par le seul point d'entrée qui accepte une session arbitraire.
    await expect(fetchIdentity('a b', 'corr')).rejects.toThrow(OpsGatewayError);
    expect(faux).not.toHaveBeenCalled();
  });

  it('n’expose aucune fonction visant la famille /api/v1/freight', () => {
    const code = SOURCE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    expect(code).not.toContain('/api/v1/freight');
  });
});

describe('lecture d’une ressource Ops', () => {
  it('ajoute elle-même le préfixe du périmètre', async () => {
    espionner(reponseJson({ success: true, data: { consolidations: [] } }));
    await opsGet('consolidations', 'session-abc', 'corr');
    // L'appelant nomme la ressource, jamais le chemin : sortir du périmètre
    // devient impossible à écrire, et pas seulement interdit.
    expect(appelsFetch[0]?.url).toBe('https://odoo.example.test/api/v1/ops/consolidations');
  });

  it.each([
    ['une remontée de répertoire', '../freight/consolidations/open'],
    ['un chemin absolu', '/api/v1/freight/consolidations/open'],
    ['un hôte complet', 'https://ailleurs.test/x'],
    ['une ressource vide', ''],
    ['un point', 'consolidations/.'],
    ['un espace', 'intakes/AIR 001'],
    ['une chaîne de requête', 'intakes?x=1'],
  ])('refuse %s avant toute émission', async (_cas, ressource) => {
    const faux = espionner(reponseJson({ success: true, data: {} }));
    await expect(opsGet(ressource, 'session-abc', 'corr')).rejects.toMatchObject({
      code: 'invalid_path',
    });
    expect(faux).not.toHaveBeenCalled();
  });

  it('accepte une référence de dossier en majuscules', async () => {
    espionner(reponseJson({ success: true, data: {} }));
    await opsGet('intakes/AIR-DSS-CDG-2026-002', 'session-abc', 'corr');
    // Les références métier sont en majuscules depuis l'étape 8 ; ce qui reste
    // exclu, c'est le point, l'espace et la chaîne de requête.
    expect(appelsFetch[0]?.url).toBe(
      'https://odoo.example.test/api/v1/ops/intakes/AIR-DSS-CDG-2026-002');
  });

  it('renvoie la charge « data » et rien d’autre', async () => {
    espionner(reponseJson({ success: true, data: { consolidations: [1, 2] } }));
    await expect(opsGet('consolidations', 'session-abc', 'corr')).resolves.toEqual({
      consolidations: [1, 2],
    });
  });

  it('traduit un 403 en refus', async () => {
    espionner(new Response('{}', { status: 403 }));
    await expect(opsGet('consolidations', 'session-abc', 'corr')).rejects.toMatchObject({
      code: 'forbidden',
    });
  });
});

describe('ouverture de session Odoo', () => {
  it('renvoie l’identifiant de session lu dans Set-Cookie', async () => {
    espionner(reponseAuthentifiee(7, 'session-xyz'));
    await expect(authenticate('gilles', 'motdepasse', 'corr')).resolves.toBe('session-xyz');
  });

  it('vise bien /web/session/authenticate avec la base configurée', async () => {
    espionner(reponseAuthentifiee(7, 'session-xyz'));
    await authenticate('gilles', 'motdepasse', 'corr');
    expect(appelsFetch[0]?.url).toBe('https://odoo.example.test/web/session/authenticate');
    const corps = JSON.parse(String(appelsFetch[0]?.init.body)) as {
      params: { db: string; login: string };
    };
    expect(corps.params.db).toBe('banc');
    expect(corps.params.login).toBe('gilles');
  });

  it('ne suit pas les redirections', async () => {
    espionner(reponseAuthentifiee(7, 'session-xyz'));
    await authenticate('gilles', 'motdepasse', 'corr');
    // Suivre une redirection vers /web/login transformerait un refus en 200.
    expect(appelsFetch[0]?.init.redirect).toBe('manual');
    expect(appelsFetch[0]?.init.cache).toBe('no-store');
  });

  it('refuse un identifiant inconnu et un mot de passe faux de la même façon', async () => {
    espionner(reponseJson({ jsonrpc: '2.0', result: { uid: false } }));
    const inconnu = await authenticate('fantome', 'x', 'corr').catch((e: OpsGatewayError) => e.code);
    espionner(reponseJson({ jsonrpc: '2.0', error: { message: 'Access Denied' } }));
    const faux = await authenticate('gilles', 'x', 'corr').catch((e: OpsGatewayError) => e.code);
    expect(inconnu).toBe('invalid_credentials');
    expect(faux).toBe('invalid_credentials');
  });

  it('signale l’indisponibilité quand Odoo n’ouvre aucune session', async () => {
    espionner(reponseJson({ jsonrpc: '2.0', result: { uid: 7 } }));
    await expect(authenticate('gilles', 'x', 'corr')).rejects.toMatchObject({
      code: 'unavailable',
    });
  });

  it('signale l’indisponibilité quand le réseau échoue', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('ECONNREFUSED');
      }),
    );
    await expect(authenticate('gilles', 'x', 'corr')).rejects.toMatchObject({
      code: 'unavailable',
    });
  });
});

describe('lecture de l’identité', () => {
  it('renvoie l’identité fournie par Odoo', async () => {
    espionner(reponseJson({ success: true, data: IDENTITE }));
    await expect(fetchIdentity('session-abc', 'corr')).resolves.toEqual(IDENTITE);
  });

  it('vise /api/v1/ops/me', async () => {
    espionner(reponseJson({ success: true, data: IDENTITE }));
    await fetchIdentity('session-abc', 'corr');
    expect(appelsFetch[0]?.url).toBe('https://odoo.example.test/api/v1/ops/me');
    expect(appelsFetch[0]?.init.method).toBe('GET');
  });

  it('traduit un 403 en refus', async () => {
    espionner(new Response('{}', { status: 403 }));
    await expect(fetchIdentity('session-abc', 'corr')).rejects.toMatchObject({
      code: 'forbidden',
    });
  });

  it('traite une redirection comme un refus', async () => {
    // Odoo redirige vers /web/login quand la session n'est plus valide.
    espionner(new Response(null, { status: 303, headers: { location: '/web/login' } }));
    await expect(fetchIdentity('session-abc', 'corr')).rejects.toMatchObject({
      code: 'forbidden',
    });
  });

  it('refuse une réponse sans succès déclaré', async () => {
    espionner(reponseJson({ success: false }));
    await expect(fetchIdentity('session-abc', 'corr')).rejects.toMatchObject({
      code: 'unavailable',
    });
  });
});

describe('fermeture de session', () => {
  it('n’échoue pas si Odoo est injoignable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('ECONNREFUSED');
      }),
    );
    // Une déconnexion qui lève laisserait un opérateur connecté sur un
    // terminal partagé.
    await expect(destroySession('session-abc', 'corr')).resolves.toBeUndefined();
  });

  it('vise /web/session/destroy avec la session de l’opérateur', async () => {
    espionner(reponseJson({ result: true }));
    await destroySession('session-abc', 'corr');
    expect(appelsFetch[0]?.url).toBe('https://odoo.example.test/web/session/destroy');
    expect((appelsFetch[0]?.init.headers as Record<string, string>).Cookie).toBe(
      'session_id=session-abc',
    );
  });
});


describe('un contenu refusé n’est pas une panne', () => {
  it('distingue le 422 d’Odoo d’un service indisponible', async () => {
    espionner(reponseJson(
      { success: false, error: { code: 'invalid_expense_date', message: 'x' } },
      { status: 422 },
    ));
    // Sans ce cas, une date future remontait en « service momentanément
    // indisponible » : l'opérateur aurait attendu au lieu de corriger.
    await expect(opsPost('expenses', {}, 'session-abc', 'corr')).rejects.toMatchObject({
      code: 'unprocessable',
      conflictCode: 'invalid_expense_date',
    });
  });

  it('ne relaie pas le message d’Odoo, seulement son code', async () => {
    espionner(reponseJson(
      { success: false,
        error: { code: 'currency_not_available', message: 'XOF inactive on company 3' } },
      { status: 422 },
    ));
    const erreur = await opsPost('expenses', {}, 'session-abc', 'corr')
      .then(() => null, (e: unknown) => e as OpsGatewayError);
    expect(erreur).toBeInstanceOf(OpsGatewayError);
    expect(erreur?.message).not.toContain('company 3');
    expect(erreur?.conflictCode).toBe('currency_not_available');
  });
});

describe('dépôt d’un fichier sur une ressource Ops', () => {
  function fichier() {
    return {
      nom: 'ticket.jpg',
      type: 'image/jpeg',
      contenu: new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: 'image/jpeg' }),
    };
  }

  it('ajoute lui-même le préfixe du périmètre', async () => {
    espionner(reponseJson({ success: true, data: { status: 'attached' } }));
    await opsPostFichier('expenses/ref-1/receipt', fichier(), {}, 'session-abc', 'corr');
    expect(appelsFetch[0]?.url).toContain('/api/v1/ops/expenses/ref-1/receipt');
  });

  it('refuse une ressource hors du périmètre avant toute émission', async () => {
    const faux = espionner(reponseJson({}));
    await expect(opsPostFichier(
      '../freight/sync', fichier(), {}, 'session-abc', 'corr',
    )).rejects.toThrow(OpsGatewayError);
    expect(faux).not.toHaveBeenCalled();
  });

  it('laisse le navigateur poser le type multipart et sa frontière', async () => {
    espionner(reponseJson({ success: true, data: { status: 'attached' } }));
    await opsPostFichier('expenses/ref-1/receipt', fichier(), {}, 'session-abc', 'corr');
    const enTetes = appelsFetch[0]?.init.headers as Record<string, string>;
    // Écrire `Content-Type` nous-mêmes produirait un corps sans frontière,
    // donc illisible pour Odoo.
    expect(Object.keys(enTetes).sort()).toEqual(['Cookie', 'X-Request-ID']);
    expect(appelsFetch[0]?.init.body).toBeInstanceOf(FormData);
  });

  it('transporte les champs de texte et le fichier sous le nom attendu', async () => {
    espionner(reponseJson({ success: true, data: { status: 'attached' } }));
    await opsPostFichier(
      'expenses/ref-1/receipt', fichier(), { request_uuid: 'abc' }, 'session-abc', 'corr');
    const corps = appelsFetch[0]?.init.body as FormData;
    expect(corps.get('request_uuid')).toBe('abc');
    expect(corps.get('receipt')).toBeInstanceOf(File);
  });

  it('n’emprunte aucune clé : seul le cookie de session voyage', async () => {
    espionner(reponseJson({ success: true, data: { status: 'attached' } }));
    await opsPostFichier('expenses/ref-1/receipt', fichier(), {}, 'session-abc', 'corr');
    const enTetes = appelsFetch[0]?.init.headers as Record<string, string>;
    expect(enTetes.Cookie).toBe('session_id=session-abc');
    expect(enTetes.Authorization).toBeUndefined();
  });

  it('traduit un justificatif déjà présent en conflit nommé', async () => {
    espionner(reponseJson(
      { success: false, error: { code: 'receipt_already_attached', message: 'x' } },
      { status: 409 },
    ));
    await expect(opsPostFichier(
      'expenses/ref-1/receipt', fichier(), {}, 'session-abc', 'corr',
    )).rejects.toMatchObject({ code: 'conflict', conflictCode: 'receipt_already_attached' });
  });
});
