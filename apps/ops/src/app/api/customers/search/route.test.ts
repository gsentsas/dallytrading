import { beforeEach, describe, expect, it, vi } from 'vitest';

import { magasinCookies, reinitialiserCookies } from '@/test/faux-cookies';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsPost: vi.fn() };
});

const { OPS_COOKIE, sealSession } = await import('@/lib/auth/session');
const { opsPost, OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const { resetRateLimits, OPS_RECHERCHE_SESSION } = await import('@/lib/rate-limit');
const { POST } = await import('@/app/api/customers/search/route');

const CLIENT = {
  reference: 'b9c8c46f-1f2e-4a3b-9c8d-7e6f5a4b3c2d',
  name: 'Aissatou Kandji',
  phone: '+33 6 12 34 56 78',
  email: 'client@example.com',
  address: '207 rue Saint-Charles, 75015 Paris, France',
  customer_type: 'individual',
};

function requete(corps: unknown, enTetes: Record<string, string> = {}): Request {
  return new Request('https://ops.example.test/api/customers/search', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-forwarded-for': '203.0.113.9', ...enTetes },
    body: typeof corps === 'string' ? corps : JSON.stringify(corps),
  });
}

function avecSession() {
  magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
}

beforeEach(() => {
  reinitialiserCookies();
  resetRateLimits();
  vi.mocked(opsPost).mockReset();
});

describe('POST /api/customers/search', () => {
  it('relaie le client trouvé', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'match', customer: CLIENT });

    const reponse = await POST(requete({ phone: '+221 77 123 45 67' }));
    expect(reponse.status).toBe(200);
    await expect(reponse.json()).resolves.toEqual({
      success: true, data: { status: 'match', customer: CLIENT },
    });
  });

  it('présente la session de l’opérateur et le seul critère soumis', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'not_found', customer: null });
    await POST(requete({ phone: '771234567' }));
    expect(opsPost).toHaveBeenCalledWith(
      'customers/search', { phone: '771234567' }, 'sX', expect.any(String));
  });

  it('relaie l’absence de correspondance', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'not_found', customer: null });
    const charge = await (await POST(requete({ phone: '771234567' }))).json();
    expect(charge).toEqual({ success: true, data: { status: 'not_found', customer: null } });
  });

  it('relaie l’ambiguïté sans aucune identité', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'ambiguous', customer: null });
    const texte = await (await POST(requete({ phone: '771234567' }))).text();
    expect(JSON.parse(texte)).toEqual({
      success: true, data: { status: 'ambiguous', customer: null },
    });
    expect(texte).not.toContain('Aissatou');
  });
});

describe('ce que la route refuse', () => {
  it('renvoie 401 sans cookie, sans interroger Odoo', async () => {
    const reponse = await POST(requete({ phone: '771234567' }));
    expect(reponse.status).toBe(401);
    expect(opsPost).not.toHaveBeenCalled();
  });

  it('renvoie 401 quand Odoo ne reconnaît plus la session', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(new OpsGatewayError('forbidden'));
    expect((await POST(requete({ phone: '771234567' }))).status).toBe(401);
  });

  it('renvoie 503 quand Odoo est indisponible', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(new OpsGatewayError('unavailable'));
    expect((await POST(requete({ phone: '771234567' }))).status).toBe(503);
  });

  it('refuse une recherche par nom sans interroger Odoo', async () => {
    avecSession();
    const reponse = await POST(requete({ name: 'Mamadou' }));
    expect(reponse.status).toBe(400);
    expect(opsPost).not.toHaveBeenCalled();
  });

  it('refuse une clé inconnue glissée à côté du critère', async () => {
    avecSession();
    expect((await POST(requete({ phone: '771234567', company_id: 1 }))).status).toBe(400);
    expect(opsPost).not.toHaveBeenCalled();
  });

  it('refuse une requête qui n’est pas du JSON', async () => {
    avecSession();
    const reponse = await POST(requete({ phone: '7' }, { 'content-type': 'text/plain' }));
    expect(reponse.status).toBe(415);
  });

  it('refuse un corps illisible', async () => {
    avecSession();
    expect((await POST(requete('{ pas du json'))).status).toBe(400);
  });

  it('refuse une origine étrangère', async () => {
    avecSession();
    const reponse = await POST(requete({ phone: '771234567' }, {
      origin: 'https://ailleurs.test',
    }));
    expect(reponse.status).toBe(403);
    expect(opsPost).not.toHaveBeenCalled();
  });

  it('accepte l’origine de l’application', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'not_found', customer: null });
    const reponse = await POST(requete({ phone: '771234567' }, {
      origin: 'https://ops.example.test',
    }));
    expect(reponse.status).toBe(200);
  });

  it('n’est jamais mise en cache', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'not_found', customer: null });
    const reponse = await POST(requete({ phone: '771234567' }));
    expect(reponse.headers.get('cache-control')).toBe('no-store');
  });
});

