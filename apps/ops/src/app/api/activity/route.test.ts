import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ActivityPage } from '@/lib/ops/activity';

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/ops/activity', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/ops/activity')>();
  return { ...original, fetchActivity: vi.fn(), fetchIntakeActivity: vi.fn() };
});

const { readOpsSession } = await import('@/lib/auth/auth');
const { fetchActivity, fetchIntakeActivity } = await import('@/lib/ops/activity');
const { GET: activityGet } = await import('@/app/api/activity/route');
const { GET: intakeActivityGet } = await import('@/app/api/intakes/[reference]/activity/route');

const PAGE: ActivityPage = {
  events: [], next_cursor: null, date: '2026-08-30', scope: 'mine',
  timezone: 'Africa/Dakar',
};

beforeEach(() => {
  vi.mocked(readOpsSession).mockReset();
  vi.mocked(fetchActivity).mockReset();
  vi.mocked(fetchIntakeActivity).mockReset();
  vi.mocked(readOpsSession).mockResolvedValue({ odooSessionId: 'session', issuedAt: 1 });
  vi.mocked(fetchActivity).mockResolvedValue(PAGE);
  vi.mocked(fetchIntakeActivity).mockResolvedValue({
    events: [], next_cursor: null, timezone: 'Africa/Dakar',
  });
});

describe('BFF activité', () => {
  it('relaie une lecture bornée et ne la met jamais en cache', async () => {
    const response = await activityGet(new Request(
      'https://ops.test/api/activity?date=2026-08-30&limit=5&scope=mine',
    ));
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(fetchActivity).toHaveBeenCalledWith({
      date: '2026-08-30', limit: 5, scope: 'mine',
    }, 'session', expect.any(String));
  });

  it('refuse paramètres inconnus, pages illimitées et absence de session', async () => {
    expect((await activityGet(new Request(
      'https://ops.test/api/activity?sudo=1',
    ))).status).toBe(400);
    expect((await activityGet(new Request(
      'https://ops.test/api/activity?limit=5000',
    ))).status).toBe(400);
    vi.mocked(readOpsSession).mockResolvedValue(null);
    expect((await activityGet(new Request(
      'https://ops.test/api/activity',
    ))).status).toBe(401);
  });

  it('n’expose aucun verbe d’écriture : le journal ne s’écrit pas d’ici', async () => {
    // Les événements naissent des services métier d'Odoo. Un `POST` exporté
    // ici — même bien intentionné — donnerait au navigateur le moyen de
    // fabriquer une ligne d'historique.
    const activity = await import('@/app/api/activity/route');
    const intake = await import('@/app/api/intakes/[reference]/activity/route');
    for (const route of [activity, intake]) {
      expect(Object.keys(route).filter((cle) => cle !== 'dynamic'))
        .toEqual(['GET']);
    }
  });

  it('relaie la timeline du vrai dossier par GET uniquement', async () => {
    const response = await intakeActivityGet(
      new Request('https://ops.test/api/intakes/AIR-TEST-A001/activity?limit=10'),
      { params: Promise.resolve({ reference: 'AIR-TEST-A001' }) },
    );
    expect(response.status).toBe(200);
    expect(fetchIntakeActivity).toHaveBeenCalledWith(
      'AIR-TEST-A001', { limit: 10 }, 'session', expect.any(String),
    );
  });
});
