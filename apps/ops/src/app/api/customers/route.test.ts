import { beforeEach, describe, expect, it, vi } from 'vitest';

import { magasinCookies, reinitialiserCookies } from '@/test/faux-cookies';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsPost: vi.fn() };
});

const { OPS_COOKIE, sealSession } = await import('@/lib/auth/session');
const { opsPost, OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const { resetRateLimits, OPS_CREATION_SESSION } = await import('@/lib/rate-limit');
const { POST } = await import('@/app/api/customers/route');

const CLIENT = {
  reference: 'b9c8c46f-1f2e-4a3b-9c8d-7e6f5a4b3c2d',
  name: 'Aissatou Kandji',
  phone: '+221 77 123 45 67',
  email: 'client@example.com',
  address: '207 rue Saint-Charles, 75015 Paris',
  customer_type: 'individual',
};

function demande(surcharges: Record<string, unknown> = {}) {
  return {
    request_uuid: '11111111-2222-4333-8444-555555555555',
    customer_type: 'individual',
    name: 'Aissatou Kandji',
    phone: '+221 77 123 45 67',
    email: 'client@example.com',
    address: '207 rue Saint-Charles, 75015 Paris',
    ...surcharges,
  };
}

function requete(corps: unknown, enTetes: Record<string, string> = {}): Request {
  return new Request('https://ops.example.test/api/customers', {
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

describe('POST /api/customers', () => {
  it('relaie la fiche créée', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', customer: CLIENT });
    const reponse = await POST(requete(demande()));
    expect(reponse.status).toBe(200);
    await expect(reponse.json()).resolves.toEqual({
      success: true, data: { status: 'created', customer: CLIENT },
    });
  });

  it('relaie une fiche déjà existante comme un succès', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'existing', customer: CLIENT });
    const reponse = await POST(requete(demande()));
    // « Existe déjà » n'est pas une erreur : c'est souvent la bonne issue.
    expect(reponse.status).toBe(200);
    expect((await reponse.json()).data.status).toBe('existing');
  });

  it('transmet la demande telle que validée, avec son identifiant', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', customer: CLIENT });
    await POST(requete(demande()));
    expect(opsPost).toHaveBeenCalledWith(
      'customers', expect.objectContaining({
        request_uuid: '11111111-2222-4333-8444-555555555555',
      }), 'sX', expect.any(String));
  });

  it('accepte une demande sans adresse électronique', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', customer: CLIENT });
    const corps = demande();
    delete (corps as Record<string, unknown>).email;
    expect((await POST(requete(corps))).status).toBe(200);
  });
});

describe('ce que la route refuse', () => {
  it.each([
    ['sans identifiant de demande', 'request_uuid'],
    ['sans type de client', 'customer_type'],
    ['sans nom', 'name'],
    ['sans téléphone', 'phone'],
    ['sans adresse', 'address'],
  ])('refuse une demande %s', async (_cas, champ) => {
    avecSession();
    const corps = demande();
    delete (corps as Record<string, unknown>)[champ];
    expect((await POST(requete(corps))).status).toBe(400);
    expect(opsPost).not.toHaveBeenCalled();
  });

  it('refuse un identifiant de demande qui n’est pas un UUID', async () => {
    avecSession();
    expect((await POST(requete(demande({ request_uuid: 'x' })))).status).toBe(400);
  });

  it.each(['partner_id', 'is_company', 'company_id', 'credit_limit', 'user_id'])(
    'refuse la clé %s', async (cle) => {
      avecSession();
      // Une clé acceptée ici deviendrait une colonne de res.partner écrite par
      // le navigateur.
      expect((await POST(requete(demande({ [cle]: 1 })))).status).toBe(400);
      expect(opsPost).not.toHaveBeenCalled();
    });

  it('refuse un type de client inconnu', async () => {
    avecSession();
    expect((await POST(requete(demande({ customer_type: 'prospect' })))).status).toBe(400);
  });

  it('renvoie 401 sans cookie', async () => {
    expect((await POST(requete(demande()))).status).toBe(401);
    expect(opsPost).not.toHaveBeenCalled();
  });

  it('renvoie 401 quand Odoo ne reconnaît plus la session', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(new OpsGatewayError('forbidden'));
    expect((await POST(requete(demande()))).status).toBe(401);
  });

  it('renvoie 503 quand Odoo est indisponible', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(new OpsGatewayError('unavailable'));
    expect((await POST(requete(demande()))).status).toBe(503);
  });

  it('refuse une origine étrangère', async () => {
    avecSession();
    expect((await POST(requete(demande(), { origin: 'https://ailleurs.test' }))).status).toBe(403);
  });

  it('refuse une requête qui n’est pas du JSON', async () => {
    avecSession();
    expect((await POST(requete(demande(), { 'content-type': 'text/plain' }))).status).toBe(415);
  });
});