describe('limitation de l’énumération', () => {
  it('finit par refuser un balayage depuis une même session', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'not_found', customer: null });
    let dernier = 0;
    for (let essai = 0; essai <= OPS_RECHERCHE_SESSION.limite; essai += 1) {
      dernier = (await POST(requete({ phone: `2217712345${essai % 10}` }))).status;
    }
    expect(dernier).toBe(429);
  });

  it('indique un délai de réessai', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'not_found', customer: null });
    let reponse = await POST(requete({ phone: '771234567' }));
    for (let essai = 0; essai <= OPS_RECHERCHE_SESSION.limite; essai += 1) {
      reponse = await POST(requete({ phone: '771234567' }));
    }
    expect(Number(reponse.headers.get('retry-after'))).toBeGreaterThan(0);
  });

  it('laisse passer une réception normale', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'match', customer: CLIENT });
    // Une réception, c'est une recherche, parfois deux. Vingt d'affilée doivent
    // rester possibles.
    let dernier = 0;
    for (let essai = 0; essai < 20; essai += 1) {
      dernier = (await POST(requete({ phone: '771234567' }))).status;
    }
    expect(dernier).toBe(200);
  });
});

describe('ce qui ne doit jamais sortir', () => {
  it('ne renvoie jamais le critère soumis dans un message d’erreur', async () => {
    avecSession();
    const texte = await (await POST(requete({ phone: '+221 77 999 88 77', name: 'x' }))).text();
    // Le motif du refus décrirait le corps soumis, donc une donnée personnelle.
    expect(texte).not.toContain('77 999 88 77');
    expect(texte).not.toContain('771234567');
  });

  it('ne journalise ni numéro, ni adresse, ni nom', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'match', customer: CLIENT });

    const lignes: string[] = [];
    const espions = (['log', 'warn', 'error'] as const).map((niveau) =>
      vi.spyOn(console, niveau).mockImplementation((...args: unknown[]) => {
        lignes.push(args.map(String).join(' '));
      }));
    try {
      await POST(requete({ phone: '+221 77 123 45 67' }));
    } finally {
      espions.forEach((espion) => espion.mockRestore());
    }

    const journal = lignes.join('\n');
    // Le journal retient la corrélation, l'issue et la durée — de quoi
    // diagnostiquer une panne, jamais de quoi reconstituer qui a cherché qui.
    for (const interdit of ['77 123 45 67', '771234567', 'Aissatou', 'Kandji',
                            'client@example.com', 'Saint-Charles', 'sX']) {
      expect(journal).not.toContain(interdit);
    }
    expect(journal).toContain('ops.customers.search');
    expect(journal).toContain('match');
  });

  it('ne laisse fuir aucun détail technique', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(new OpsGatewayError('unavailable', 'statut 500'));
    const texte = await (await POST(requete({ phone: '771234567' }))).text();
    for (const indice of ['statut 500', 'res.partner', 'odoo', 'sudo']) {
      expect(texte.toLowerCase()).not.toContain(indice.toLowerCase());
    }
  });
});
