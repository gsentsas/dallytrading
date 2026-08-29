import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn(), opsPost: vi.fn(), opsPostFichier: vi.fn() };
});

const { opsGet, opsPost, opsPostFichier } = await import('@/lib/auth/odoo-ops');
const {
  attachReceipt,
  demandeDepense,
  fetchExpenseConsolidations,
  fetchExpenses,
  recordExpense,
} = await import('@/lib/ops/expenses');

const DEPART = {
  reference: 'AIR-DSS-CDG-2026-002',
  transport_mode: 'air',
  state: 'departed',
  origin: { city: 'Dakar', location: 'DSS' },
  destination: { city: 'Paris', location: 'CDG' },
};

const DEPENSE = {
  reference: '11111111-2222-4333-8444-555555555555',
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

const DEMANDE = {
  request_uuid: '11111111-2222-4333-8444-555555555555',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  expense_date: '2026-08-20',
  category: 'Manutention',
  description: 'Portage entrepôt',
  beneficiary: 'Équipe entrepôt',
  amount: 15000,
  currency_code: 'XOF',
  payment_method: 'cash' as const,
  comment: '',
};

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsPost).mockReset();
  vi.mocked(opsPostFichier).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('départs éligibles aux dépenses', () => {
  it('vise sa propre ressource, pas celle des réceptions', async () => {
    vi.mocked(opsGet).mockResolvedValue({ consolidations: [DEPART] });
    await fetchExpenseConsolidations('sX', 'corr');
    expect(opsGet).toHaveBeenCalledWith('expense-consolidations', 'sX', 'corr');
  });

  it.each(['collecting', 'collection_closed', 'ready', 'departed', 'arrived'])(
    'accepte un départ à l’état %s', async (etat) => {
      vi.mocked(opsGet).mockResolvedValue({
        consolidations: [{ ...DEPART, state: etat }],
      });
      await expect(fetchExpenseConsolidations('sX', 'corr')).resolves.toHaveLength(1);
    });

  it.each(['draft', 'cancelled', 'closed'])(
    'refuse un départ à l’état %s', async (etat) => {
      // Le serveur ne doit pas en servir ; s'il le faisait, l'écran ne
      // l'afficherait pas non plus.
      vi.mocked(opsGet).mockResolvedValue({
        consolidations: [{ ...DEPART, state: etat }],
      });
      await expect(fetchExpenseConsolidations('sX', 'corr')).rejects.toThrow();
    });

  it('refuse un départ qui porterait son identifiant Odoo', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      consolidations: [{ ...DEPART, id: 42 }],
    });
    await expect(fetchExpenseConsolidations('sX', 'corr')).rejects.toThrow();
  });
});

describe('ce que le navigateur a le droit de demander', () => {
  it('accepte une demande complète', () => {
    expect(demandeDepense.safeParse(DEMANDE).success).toBe(true);
  });

  it.each([
    'state', 'source', 'external_expense_key', 'company_id', 'consolidation_id',
    'actor_name', 'paid_by', 'total_eur_snapshot', 'total_xof_snapshot',
    'receipt_attachment_id',
  ])('refuse la clé %s, décidée par le serveur', (cle) => {
    expect(demandeDepense.safeParse({ ...DEMANDE, [cle]: 'x' }).success).toBe(false);
  });

  it.each([0, -1, -15000])('refuse le montant %s', (valeur) => {
    expect(demandeDepense.safeParse({ ...DEMANDE, amount: valeur }).success).toBe(false);
  });

  it.each(['cash', 'wave', 'bank', 'other'])('accepte le mode %s', (mode) => {
    expect(demandeDepense.safeParse({ ...DEMANDE, payment_method: mode }).success)
      .toBe(true);
  });

  it.each(['orange_money', 'wvae', 'CASH', ''])('refuse le mode %s', (mode) => {
    expect(demandeDepense.safeParse({ ...DEMANDE, payment_method: mode }).success)
      .toBe(false);
  });

  it('refuse une date mal formée', () => {
    expect(demandeDepense.safeParse({ ...DEMANDE, expense_date: '20/08/2026' }).success)
      .toBe(false);
  });

  it('exige un identifiant de demande', () => {
    const partiel: Record<string, unknown> = { ...DEMANDE };
    delete partiel.request_uuid;
    expect(demandeDepense.safeParse(partiel).success).toBe(false);
  });
});