describe('conflits', () => {
  it('rend 409 et le code stable pour une contradiction d’identité', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(
      new OpsGatewayError('conflict', 'conflit', 'customer_identity_conflict'));
    const reponse = await POST(requete(demande()));
    expect(reponse.status).toBe(409);
    const charge = await reponse.json();
    expect(charge.code).toBe('customer_identity_conflict');
    expect(charge.error).toContain('plusieurs fiches');
  });

  it('rend 409 pour un identifiant rejoué avec une autre intention', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(
      new OpsGatewayError('conflict', 'conflit', 'idempotency_conflict'));
    const charge = await (await POST(requete(demande()))).json();
    expect(charge.code).toBe('idempotency_conflict');
  });

  it('ne laisse fuir aucune identité dans un conflit', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(
      new OpsGatewayError('conflict', 'conflit', 'customer_identity_conflict'));
    const texte = await (await POST(requete(demande()))).text();
    for (const interdit of ['Aissatou', 'Kandji', '77 123 45 67', 'client@example.com']) {
      expect(texte).not.toContain(interdit);
    }
  });
});

describe('limitation des créations', () => {
  it('finit par refuser un flot de créations distinctes', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', customer: CLIENT });
    let dernier = 0;
    for (let essai = 0; essai <= OPS_CREATION_SESSION.limite; essai += 1) {
      dernier = (await POST(requete(demande({
        request_uuid: `11111111-2222-4333-8444-5555555555${String(essai).padStart(2, '0')}`,
      })))).status;
    }
    expect(dernier).toBe(429);
  });

  it('ne compte pas les tentatives réseau d’une même demande', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', customer: CLIENT });
    // Une 4G capricieuse ne doit pas punir l'opérateur.
    let dernier = 0;
    for (let essai = 0; essai <= OPS_CREATION_SESSION.limite * 3; essai += 1) {
      dernier = (await POST(requete(demande()))).status;
    }
    expect(dernier).toBe(200);
  });

  it('borne la session plus serré que la recherche', async () => {
    // Créer un client est un geste rare ; chercher, non.
    expect(OPS_CREATION_SESSION.limite).toBe(20);
  });
});

describe('ce qui ne doit jamais sortir', () => {
  it('ne journalise ni nom, ni numéro, ni adresse', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', customer: CLIENT });

    const lignes: string[] = [];
    const espions = (['log', 'warn', 'error'] as const).map((niveau) =>
      vi.spyOn(console, niveau).mockImplementation((...args: unknown[]) => {
        lignes.push(args.map(String).join(' '));
      }));
    try {
      await POST(requete(demande()));
    } finally {
      espions.forEach((espion) => espion.mockRestore());
    }

    const journal = lignes.join('\n');
    for (const interdit of ['Aissatou', 'Kandji', '77 123 45 67', 'client@example.com',
                            'Saint-Charles', 'sX']) {
      expect(journal).not.toContain(interdit);
    }
    expect(journal).toContain('ops.customers.create');
  });

  it('n’est jamais mise en cache', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', customer: CLIENT });
    expect((await POST(requete(demande()))).headers.get('cache-control')).toBe('no-store');
  });

  it('refuse un DTO qui porterait un identifiant Odoo', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({
      status: 'created', customer: { ...CLIENT, partner_id: 3728 },
    });
    expect((await POST(requete(demande()))).status).toBe(503);
  });
});
