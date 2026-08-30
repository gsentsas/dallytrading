import { beforeEach, describe, expect, it, vi } from 'vitest';

import { magasinCookies, reinitialiserCookies } from '@/test/faux-cookies';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn(), opsPost: vi.fn(), opsPostFichier: vi.fn() };
});

const { OPS_COOKIE, sealSession } = await import('@/lib/auth/session');
const { opsGet, opsPost, opsPostFichier, OpsGatewayError } =
  await import('@/lib/auth/odoo-ops');
const { resetRateLimits } = await import('@/lib/rate-limit');
const { POST } = await import('@/app/api/expenses/route');
const { GET: getDeparts } = await import('@/app/api/expense-consolidations/route');
const { GET: getDepenses } =
  await import('@/app/api/consolidations/[reference]/expenses/route');
const { POST: postJustificatif } =
  await import('@/app/api/expenses/[reference]/receipt/route');

const UUID = '11111111-2222-4333-8444-555555555555';

const DEMANDE = {
  request_uuid: UUID,
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  expense_date: '2026-08-20',
  category: 'Manutention',
  description: 'Portage entrepôt',
  beneficiary: 'Équipe entrepôt',
  amount: 15000,
  currency_code: 'XOF',
  payment_method: 'cash',
  comment: '',
};

const DEPENSE = {
  reference: UUID,
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  expense_date: '2026-08-20',
  category: 'Manutention',
  description: 'Portage entrepôt',
  beneficiary: 'Équipe entrepôt',
  amount: 15000,
  currency_code: 'XOF',
  payment_method: 'cash',
  paid_by: 'Gilles',
  state: 'review',
  has_receipt: false,
  can_attach_receipt: true,
};

function avecSession() {
  magasinCookies.set(OPS_COOKIE, sealSession({ odooSessionId: 'sX', issuedAt: Date.now() }));
}

function requete(corps: unknown, headers: Record<string, string> = {}): Request {
  return new Request('https://ops.example.test/api/expenses', {
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

/** Une photo minimale : ce qui compte, ce sont ses premiers octets. */
function photo(taille = 128, type = 'image/jpeg'): File {
  const octets = new Uint8Array(taille);
  octets.set([0xff, 0xd8, 0xff, 0xe0]);
  return new File([octets], 'ticket.jpg', { type });
}

function requeteJustificatif(
  fichier: File | null,
  requestUuid: string | null = UUID,
  headers: Record<string, string> = {},
): Request {
  const corps = new FormData();
  if (requestUuid !== null) corps.append('request_uuid', requestUuid);
  if (fichier) corps.append('receipt', fichier);
  return new Request('https://ops.example.test/api/expenses/ref-1/receipt', {
    method: 'POST',
    headers: { origin: 'https://ops.example.test', 'x-forwarded-for': '203.0.113.9', ...headers },
    body: corps,
  });
}

const CONTEXTE = { params: Promise.resolve({ reference: 'ref-1' }) };

beforeEach(() => {
  reinitialiserCookies();
  resetRateLimits();
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsPost).mockReset();
  vi.mocked(opsPostFichier).mockReset();
});

describe('POST /api/expenses', () => {
  it('relaie la demande stricte avec la session seule', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', expense: DEPENSE });
    const reponse = await POST(requete(DEMANDE));
    expect(reponse.status).toBe(200);
    expect(opsPost).toHaveBeenCalledWith('expenses', DEMANDE, 'sX', expect.any(String));
  });

  it('refuse sans session', async () => {
    expect((await POST(requete(DEMANDE))).status).toBe(401);
  });

  it('refuse une origine étrangère', async () => {
    avecSession();
    const reponse = await POST(requete(DEMANDE, { origin: 'https://ailleurs.test' }));
    expect(reponse.status).toBe(403);
    expect(opsPost).not.toHaveBeenCalled();
  });

  it.each(['state', 'source', 'actor_name', 'consolidation_id'])(
    'refuse un champ serveur glissé dans le corps : %s', async (cle) => {
      avecSession();
      const reponse = await POST(requete({ ...DEMANDE, [cle]: 'x' }));
      expect(reponse.status).toBe(400);
      expect(opsPost).not.toHaveBeenCalled();
    });

  it('traduit un refus de contenu en 422 et non en panne', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(
      new OpsGatewayError('unprocessable', 'x', 'invalid_expense_date'));
    const reponse = await POST(requete(DEMANDE));
    expect(reponse.status).toBe(422);
    const charge = await reponse.json();
    expect(charge.code).toBe('invalid_expense_date');
    expect(charge.error).toContain('date');
  });

  it('traduit un acteur de caisse absent en message actionnable', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(
      new OpsGatewayError('conflict', 'x', 'cash_actor_not_configured'));
    const reponse = await POST(requete(DEMANDE));
    expect(reponse.status).toBe(409);
    expect((await reponse.json()).error).toContain('responsable');
  });

  it('ne relaie jamais le message d’Odoo', async () => {
    avecSession();
    vi.mocked(opsPost).mockRejectedValue(
      new OpsGatewayError('unprocessable', 'currency XOF inactive on company 3',
                          'currency_not_available'));
    const texte = await (await POST(requete(DEMANDE))).text();
    expect(texte).not.toContain('company 3');
  });
});

