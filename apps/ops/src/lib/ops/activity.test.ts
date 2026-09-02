import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', () => ({ opsGetQuery: vi.fn() }));

const { opsGetQuery } = await import('@/lib/auth/odoo-ops');
const {
  activityEvent, activityItem, activityPage, fetchActivity, fetchIntakeActivity,
} = await import('@/lib/ops/activity');

const TZ = 'Africa/Dakar';

const EVENT = {
  event: 'wave_payment_recorded' as const,
  category: 'payment' as const,
  label: 'Paiement Wave',
  occurred_at: '2026-08-30T07:45:00Z',
  actor: 'Gilles',
  dossier_reference: 'AIR-DSS-CDG-2026-002-A168',
  dossier_label: 'A168',
  summary: '100 000 FCFA',
  changes: [],
};

beforeEach(() => vi.mocked(opsGetQuery).mockReset());

describe('le contrat activité', () => {
  it('accepte uniquement le DTO métier public', () => {
    expect(activityPage.parse({
      events: [EVENT], next_cursor: null, timezone: TZ,
    })).toEqual({ events: [EVENT], next_cursor: null, timezone: TZ });
    for (const internal of ['id', 'shipment_id', 'operator_user_id', 'request_uuid']) {
      expect(() => activityPage.parse({
        events: [{ ...EVENT, [internal]: 42 }], next_cursor: null, timezone: TZ,
      })).toThrow();
    }
  });

  it('borne les événements et refuse un instant sans fuseau', () => {
    expect(() => activityPage.parse({
      events: [{ ...EVENT, occurred_at: '2026-08-30 07:45:00' }],
      next_cursor: null, timezone: TZ,
    })).toThrow();
    expect(() => activityPage.parse({
      events: Array.from({ length: 101 }, () => EVENT),
      next_cursor: null, timezone: TZ,
    })).toThrow();
  });

  it('refuse une page qui ne dit pas dans quel fuseau elle a été comptée', () => {
    // Sans le fuseau du serveur, l'écran formaterait avec le sien : la
    // journée affichée et la journée filtrée cesseraient de coïncider.
    expect(() => activityPage.parse({
      events: [EVENT], next_cursor: null,
    })).toThrow();
  });

  it('lit les saisies de l’utilisateur par GET borné', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({
      events: [EVENT], next_cursor: 'suite', date: '2026-08-30', scope: 'mine',
      timezone: TZ,
    });
    const result = await fetchActivity(
      { date: '2026-08-30', limit: 5, scope: 'mine' }, 'session', 'corr',
    );
    expect(result.events).toHaveLength(1);
    expect(opsGetQuery).toHaveBeenCalledWith('activity', {
      date: '2026-08-30', limit: '5', scope: 'mine',
    }, 'session', 'corr');
  });

  it('lit une timeline dossier sans POSTer un événement', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({
      events: [EVENT], next_cursor: null, timezone: TZ,
      dossier_reference: EVENT.dossier_reference, dossier_label: 'A168',
    });
    await fetchIntakeActivity(EVENT.dossier_reference, { limit: 10 }, 's', 'c');
    expect(opsGetQuery).toHaveBeenCalledWith(
      `intakes/${EVENT.dossier_reference}/activity`, { limit: '10' }, 's', 'c',
    );
  });
});

describe('les deux actions du chargement sont analysables', () => {
  /**
   * `activityPage.parse` est strict et sans repli : le jour où un opérateur
   * charge un colis, le serveur écrit `package_loaded`. Si l'énumération
   * l'ignorait, l'analyse de la page entière échouerait et le fil d'activité
   * rendrait 503 — pour tout le monde, pas seulement pour cet événement.
   *
   * La liste est lue à la source côté serveur plutôt que recopiée : une copie
   * divergerait au premier changement.
   */
  const SERVICE = readFileSync(fileURLToPath(new URL(
    '../../../../../odoo/custom-addons/dally_ops_mobile/models/'
    + 'ops_activity_service.py', import.meta.url)), 'utf8');

  it('le serveur les publie bien, dans la catégorie « loading »', () => {
    for (const action of ['package_loaded', 'package_unloaded']) {
      expect(SERVICE).toContain(`"${action}": (`);
      const ligne = SERVICE.slice(SERVICE.indexOf(`"${action}": (`));
      expect(ligne.slice(0, ligne.indexOf('\n'))).toContain('"loading"');
    }
  });

  it('le navigateur sait les analyser', () => {
    const connus = new Set<string>(activityEvent.options);
    expect(connus.has('package_loaded')).toBe(true);
    expect(connus.has('package_unloaded')).toBe(true);
    expect(new Set<string>(activityItem.shape.category.options).has('loading'))
      .toBe(true);
  });

  it('un événement de chargement traverse le contrat entier', () => {
    const page = {
      events: [{
        event: 'package_loaded', category: 'loading',
        label: 'Colis chargé au départ',
        occurred_at: '2026-09-02T09:00:00+00:00', actor: 'Gilles',
        dossier_reference: 'AIR-DSS-CDG-2026-002-A001', dossier_label: 'A001',
        summary: '', changes: [],
      }],
      next_cursor: null, timezone: TZ,
    };
    expect(() => activityPage.parse(page)).not.toThrow();
  });
});
