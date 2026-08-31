import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsPost: vi.fn() };
});

const { opsPost } = await import('@/lib/auth/odoo-ops');
const { advanceIntakeState, demandeTransition } = await import('@/lib/ops/intake-state');

const UUID = '11111111-1111-4111-8111-111111111111';
const REFERENCE = 'AIR-DSS-CDG-2026-902-A001';
const REPONSE = {
  status: 'updated', reference: REFERENCE, state: 'preparing',
  allowed_transitions: ['ready'],
};
const DEMANDE = {
  request_uuid: UUID, expected_state: 'goods_received', target_state: 'preparing',
} as const;

beforeEach(() => { vi.mocked(opsPost).mockReset(); });
afterEach(() => { vi.restoreAllMocks(); });

describe('contrat de l’avancement d’état', () => {
  it('poste sur la ressource du dossier et rien d’autre', async () => {
    vi.mocked(opsPost).mockResolvedValue(REPONSE);
    await advanceIntakeState(REFERENCE, DEMANDE, 'session', 'correlation');
    expect(opsPost).toHaveBeenCalledWith(
      `intakes/${REFERENCE}/state`, DEMANDE, 'session', 'correlation');
  });

  it('accepte un rejeu comme une issue normale', async () => {
    vi.mocked(opsPost).mockResolvedValue({ ...REPONSE, status: 'replayed' });
    const page = await advanceIntakeState(REFERENCE, DEMANDE, 'session', 'correlation');
    expect(page.status).toBe('replayed');
  });

  it('n’accepte que les deux cibles offertes au terrain', () => {
    for (const cible of ['preparing', 'ready']) {
      expect(demandeTransition.safeParse({ ...DEMANDE, target_state: cible }).success)
        .toBe(true);
    }
    for (const cible of ['departed', 'cancelled', 'delivered', 'draft', '']) {
      expect(demandeTransition.safeParse({ ...DEMANDE, target_state: cible }).success,
             cible).toBe(false);
    }
  });

  it('refuse un champ supplémentaire dans la demande', () => {
    expect(demandeTransition.safeParse({ ...DEMANDE, force: true }).success).toBe(false);
  });

  it('exige un identifiant de geste bien formé', () => {
    for (const identifiant of ['', 'pas-un-uuid', undefined]) {
      expect(demandeTransition.safeParse({ ...DEMANDE, request_uuid: identifiant })
        .success, String(identifiant)).toBe(false);
    }
  });

  it('refuse une réponse portant un identifiant interne', async () => {
    vi.mocked(opsPost).mockResolvedValue({ ...REPONSE, shipment_id: 688 });
    await expect(advanceIntakeState(REFERENCE, DEMANDE, 'session', 'correlation'))
      .rejects.toThrow();
  });

  it('refuse une transition autorisée que l’écran ne saurait pas nommer', async () => {
    vi.mocked(opsPost).mockResolvedValue(
      { ...REPONSE, allowed_transitions: ['departed'] });
    await expect(advanceIntakeState(REFERENCE, DEMANDE, 'session', 'correlation'))
      .rejects.toThrow();
  });

  it('refuse une référence qui n’en est pas une', async () => {
    vi.mocked(opsPost).mockResolvedValue(REPONSE);
    await expect(advanceIntakeState('../freight', DEMANDE, 'session', 'correlation'))
      .rejects.toThrow('Référence de dossier invalide.');
    expect(opsPost).not.toHaveBeenCalled();
  });
});