describe('GET /api/expense-consolidations', () => {
  it('sert les départs éligibles', async () => {
    avecSession();
    vi.mocked(opsGet).mockResolvedValue({ consolidations: [] });
    const reponse = await getDeparts();
    expect(reponse.status).toBe(200);
    expect(opsGet).toHaveBeenCalledWith(
      'expense-consolidations', 'sX', expect.any(String));
  });

  it('refuse sans session', async () => {
    expect((await getDeparts()).status).toBe(401);
  });
});

describe('GET /api/consolidations/<reference>/expenses', () => {
  it('sert la liste et son résumé', async () => {
    avecSession();
    vi.mocked(opsGet).mockResolvedValue({
      consolidation_reference: 'ref-1', expenses: [DEPENSE],
      summary: [{ currency_code: 'XOF', amount: 15000 }],
    });
    const reponse = await getDepenses(
      new Request('https://ops.example.test/x'), CONTEXTE);
    expect(reponse.status).toBe(200);
    expect((await reponse.json()).data.summary).toHaveLength(1);
  });

  it('rend 404 sur un départ introuvable', async () => {
    avecSession();
    vi.mocked(opsGet).mockRejectedValue(new OpsGatewayError('not_found'));
    const reponse = await getDepenses(
      new Request('https://ops.example.test/x'), CONTEXTE);
    expect(reponse.status).toBe(404);
  });
});