describe('enregistrement', () => {
  it('vise la ressource des dépenses', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', expense: DEPENSE });
    await recordExpense(DEMANDE, 'sX', 'corr');
    expect(opsPost).toHaveBeenCalledWith('expenses', DEMANDE, 'sX', 'corr');
  });

  it('rend la dépense et son payeur', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', expense: DEPENSE });
    const resultat = await recordExpense(DEMANDE, 'sX', 'corr');
    expect(resultat.expense.paid_by).toBe('Gilles');
    expect(resultat.expense.has_receipt).toBe(false);
  });

  it('accepte un rejeu', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'replayed', expense: DEPENSE });
    await expect(recordExpense(DEMANDE, 'sX', 'corr')).resolves.toHaveProperty(
      'status', 'replayed');
  });

  it.each(['expense_id', 'consolidation_id', 'company_id', 'currency_id',
           'attachment_id', 'external_expense_key'])(
    'refuse une réponse portant %s', async (cle) => {
      vi.mocked(opsPost).mockResolvedValue({
        status: 'created', expense: { ...DEPENSE, [cle]: 42 },
      });
      await expect(recordExpense(DEMANDE, 'sX', 'corr')).rejects.toThrow();
    });
});

describe('lecture des dépenses d’un départ', () => {
  it('vise la ressource du départ', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      consolidation_reference: 'AIR-1', expenses: [], summary: [],
    });
    await fetchExpenses('AIR-1', 'sX', 'corr');
    expect(opsGet).toHaveBeenCalledWith('consolidations/AIR-1/expenses', 'sX', 'corr');
  });

  it('rend un total par devise, jamais un total unique', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      consolidation_reference: 'AIR-1',
      expenses: [DEPENSE],
      summary: [
        { currency_code: 'EUR', amount: 42.5 },
        { currency_code: 'XOF', amount: 20000 },
      ],
    });
    const liste = await fetchExpenses('AIR-1', 'sX', 'corr');
    expect(liste.summary).toHaveLength(2);
  });

  it('refuse un résumé qui porterait un montant converti', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      consolidation_reference: 'AIR-1',
      expenses: [],
      summary: [{ currency_code: 'XOF', amount: 20000, amount_eur: 30.5 }],
    });
    await expect(fetchExpenses('AIR-1', 'sX', 'corr')).rejects.toThrow();
  });
});

describe('justificatif', () => {
  it('vise la ressource du justificatif et porte l’identifiant d’envoi', async () => {
    vi.mocked(opsPostFichier).mockResolvedValue({
      status: 'attached', expense: { ...DEPENSE, has_receipt: true, can_attach_receipt: false },
    });
    const contenu = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: 'image/jpeg' });
    await attachReceipt(
      'ref-1', '11111111-2222-4333-8444-555555555555',
      { nom: 'ticket.jpg', type: 'image/jpeg', contenu }, 'sX', 'corr');
    expect(opsPostFichier).toHaveBeenCalledWith(
      'expenses/ref-1/receipt',
      { nom: 'ticket.jpg', type: 'image/jpeg', contenu },
      { request_uuid: '11111111-2222-4333-8444-555555555555' },
      'sX', 'corr',
    );
  });

  it('rend la dépense avec son justificatif joint', async () => {
    vi.mocked(opsPostFichier).mockResolvedValue({
      status: 'attached', expense: { ...DEPENSE, has_receipt: true, can_attach_receipt: false },
    });
    const resultat = await attachReceipt(
      'ref-1', '11111111-2222-4333-8444-555555555555',
      { nom: 't.jpg', type: 'image/jpeg', contenu: new Blob(['x']) }, 'sX', 'corr');
    expect(resultat.expense.has_receipt).toBe(true);
  });

  it('dit qu’une dépense venue du tableur ne se complète pas d’ici', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      consolidation_reference: 'AIR-1',
      expenses: [{ ...DEPENSE, can_attach_receipt: false }],
      summary: [],
    });
    const liste = await fetchExpenses('AIR-1', 'sX', 'corr');
    expect(liste.expenses[0]?.can_attach_receipt).toBe(false);
  });

  it('refuse une réponse qui exposerait le chemin du fichier', async () => {
    vi.mocked(opsPostFichier).mockResolvedValue({
      status: 'attached',
      expense: { ...DEPENSE, receipt_url: '/web/content/9182' },
    });
    await expect(attachReceipt(
      'ref-1', '11111111-2222-4333-8444-555555555555',
      { nom: 't.jpg', type: 'image/jpeg', contenu: new Blob(['x']) }, 'sX', 'corr',
    )).rejects.toThrow();
  });
});
