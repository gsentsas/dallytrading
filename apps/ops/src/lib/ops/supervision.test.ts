/**
 * Le contrat de supervision, dans les deux sens.
 *
 * Les schémas sont stricts : une réponse qui porterait une clé inattendue —
 * un identifiant Odoo, le `last_error` d'un transport — n'atteint pas le
 * navigateur. La vérification est structurelle, pas textuelle : chercher un
 * nombre dans du texte retrouverait un identifiant au hasard dans une
 * référence.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn() };
});

const { opsGet } = await import('@/lib/auth/odoo-ops');
const { fetchAnomalies, fetchEtatProjection } =
  await import('@/lib/ops/supervision');

const ANOMALIE = {
  type: 'UNBILLED_PACKAGE',
  reference: 'AIR-DSS-CDG-2099-001-A901',
  title: 'Article non facturé',
  operator_message: '1 article n’est couvert par aucune facture.',
  severity: 'medium',
  action: 'open_intake',
  intake_reference: 'AIR-DSS-CDG-2099-001-A901',
};

const LISTE = { anomalies: [ANOMALIE], total: 1, truncated: false };

const PROJECTION = {
  counts: { pending: 2, retry: 1, failed: 0, synced: 40 },
  operator_message: 'Des envois sont en attente de traitement.',
  last_synced_at: '2026-09-01T10:00:00',
};

beforeEach(() => { vi.mocked(opsGet).mockReset(); });
afterEach(() => { vi.restoreAllMocks(); });

describe('les anomalies', () => {
  it('vise la ressource de supervision', async () => {
    vi.mocked(opsGet).mockResolvedValue(LISTE);
    await fetchAnomalies('session', 'cid');
    expect(vi.mocked(opsGet)).toHaveBeenCalledWith('anomalies', 'session', 'cid');
  });

  it('accepte une liste conforme', async () => {
    vi.mocked(opsGet).mockResolvedValue(LISTE);
    const liste = await fetchAnomalies('session', 'cid');
    expect(liste.anomalies[0]?.type).toBe('UNBILLED_PACKAGE');
  });

  it('refuse un identifiant Odoo glissé dans une anomalie', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      ...LISTE, anomalies: [{ ...ANOMALIE, shipment_id: 42 }],
    });
    await expect(fetchAnomalies('session', 'cid')).rejects.toThrow();
  });

  it('refuse un message de transport glissé à côté du message opérateur', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      ...LISTE, anomalies: [{ ...ANOMALIE, last_error: 'ECONNRESET chez 10.0.0.4' }],
    });
    await expect(fetchAnomalies('session', 'cid')).rejects.toThrow();
  });

  it('refuse un type d’anomalie hors vocabulaire', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      ...LISTE, anomalies: [{ ...ANOMALIE, type: 'QUELQUE_CHOSE' }],
    });
    await expect(fetchAnomalies('session', 'cid')).rejects.toThrow();
  });

  it('refuse une action que l’écran ne sait pas exécuter', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      ...LISTE, anomalies: [{ ...ANOMALIE, action: 'resync_sheet' }],
    });
    await expect(fetchAnomalies('session', 'cid')).rejects.toThrow();
  });

  it('refuse `open_intake` sans dossier à ouvrir', async () => {
    // L'écran annoncerait une action puis n'afficherait aucun lien.
    vi.mocked(opsGet).mockResolvedValue({
      ...LISTE, anomalies: [{ ...ANOMALIE, intake_reference: null }],
    });
    await expect(fetchAnomalies('session', 'cid')).rejects.toThrow();
  });

  it('refuse un dossier annoncé sans action pour l’ouvrir', async () => {
    // L'écran tairait une fiche qu'il pourrait pourtant ouvrir.
    vi.mocked(opsGet).mockResolvedValue({
      ...LISTE, anomalies: [{ ...ANOMALIE, action: null }],
    });
    await expect(fetchAnomalies('session', 'cid')).rejects.toThrow();
  });

  it('accepte une anomalie sans dossier à ouvrir', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      ...LISTE,
      anomalies: [{ ...ANOMALIE, action: null, intake_reference: null }],
    });
    const liste = await fetchAnomalies('session', 'cid');
    expect(liste.anomalies[0]?.action).toBeNull();
  });
});

describe('l’état de projection vers le tableur', () => {
  it('vise sa propre ressource, distincte de la file de l’appareil', async () => {
    vi.mocked(opsGet).mockResolvedValue(PROJECTION);
    await fetchEtatProjection('session', 'cid');
    expect(vi.mocked(opsGet)).toHaveBeenCalledWith('sheet-sync', 'session', 'cid');
  });

  it('accepte les quatre compteurs', async () => {
    vi.mocked(opsGet).mockResolvedValue(PROJECTION);
    const etat = await fetchEtatProjection('session', 'cid');
    expect(etat.counts.retry).toBe(1);
  });

  it('refuse le `last_error` de l’outbox', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      ...PROJECTION, last_error: 'HTTP 500 depuis projection.invalid',
    });
    await expect(fetchEtatProjection('session', 'cid')).rejects.toThrow();
  });

  it('refuse un compteur négatif — il n’en existe pas', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      ...PROJECTION, counts: { ...PROJECTION.counts, failed: -1 },
    });
    await expect(fetchEtatProjection('session', 'cid')).rejects.toThrow();
  });

  it('refuse une file mélangée : aucun compteur d’appareil ici', async () => {
    // Les deux files ne s'additionnent jamais. Un compteur venu d'IndexedDB
    // qui remonterait dans cette réponse serait une confusion, pas un extra.
    vi.mocked(opsGet).mockResolvedValue({
      ...PROJECTION,
      counts: { ...PROJECTION.counts, device_pending: 3 },
    });
    await expect(fetchEtatProjection('session', 'cid')).rejects.toThrow();
  });
});
