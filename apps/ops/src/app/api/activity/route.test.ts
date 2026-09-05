import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ActivityPage } from '@/lib/ops/activity';

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/logger', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/logger')>();
  return { ...original, logger: { ...original.logger, error: vi.fn() } };
});
vi.mock('@/lib/ops/activity', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/ops/activity')>();
  return { ...original, fetchActivity: vi.fn(), fetchIntakeActivity: vi.fn() };
});

const { readOpsSession } = await import('@/lib/auth/auth');
const { logger } = await import('@/lib/logger');
const { OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const { activityPage } = await import('@/lib/ops/activity');
const { fetchActivity, fetchIntakeActivity } = await import('@/lib/ops/activity');
const { GET: activityGet } = await import('@/app/api/activity/route');
const { GET: intakeActivityGet } = await import('@/app/api/intakes/[reference]/activity/route');

const PAGE: ActivityPage = {
  events: [], next_cursor: null, date: '2026-08-30', scope: 'mine',
  timezone: 'Africa/Dakar',
};

beforeEach(() => {
  vi.mocked(logger.error).mockReset();
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

/*
 * Ce qu'un 503 doit dire — et ce qu'il ne doit jamais dire.
 *
 * Le journal servait uniquement à compter les pannes : il portait le seul
 * `correlationId`, et une enquête ne pouvait pas distinguer une passerelle
 * tombée d'une réponse Odoo hors contrat. Ces tests exigent la forme de
 * l'erreur, et interdisent son contenu.
 */
const SESSION_SENTINELLE = 'SECRET_SESSION_SENTINEL';
const CLE_SENSIBLE = 'SECRET_CUSTOMER_SENTINEL';

/** Le contexte réellement passé au journal, sérialisé comme il le sera. */
function contexteJournalise(): string {
  expect(logger.error).toHaveBeenCalledTimes(1);
  return JSON.stringify(vi.mocked(logger.error).mock.calls[0]![1]);
}

function contexte(): Record<string, unknown> {
  return vi.mocked(logger.error).mock.calls[0]![1] as Record<string, unknown>;
}

describe('un 503 activité se diagnostique sans se trahir', () => {
  beforeEach(() => {
    vi.mocked(readOpsSession).mockResolvedValue(
      { odooSessionId: SESSION_SENTINELLE, issuedAt: 1 });
  });

  it('nomme la panne de passerelle sans citer la session', async () => {
    vi.mocked(fetchActivity).mockRejectedValue(
      new OpsGatewayError('unavailable', 'Odoo injoignable'));

    const response = await activityGet(new Request('https://ops.test/api/activity'));

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual(
      { success: false, error: 'Service momentanément indisponible.' });
    expect(contexte()).toMatchObject({
      route: 'activity',
      errorClass: 'OPS_GATEWAY',
      errorType: 'OpsGatewayError',
      gatewayCode: 'unavailable',
    });
    expect(contexte().correlationId).toEqual(expect.any(String));
    expect(contexte().durationMs).toEqual(expect.any(Number));
    expect(contexteJournalise()).not.toContain(SESSION_SENTINELLE);
  });

  it('classe une réponse hors contrat sans recopier ce qu\'elle contenait', async () => {
    // La vraie erreur : le schéma est strict, donc une clé inattendue d'Odoo
    // atterrit *nommée* dans la ZodError. Si le journal recopiait l'erreur,
    // ce nom partirait avec.
    let zod: unknown;
    try {
      activityPage.parse({
        events: [], next_cursor: null, timezone: 'Africa/Dakar',
        [CLE_SENSIBLE]: 'valeur',
      });
    } catch (e) { zod = e; }
    // Contrôle de la valeur du test : la sentinelle est bien dans l'erreur brute.
    expect(JSON.stringify((zod as { issues: unknown[] }).issues)).toContain(CLE_SENSIBLE);
    vi.mocked(fetchActivity).mockRejectedValue(zod);

    const response = await activityGet(new Request('https://ops.test/api/activity'));

    expect(response.status).toBe(503);
    expect(contexte()).toMatchObject({
      errorClass: 'VALIDATION', errorType: 'ZodError', issueCount: 1,
    });
    expect(contexteJournalise()).not.toContain(CLE_SENSIBLE);
    expect(contexteJournalise()).not.toContain(SESSION_SENTINELLE);
  });

  it('ne recopie pas le message d\'une erreur générique', async () => {
    vi.mocked(fetchActivity).mockRejectedValue(
      new Error(`échec brut portant ${CLE_SENSIBLE}`));

    const response = await activityGet(new Request('https://ops.test/api/activity'));

    expect(response.status).toBe(503);
    expect(contexte()).toMatchObject({ errorClass: 'ERROR', errorType: 'Error' });
    expect(contexteJournalise()).not.toContain(CLE_SENSIBLE);
  });

  it('décrit une valeur lancée qui n\'est pas une Error', async () => {
    vi.mocked(fetchActivity).mockRejectedValue(CLE_SENSIBLE);

    const response = await activityGet(new Request('https://ops.test/api/activity'));

    expect(response.status).toBe(503);
    expect(contexte()).toMatchObject(
      { errorClass: 'UNKNOWN', errorType: 'UnknownError' });
    expect(contexteJournalise()).not.toContain(CLE_SENSIBLE);
  });

  it('journalise aussi l\'activité d\'un dossier, sans nommer le dossier', async () => {
    const reference = 'AIR-DSS-CDG-2026-002-A168';
    vi.mocked(fetchIntakeActivity).mockRejectedValue(
      new OpsGatewayError('unavailable'));

    const response = await intakeActivityGet(
      new Request(`https://ops.test/api/intakes/${reference}/activity`),
      { params: Promise.resolve({ reference }) });

    expect(response.status).toBe(503);
    expect(contexte()).toMatchObject({
      route: 'intake_activity',
      errorClass: 'OPS_GATEWAY',
      gatewayCode: 'unavailable',
    });
    // Une référence de dossier désigne un client : elle reste hors du journal.
    expect(contexteJournalise()).not.toContain(reference);
    expect(contexteJournalise()).not.toContain('A168');
    expect(contexteJournalise()).not.toContain(SESSION_SENTINELLE);
  });

  it('n\'écrit que les champs autorisés', async () => {
    vi.mocked(fetchActivity).mockRejectedValue(new OpsGatewayError('unavailable'));
    await activityGet(new Request('https://ops.test/api/activity'));
    // Liste blanche : tout champ nouveau devra être justifié ici.
    expect(Object.keys(contexte()).sort()).toEqual([
      'correlationId', 'durationMs', 'errorClass', 'errorType', 'gatewayCode', 'route',
    ]);
  });
});
