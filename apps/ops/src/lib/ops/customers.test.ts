import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsPost: vi.fn() };
});

const { opsPost } = await import('@/lib/auth/odoo-ops');
const { critereRecherche, searchCustomer } = await import('@/lib/ops/customers');

const CLIENT = {
  reference: 'b9c8c46f-1f2e-4a3b-9c8d-7e6f5a4b3c2d',
  name: 'Aissatou Kandji',
  phone: '+33 6 12 34 56 78',
  email: 'client@example.com',
  address: '207 rue Saint-Charles, 75015 Paris, France',
  customer_type: 'individual',
};

beforeEach(() => {
  vi.mocked(opsPost).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ce que le navigateur a le droit de demander', () => {
  it('accepte un numéro seul', () => {
    expect(critereRecherche.safeParse({ phone: '+221 77 123 45 67' }).success).toBe(true);
  });

  it('accepte une adresse seule', () => {
    expect(critereRecherche.safeParse({ email: 'client@example.com' }).success).toBe(true);
  });

  it('refuse les deux à la fois', () => {
    expect(critereRecherche.safeParse({
      phone: '771234567', email: 'client@example.com',
    }).success).toBe(false);
  });

  it('refuse une demande vide', () => {
    expect(critereRecherche.safeParse({}).success).toBe(false);
  });

  it('refuse une recherche par nom', () => {
    // Il n'existe pas de critère « nom » : les homonymes sont courants, et une
    // recherche par nom est un moyen de feuilleter le fichier clients.
    expect(critereRecherche.safeParse({ name: 'Mamadou' }).success).toBe(false);
  });

  it('refuse une clé inconnue glissée à côté d’un critère valide', () => {
    // `strict()` : ignorer la clé laisserait croire qu'elle a été prise en
    // compte.
    expect(critereRecherche.safeParse({
      phone: '771234567', company_id: 1,
    }).success).toBe(false);
  });

  it('refuse un critère qui n’est pas une chaîne', () => {
    expect(critereRecherche.safeParse({ phone: 771234567 }).success).toBe(false);
  });
});

describe('résultat de la recherche', () => {
  it('rend le client trouvé', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'match', customer: CLIENT });
    const resultat = await searchCustomer({ phone: '771234567' }, 's', 'corr');
    expect(resultat).toEqual({ status: 'match', customer: CLIENT });
  });

  it('vise la ressource « customers/search » en POST', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'not_found', customer: null });
    await searchCustomer({ phone: '771234567' }, 'session-abc', 'corr');
    expect(opsPost).toHaveBeenCalledWith(
      'customers/search', { phone: '771234567' }, 'session-abc', 'corr');
  });

  it('accepte l’absence de correspondance', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'not_found', customer: null });
    await expect(searchCustomer({ phone: '7' }, 's', 'corr')).resolves.toEqual({
      status: 'not_found', customer: null,
    });
  });

  it('accepte l’ambiguïté, qui ne porte aucun client', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'ambiguous', customer: null });
    await expect(searchCustomer({ phone: '7' }, 's', 'corr')).resolves.toEqual({
      status: 'ambiguous', customer: null,
    });
  });

  it('refuse une ambiguïté qui porterait malgré tout un client', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'ambiguous', customer: CLIENT });
    // Le type l'interdit et la validation le fait respecter : deux fiches
    // veulent dire qu'on ignore laquelle est devant le comptoir.
    await expect(searchCustomer({ phone: '7' }, 's', 'corr')).rejects.toThrow();
  });

  it('refuse un statut inconnu', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'maybe', customer: null });
    await expect(searchCustomer({ phone: '7' }, 's', 'corr')).rejects.toThrow();
  });
});

describe('le contrat se referme ici', () => {
  it('refuse un DTO qui porterait un identifiant Odoo', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      status: 'match', customer: { ...CLIENT, partner_id: 3728 },
    });
    await expect(searchCustomer({ phone: '7' }, 's', 'corr')).rejects.toThrow();
  });

  it('refuse un DTO qui porterait un solde ou une note', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      status: 'match', customer: { ...CLIENT, credit: 1200, comment: 'Note interne' },
    });
    await expect(searchCustomer({ phone: '7' }, 's', 'corr')).rejects.toThrow();
  });

  it('exige une référence opaque en forme d’UUID', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      status: 'match', customer: { ...CLIENT, reference: '3728' },
    });
    await expect(searchCustomer({ phone: '7' }, 's', 'corr')).rejects.toThrow();
  });

  it('refuse un type de client inattendu', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      status: 'match', customer: { ...CLIENT, customer_type: 'prospect' },
    });
    await expect(searchCustomer({ phone: '7' }, 's', 'corr')).rejects.toThrow();
  });
});
