import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { EtatDossier } from '@/lib/ops/intake-state';

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/http/origine', () => ({ origineAcceptable: () => true }));
vi.mock('@/lib/ops/intake-state', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/ops/intake-state')>();
  return { ...original, advanceIntakeState: vi.fn() };
});

const { readOpsSession } = await import('@/lib/auth/auth');
const { advanceIntakeState } = await import('@/lib/ops/intake-state');
const { OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const { resetRateLimits } = await import('@/lib/rate-limit');
const { POST } = await import('@/app/api/intakes/[reference]/state/route');

const UUID = '11111111-1111-4111-8111-111111111111';
const REFERENCE = 'AIR-DSS-CDG-2026-902-A001';
const OK: EtatDossier = {
  status: 'updated', reference: REFERENCE, state: 'preparing',
  allowed_transitions: ['ready'],
};

/** Un geste neuf : identifiant distinct, donc unité de débit distincte. */
function geste(): Record<string, unknown> {
  return {
    request_uuid: crypto.randomUUID(),
    expected_state: 'goods_received',
    target_state: 'preparing',
  };
}

function appel(corps: unknown): Promise<Response> {
  return POST(
    new Request(`https://ops.test/api/intakes/${REFERENCE}/state`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corps),
    }),
    { params: Promise.resolve({ reference: REFERENCE }) },
  ) as unknown as Promise<Response>;
}

beforeEach(() => {
  resetRateLimits();
  vi.mocked(readOpsSession).mockReset();
  vi.mocked(advanceIntakeState).mockReset();
  vi.mocked(readOpsSession).mockResolvedValue({ odooSessionId: 'session', issuedAt: 1 });
  vi.mocked(advanceIntakeState).mockResolvedValue(OK);
});

