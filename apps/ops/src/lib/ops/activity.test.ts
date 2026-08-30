import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', () => ({ opsGetQuery: vi.fn() }));

const { opsGetQuery } = await import('@/lib/auth/odoo-ops');
const {
  activityPage, fetchActivity, fetchIntakeActivity,
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
