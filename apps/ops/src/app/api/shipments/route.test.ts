import { beforeEach, describe, expect, it, vi } from 'vitest';

import { magasinCookies, reinitialiserCookies } from '@/test/faux-cookies';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn(), opsPost: vi.fn() };
});

const { OPS_COOKIE, sealSession } = await import('@/lib/auth/session');
const { opsGet, opsPost, OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const { resetRateLimits } = await import('@/lib/rate-limit');
const { GET: getContexte } =
  await import('@/app/api/shipments/[reference]/wave-context/route');
const { GET: getPaiements, POST } =
  await import('@/app/api/shipments/[reference]/payments/route');

const UUID = '11111111-2222-4333-8444-555555555555';
const AXXX = 'AIR-DSS-CDG-TEST-001-A001';
const CONTEXTE = { params: Promise.resolve({ reference: AXXX }) };

const PAIEMENT = {
  reference: UUID, amount: 100000, currency_code: 'XOF', paid_at: '2026-08-28',
  payment_method: 'wave', beneficiary: 'Gilles', wave_reference: 'TWXYZ12345',
  note: '', accounting_status: 'pending',
};

const DEMANDE = {
  request_uuid: UUID, amount: 100000, currency: 'XOF',
  wave_reference: 'TWXYZ12345', paid_at: '2026-08-28', note: '',
};

function avecSession() {
  magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
}

function requete(corps: unknown, headers: Record<string, string> = {}): Request {
  return new Request(`https://ops.example.test/api/shipments/${AXXX}/payments`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      origin: 'https://ops.example.test',
      'x-forwarded-for': '203.0.113.9',
      ...headers,
    },
    body: typeof corps === 'string' ? corps : JSON.stringify(corps),
  });
}

beforeEach(() => {
  reinitialiserCookies();
  resetRateLimits();
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsPost).mockReset();
});

describe('GET /api/shipments/<Axxx>/wave-context', () => {
  it('sert le contexte du dossier avec la session seule', async () => {
    avecSession();
    vi.mocked(opsGet).mockResolvedValue({
      intake_reference: AXXX, customer_name: 'Aissatou', payment_method: 'wave',
      beneficiary: 'Gilles', currencies: ['XOF'],
      payments: { items: [], summary: [] },
    });
    const reponse = await getContexte(new Request('https://x/'), CONTEXTE);
    expect(reponse.status).toBe(200);
    expect(opsGet).toHaveBeenCalledWith(
      `shipments/${AXXX}/wave-context`, 'sX', expect.any(String));
    expect((await reponse.json()).data.beneficiary).toBe('Gilles');
  });

  it('refuse sans session', async () => {
    expect((await getContexte(new Request('https://x/'), CONTEXTE)).status).toBe(401);
  });

  it('rend 404 sur un dossier introuvable', async () => {
    avecSession();
    vi.mocked(opsGet).mockRejectedValue(new OpsGatewayError('not_found'));
    expect((await getContexte(new Request('https://x/'), CONTEXTE)).status).toBe(404);
  });

  it('dit qu’un bénéficiaire manquant se corrige, plutôt qu’une panne', async () => {
    avecSession();
    vi.mocked(opsGet).mockRejectedValue(
      new OpsGatewayError('conflict', 'x', 'wave_beneficiary_not_configured'));
    const reponse = await getContexte(new Request('https://x/'), CONTEXTE);
    expect(reponse.status).toBe(409);
    expect((await reponse.json()).error).toContain('responsable');
  });
});

describe('POST /api/shipments/<Axxx>/payments', () => {
  it('relaie la demande stricte avec la session seule', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', payment: PAIEMENT });
    const reponse = await POST(requete(DEMANDE), CONTEXTE);
    expect(reponse.status).toBe(200);
    expect(opsPost).toHaveBeenCalledWith(
      `shipments/${AXXX}/payments`, DEMANDE, 'sX', expect.any(String));
  });

  it('refuse sans session', async () => {
    expect((await POST(requete(DEMANDE), CONTEXTE)).status).toBe(401);
  });

  it('refuse une origine étrangère', async () => {
    avecSession();
    const reponse = await POST(
      requete(DEMANDE, { origin: 'https://ailleurs.test' }), CONTEXTE);
    expect(reponse.status).toBe(403);
    expect(opsPost).not.toHaveBeenCalled();
  });

  it.each(['payment_method', 'beneficiary', 'beneficiary_user_id', 'partner_id',
           'customer_id', 'shipment_id'])(
    'refuse un champ serveur glissé dans le corps : %s', async (cle) => {
      avecSession();
      const reponse = await POST(requete({ ...DEMANDE, [cle]: 'x' }), CONTEXTE);
      expect(reponse.status).toBe(400);
      expect(opsPost).not.toHaveBeenCalled();
    });

  it('traduit une référence Wave déjà utilisée en message actionnable', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(
      new OpsGatewayError('conflict', 'x', 'wave_reference_already_used'));
    const reponse = await POST(requete(DEMANDE), CONTEXTE);
    expect(reponse.status).toBe(409);
    expect((await reponse.json()).error).toContain('déjà été enregistrée');
  });

  it('traduit un refus de contenu en 422 et non en panne', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(
      new OpsGatewayError('unprocessable', 'x', 'invalid_wave_reference'));
    const reponse = await POST(requete(DEMANDE), CONTEXTE);
    expect(reponse.status).toBe(422);
    expect((await reponse.json()).code).toBe('invalid_wave_reference');
  });

  it('ne relaie jamais le message d’Odoo', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(new OpsGatewayError(
      'unprocessable', 'journal BNK1 introuvable sur company 3',
      'payment_channel_not_available'));
    const texte = await (await POST(requete(DEMANDE), CONTEXTE)).text();
    expect(texte).not.toContain('BNK1');
    expect(texte).not.toContain('company 3');
  });
});

describe('GET /api/shipments/<Axxx>/payments', () => {
  it('sert la liste et son résumé', async () => {
    avecSession();
    vi.mocked(opsGet).mockResolvedValue({
      intake_reference: AXXX, items: [PAIEMENT],
      summary: [{ currency_code: 'XOF', amount: 100000 }],
    });
    const reponse = await getPaiements(new Request('https://x/'), CONTEXTE);
    expect(reponse.status).toBe(200);
    expect((await reponse.json()).data.summary).toHaveLength(1);
  });

  it('refuse sans session', async () => {
    expect((await getPaiements(new Request('https://x/'), CONTEXTE)).status).toBe(401);
  });
});