describe('BFF avancement d’état', () => {
  it('relaie une demande bien formée sans jamais la mettre en cache', async () => {
    const reponse = await appel({
      request_uuid: UUID, expected_state: 'goods_received', target_state: 'preparing',
    });
    expect(reponse.status).toBe(200);
    expect(reponse.headers.get('cache-control')).toContain('no-store');
    expect(advanceIntakeState).toHaveBeenCalledWith(
      REFERENCE,
      { request_uuid: UUID, expected_state: 'goods_received', target_state: 'preparing' },
      'session', expect.any(String));
  });

  it('refuse l’absence de session avant d’interroger Odoo', async () => {
    vi.mocked(readOpsSession).mockResolvedValue(null);
    const reponse = await appel({
      request_uuid: UUID, expected_state: 'goods_received', target_state: 'preparing',
    });
    expect(reponse.status).toBe(401);
    expect(advanceIntakeState).not.toHaveBeenCalled();
  });

  it('F15 · refuse un champ supplémentaire, une cible interdite, un UUID invalide',
    async () => {
      for (const corps of [
        // Un champ de plus : le contrat d'écriture ne s'élargit pas par
        // inadvertance.
        { request_uuid: UUID, expected_state: 'goods_received',
          target_state: 'preparing', force: true },
        // Les cibles que Dally Ops n'expose jamais.
        { request_uuid: UUID, expected_state: 'ready', target_state: 'departed' },
        { request_uuid: UUID, expected_state: 'preparing', target_state: 'cancelled' },
        { request_uuid: UUID, expected_state: 'arrived', target_state: 'delivered' },
        // Identifiant de geste absent ou mal formé.
        { expected_state: 'goods_received', target_state: 'preparing' },
        { request_uuid: 'pas-un-uuid', expected_state: 'goods_received',
          target_state: 'preparing' },
        // État attendu manquant.
        { request_uuid: UUID, target_state: 'preparing' },
      ]) {
        expect((await appel(corps)).status, JSON.stringify(corps)).toBe(400);
      }
      expect(advanceIntakeState).not.toHaveBeenCalled();
    });

  it('distingue un dossier qui a bougé d’une étape impossible', async () => {
    vi.mocked(advanceIntakeState).mockRejectedValue(
      new OpsGatewayError('conflict', 'conflit', 'state_changed'));
    const perime = await appel({
      request_uuid: UUID, expected_state: 'goods_received', target_state: 'preparing',
    });
    expect(perime.status).toBe(409);
    const corpsPerime = await perime.json();
    expect(corpsPerime.code).toBe('state_changed');
    expect(corpsPerime.error).toContain('changé');

    vi.mocked(advanceIntakeState).mockRejectedValue(
      new OpsGatewayError('conflict', 'conflit', 'state_transition_blocked'));
    const bloque = await appel({
      request_uuid: UUID, expected_state: 'preparing', target_state: 'ready',
    });
    expect(bloque.status).toBe(409);
    expect((await bloque.json()).code).toBe('state_transition_blocked');
  });

  it('traduit un dossier introuvable en 404, une session perdue en 401', async () => {
    vi.mocked(advanceIntakeState).mockRejectedValue(
      new OpsGatewayError('not_found', 'introuvable', 'intake_not_found'));
    expect((await appel({
      request_uuid: UUID, expected_state: 'goods_received', target_state: 'preparing',
    })).status).toBe(404);

    vi.mocked(advanceIntakeState).mockRejectedValue(
      new OpsGatewayError('forbidden', 'refus'));
    expect((await appel({
      request_uuid: UUID, expected_state: 'goods_received', target_state: 'preparing',
    })).status).toBe(401);
  });

  it('F16 · ne laisse fuir ni identifiant interne ni détail de panne', async () => {
    vi.mocked(advanceIntakeState).mockRejectedValue(
      new Error('ECONNREFUSED 127.0.0.1:18169 shipment_id=688'));
    const reponse = await appel({
      request_uuid: UUID, expected_state: 'goods_received', target_state: 'preparing',
    });
    expect(reponse.status).toBe(503);
    const corps = JSON.stringify(await reponse.json());
    for (const interdit of ['ECONNREFUSED', '18169', 'shipment_id', '688']) {
      expect(corps).not.toContain(interdit);
    }
  });

  it('STATE_ROUTE_RATE_LIMIT · finit par refuser une session qui martèle',
    async () => {
      // Le budget de session vaut 60 gestes par fenêtre. Soixante gestes
      // distincts le consomment réellement ; le soixante-et-unième n'a plus
      // rien à dépenser.
      for (let index = 0; index < 60; index += 1) {
        expect((await appel(geste())).status, `geste ${index + 1}`).toBe(200);
      }
      const refuse = await appel(geste());
      expect(refuse.status).toBe(429);
      const attente = Number(refuse.headers.get('retry-after'));
      expect(Number.isFinite(attente)).toBe(true);
      expect(attente).toBeGreaterThan(0);
      expect(refuse.headers.get('cache-control')).toContain('no-store');
      // Le refus est prononcé avant Odoo : 60 appels servis, pas 61.
      expect(vi.mocked(advanceIntakeState)).toHaveBeenCalledTimes(60);
    });

  it('STATE_ROUTE_RETRY_NOT_DOUBLE_COUNTED · une reprise réseau ne coûte rien',
    async () => {
      // Le même geste renvoyé cent fois dépasserait largement le budget s'il
      // était compté à chaque tentative. L'entrepôt perd le réseau ; il ne
      // doit pas y perdre aussi son droit d'écrire.
      const reprise = geste();
      for (let index = 0; index < 100; index += 1) {
        expect((await appel(reprise)).status, `tentative ${index + 1}`).toBe(200);
      }
      // Et le budget est resté quasi intact : un geste neuf passe encore.
      expect((await appel(geste())).status).toBe(200);
    });

  it('n’expose aucun verbe de lecture : cette route n’écrit que', async () => {
    const routeModule = await import('@/app/api/intakes/[reference]/state/route');
    expect(Object.keys(routeModule).filter((cle) => cle !== 'POST' && cle !== 'dynamic'))
      .toEqual([]);
  });
});
