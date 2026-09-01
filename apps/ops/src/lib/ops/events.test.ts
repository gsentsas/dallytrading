import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Le contrat des événements, dans les deux sens.
 *
 * À l'aller : les trois seuls champs qu'un geste porte. Au retour : ce que
 * l'écran a le droit de recevoir. `.strict()` fait tomber la lecture le jour où
 * un champ technique descendrait — c'est la seule garde qui n'attend pas qu'on
 * pense à la vérifier.
 */

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn(), opsPost: vi.fn() };
});

const { opsGet, opsPost } = await import('@/lib/auth/odoo-ops');
const { createEvent, demandeEvenement, fetchEvents } = await import(
  '@/lib/ops/events');

const REFERENCE = 'AIR-DSS-CDG-2026-902-A001';
const UUID = '11111111-1111-4111-8111-111111111111';

const EVENEMENT = {
  kind: 'damage_noted',
  kind_label: 'Dommage constaté',
  description: 'Dommage constaté',
  note: 'Coin écrasé',
  status: 'preparing',
  status_label: 'Preparing',
  event_date: '2026-09-01T09:00:00Z',
  recorded_by: 'Gilles',
  source: 'ops' as const,
};

const LISTE = {
  events: [EVENEMENT],
  can_add: true,
  kinds: [
    { kind: 'anomaly' as const, label: 'Anomalie constatée', note_required: true },
    { kind: 'repacked' as const, label: 'Colis reconditionné', note_required: false },
  ],
};

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsPost).mockReset();
});

describe('le contrat de retour refuse tout identifiant technique', () => {
  it('accepte exactement les neuf champs prévus', async () => {
    vi.mocked(opsGet).mockResolvedValue(LISTE);
    const lu = await fetchEvents(REFERENCE, 'sX', 'corr');
    expect(lu.events[0]).toEqual(EVENEMENT);
    expect(lu.kinds).toHaveLength(2);
  });

  it.each([
    ['id', { ...EVENEMENT, id: 42 }],
    ['res_model', { ...EVENEMENT, res_model: 'dally.shipment.event' }],
    ['res_id', { ...EVENEMENT, res_id: 42 }],
    ['user_id', { ...EVENEMENT, user_id: 7 }],
    ['company_id', { ...EVENEMENT, company_id: 1 }],
    ['shipment_id', { ...EVENEMENT, shipment_id: 9 }],
    ['internal_note', { ...EVENEMENT, internal_note: 'x' }],
    ['visible_to_customer', { ...EVENEMENT, visible_to_customer: false }],
    ['is_automatic', { ...EVENEMENT, is_automatic: false }],
  ])('refuse une réponse enrichie de « %s »', async (_nom, evenement) => {
    vi.mocked(opsGet).mockResolvedValue({ ...LISTE, events: [evenement] });
    await expect(fetchEvents(REFERENCE, 'sX', 'corr')).rejects.toThrow();
  });

  it('refuse une source inconnue et une enveloppe enrichie', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      ...LISTE, events: [{ ...EVENEMENT, source: 'client' }] });
    await expect(fetchEvents(REFERENCE, 'sX', 'corr')).rejects.toThrow();

    vi.mocked(opsGet).mockResolvedValue({ ...LISTE, total: 1 });
    await expect(fetchEvents(REFERENCE, 'sX', 'corr')).rejects.toThrow();
  });
});

describe('le contrat d’aller n’ouvre aucune porte', () => {
  it('accepte les trois champs, et la note facultative', () => {
    expect(demandeEvenement.safeParse({
      request_uuid: UUID, kind: 'repacked' }).success).toBe(true);
    expect(demandeEvenement.safeParse({
      request_uuid: UUID, kind: 'anomaly', note: 'Carton enfoncé' }).success)
      .toBe(true);
  });

  it.each([
    'status', 'description', 'event_date', 'visible_to_customer',
    'is_automatic', 'user_id', 'company_id', 'shipment_id', 'location',
    'publish', 'notify',
  ])('refuse « %s », plutôt que de l’ignorer', (champ) => {
    const resultat = demandeEvenement.safeParse({
      request_uuid: UUID, kind: 'anomaly', note: 'Motif', [champ]: true });
    expect(resultat.success).toBe(false);
  });

  it('refuse une nature hors des sept, et une note trop longue', () => {
    expect(demandeEvenement.safeParse({
      request_uuid: UUID, kind: 'selfie' }).success).toBe(false);
    expect(demandeEvenement.safeParse({
      request_uuid: UUID, kind: 'other', note: 'x'.repeat(1001) }).success)
      .toBe(false);
  });

  it('exige un identifiant de geste bien formé', () => {
    for (const mauvais of ['', 'pas-un-uuid', undefined]) {
      expect(demandeEvenement.safeParse({
        request_uuid: mauvais, kind: 'repacked' }).success, String(mauvais))
        .toBe(false);
    }
  });
});

describe('les appels', () => {
  it('transmet la demande telle quelle', async () => {
    vi.mocked(opsPost).mockResolvedValue({ event: EVENEMENT, replayed: false });
    await createEvent(REFERENCE,
      { request_uuid: UUID, kind: 'anomaly', note: 'Motif' }, 'sX', 'corr');
    expect(opsPost).toHaveBeenCalledWith(
      `intakes/${REFERENCE}/events`,
      { request_uuid: UUID, kind: 'anomaly', note: 'Motif' }, 'sX', 'corr');
  });

  it('relaie le drapeau de rejeu', async () => {
    vi.mocked(opsPost).mockResolvedValue({ event: EVENEMENT, replayed: true });
    const resultat = await createEvent(REFERENCE,
      { request_uuid: UUID, kind: 'anomaly', note: 'Motif' }, 'sX', 'corr');
    expect(resultat.replayed).toBe(true);
  });

  it('refuse une référence qui composerait un chemin', async () => {
    for (const reference of ['../web', 'A 1', 'A/B', '']) {
      await expect(fetchEvents(reference, 'sX', 'corr')).rejects.toThrow();
    }
    expect(opsGet).not.toHaveBeenCalled();
  });
});

describe('la lecture accepte ce qu’Odoo autorise à écrire', () => {
  it('ne borne ni la description ni la note d’un événement du back-office',
    async () => {
      // `description` est un Char et `internal_note` un Text, ni l'un ni
      // l'autre dimensionné : un événement saisi dans Odoo peut dépasser
      // n'importe quelle borne que l'application se donnerait ici.
      const long = {
        ...EVENEMENT, kind: '', kind_label: '', source: 'backoffice' as const,
        description: 'D'.repeat(1200), note: 'N'.repeat(5000),
      };
      vi.mocked(opsGet).mockResolvedValue({ ...LISTE, events: [long] });
      const lu = await fetchEvents(REFERENCE, 'session', 'correlation');
      expect(lu.events[0]?.description).toHaveLength(1200);
      expect(lu.events[0]?.note).toHaveLength(5000);
    });

  it('mais le contrat d’écriture garde exactement sa borne', () => {
    const gabarit = { request_uuid: UUID, kind: 'anomaly' as const };
    expect(demandeEvenement.safeParse(
      { ...gabarit, note: 'x'.repeat(1000) }).success).toBe(true);
    expect(demandeEvenement.safeParse(
      { ...gabarit, note: 'x'.repeat(1001) }).success).toBe(false);
  });
});