describe('POST /api/expenses/<reference>/receipt', () => {
  it('relaie la photo et l’identifiant d’envoi', async () => {
    avecSession();
    vi.mocked(opsPostFichier).mockResolvedValue({
      status: 'attached', expense: { ...DEPENSE, has_receipt: true, can_attach_receipt: false },
    });
    const reponse = await postJustificatif(requeteJustificatif(photo()), CONTEXTE);
    expect(reponse.status).toBe(200);
    expect(opsPostFichier).toHaveBeenCalledWith(
      'expenses/ref-1/receipt',
      expect.objectContaining({ nom: 'ticket.jpg', type: 'image/jpeg' }),
      { request_uuid: UUID },
      'sX', expect.any(String),
    );
  });

  it('refuse sans session', async () => {
    expect((await postJustificatif(requeteJustificatif(photo()), CONTEXTE)).status)
      .toBe(401);
  });

  it('refuse une origine étrangère', async () => {
    avecSession();
    const reponse = await postJustificatif(
      requeteJustificatif(photo(), UUID, { origin: 'https://ailleurs.test' }), CONTEXTE);
    expect(reponse.status).toBe(403);
    expect(opsPostFichier).not.toHaveBeenCalled();
  });

  it('refuse un corps JSON sur cette route', async () => {
    avecSession();
    const reponse = await postJustificatif(
      new Request('https://ops.example.test/api/expenses/ref-1/receipt', {
        method: 'POST',
        headers: { 'content-type': 'application/json',
                   origin: 'https://ops.example.test' },
        body: JSON.stringify({ receipt: 'AAAA' }),
      }),
      CONTEXTE,
    );
    expect(reponse.status).toBe(415);
  });

  it('refuse un envoi sans fichier', async () => {
    avecSession();
    const reponse = await postJustificatif(requeteJustificatif(null), CONTEXTE);
    expect(reponse.status).toBe(422);
    expect((await reponse.json()).code).toBe('receipt_missing');
    expect(opsPostFichier).not.toHaveBeenCalled();
  });

  it('refuse un identifiant d’envoi qui n’en est pas un', async () => {
    avecSession();
    const reponse = await postJustificatif(
      requeteJustificatif(photo(), 'pas-un-uuid'), CONTEXTE);
    expect(reponse.status).toBe(400);
    expect(opsPostFichier).not.toHaveBeenCalled();
  });

  it('refuse une photo trop lourde sans la transporter', async () => {
    avecSession();
    const reponse = await postJustificatif(
      requeteJustificatif(photo(10 * 1024 * 1024 + 1)), CONTEXTE);
    expect(reponse.status).toBe(422);
    expect((await reponse.json()).code).toBe('receipt_too_large');
    expect(opsPostFichier).not.toHaveBeenCalled();
  });

  it.each(['application/pdf', 'image/svg+xml', 'text/html', 'application/octet-stream'])(
    'refuse un type annoncé %s', async (type) => {
      avecSession();
      const reponse = await postJustificatif(
        requeteJustificatif(photo(64, type)), CONTEXTE);
      expect(reponse.status).toBe(422);
      expect((await reponse.json()).code).toBe('receipt_type_not_allowed');
      expect(opsPostFichier).not.toHaveBeenCalled();
    });

  it('laisse le serveur trancher sur les octets malgré un type acceptable', async () => {
    // Un fichier HTML annoncé « image/jpeg » passe le premier tri : c'est
    // attendu. Le refus vient d'Odoo, qui lit les octets.
    avecSession();
    vi.mocked(opsPostFichier).mockRejectedValue(
      new OpsGatewayError('unprocessable', 'x', 'receipt_type_not_allowed'));
    const menteur = new File([new TextEncoder().encode('<html></html>')],
                             'ticket.jpg', { type: 'image/jpeg' });
    const reponse = await postJustificatif(requeteJustificatif(menteur), CONTEXTE);
    expect(opsPostFichier).toHaveBeenCalled();
    expect(reponse.status).toBe(422);
    expect((await reponse.json()).error).toContain('JPEG');
  });

  it('dit qu’un justificatif existe déjà plutôt que de l’écraser', async () => {
    avecSession();
    vi.mocked(opsPostFichier).mockRejectedValue(
      new OpsGatewayError('conflict', 'x', 'receipt_already_attached'));
    const reponse = await postJustificatif(requeteJustificatif(photo()), CONTEXTE);
    expect(reponse.status).toBe(409);
    expect((await reponse.json()).error).toContain('déjà un justificatif');
  });

  it('rend 404 quand la dépense est introuvable', async () => {
    avecSession();
    vi.mocked(opsPostFichier).mockRejectedValue(new OpsGatewayError('not_found'));
    expect((await postJustificatif(requeteJustificatif(photo()), CONTEXTE)).status)
      .toBe(404);
  });

  it('ne journalise ni le nom du fichier ni son contenu', async () => {
    avecSession();
    vi.mocked(opsPostFichier).mockResolvedValue({
      status: 'attached', expense: { ...DEPENSE, has_receipt: true, can_attach_receipt: false },
    });
    const lignes: string[] = [];
    const espion = vi.spyOn(console, 'log').mockImplementation((...args) => {
      lignes.push(args.map(String).join(' '));
    });
    await postJustificatif(requeteJustificatif(photo()), CONTEXTE);
    espion.mockRestore();
    const journal = lignes.join('\n');
    // Sans cette première assertion, le test passerait aussi bien si rien
    // n'avait été journalisé du tout.
    expect(journal).toContain('ops.expense.receipt');
    expect(journal).not.toContain('ticket.jpg');
    expect(journal).not.toContain('image/jpeg');
  });

  it('finit par freiner les envois répétés', async () => {
    avecSession();
    vi.mocked(opsPostFichier).mockResolvedValue({
      status: 'attached', expense: { ...DEPENSE, has_receipt: true, can_attach_receipt: false },
    });
    let dernier = 200;
    for (let index = 0; index < 60; index += 1) {
      const uuid = `11111111-2222-4333-8444-${String(index).padStart(12, '0')}`;
      dernier = (await postJustificatif(
        requeteJustificatif(photo(), uuid), CONTEXTE)).status;
      if (dernier === 429) break;
    }
    expect(dernier).toBe(429);
  });

  it('ne compte qu’une fois les reprises d’un même envoi', async () => {
    avecSession();
    vi.mocked(opsPostFichier).mockResolvedValue({
      status: 'attached', expense: { ...DEPENSE, has_receipt: true, can_attach_receipt: false },
    });
    // Quarante-cinq reprises du même envoi : au-delà du budget si chacune
    // comptait, sans effet puisqu'elles portent le même identifiant.
    let dernier = 200;
    for (let index = 0; index < 45; index += 1) {
      dernier = (await postJustificatif(requeteJustificatif(photo()), CONTEXTE)).status;
    }
    expect(dernier).toBe(200);
  });
});
