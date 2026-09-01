import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * La consignation d'un événement, vue du BFF.
 *
 * La route emprunte le squelette commun des mutations : ces tests vérifient
 * donc surtout ce qui lui est propre — son budget de débit, la traduction de
 * ses refus, et le fait qu'aucun champ de publication n'existe.
 */

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/http/origine', () => ({ origineAcceptable: vi.fn(() => true) }));
vi.mock('@/lib/ops/events', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/ops/events')>();
  return { ...original, createEvent: vi.fn(), fetchEvents: vi.fn() };
});

const { readOpsSession } = await import('@/lib/auth/auth');
const { origineAcceptable } = await import('@/lib/http/origine');
const { createEvent, fetchEvents } = await import('@/lib/ops/events');
const { OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const {
  OPS_EVENT_SESSION, checkRateLimit, cleDemandeComptee, cleEvenementDemande,
  cleEvenementSession, peekRateLimit, resetRateLimits,
} = await import('@/lib/rate-limit');
const { GET, POST } = await import('@/app/api/intakes/[reference]/events/route');

const REFERENCE = 'AIR-DSS-CDG-2026-902-A001';
const UUID = '11111111-1111-4111-8111-111111111111';

const EVENEMENT = {
  kind: 'damage_noted', kind_label: 'Dommage constaté',
  description: 'Dommage constaté', note: 'Coin écrasé',
  status: 'preparing', status_label: 'Preparing',
  event_date: '2026-09-01T09:00:00Z', recorded_by: 'Gilles',
  source: 'ops' as const,
};

const LISTE = {
  events: [EVENEMENT],
  can_add: true,
  kinds: [{ kind: 'anomaly' as const, label: 'Anomalie constatée',
            note_required: true }],
};

function appel(corps: unknown, entetes: Record<string, string> = {}): Promise<Response> {
  return POST(
    new Request(`https://ops.test/api/intakes/${REFERENCE}/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...entetes },
      body: JSON.stringify(corps),
    }),
    { params: Promise.resolve({ reference: REFERENCE }) },
  ) as unknown as Promise<Response>;
}

function contexte() {
  return { params: Promise.resolve({ reference: REFERENCE }) };
}

const GESTE = { request_uuid: UUID, kind: 'anomaly', note: 'Carton enfoncé' };

beforeEach(() => {
  resetRateLimits();
  vi.mocked(readOpsSession).mockReset();
  vi.mocked(origineAcceptable).mockReset();
  vi.mocked(createEvent).mockReset();
  vi.mocked(fetchEvents).mockReset();
  vi.mocked(readOpsSession).mockResolvedValue({ odooSessionId: 'session', issuedAt: 1 });
  vi.mocked(origineAcceptable).mockReturnValue(true);
  vi.mocked(createEvent).mockResolvedValue({ event: EVENEMENT, replayed: false });
  vi.mocked(fetchEvents).mockResolvedValue(LISTE);
});

describe('POST · les gardes d’entrée', () => {
  it('relaie une demande bien formée sans jamais la mettre en cache', async () => {
    const reponse = await appel(GESTE);
    expect(reponse.status).toBe(200);
    expect(reponse.headers.get('cache-control')).toContain('no-store');
    expect(createEvent).toHaveBeenCalledWith(
      REFERENCE, GESTE, 'session', expect.any(String));
  });

  it('refuse l’absence de session avant d’interroger Odoo', async () => {
    vi.mocked(readOpsSession).mockResolvedValue(null);
    expect((await appel(GESTE)).status).toBe(401);
    expect(createEvent).not.toHaveBeenCalled();
  });

  it('refuse une origine inacceptable', async () => {
    vi.mocked(origineAcceptable).mockReturnValue(false);
    expect((await appel(GESTE)).status).toBe(403);
    expect(createEvent).not.toHaveBeenCalled();
  });

  it('refuse un corps qui n’est pas du JSON', async () => {
    const reponse = await appel(GESTE, { 'Content-Type': 'text/plain' });
    expect(reponse.status).toBe(415);
    expect(createEvent).not.toHaveBeenCalled();
  });

  it('refuse tout champ qui prétendrait publier ou notifier', async () => {
    for (const champ of ['visible_to_customer', 'is_automatic', 'status',
                         'description', 'event_date', 'location',
                         'publish', 'notify']) {
      const reponse = await appel({ ...GESTE, [champ]: true });
      expect(reponse.status, champ).toBe(400);
    }
    expect(createEvent).not.toHaveBeenCalled();
  });

  it('refuse une nature inconnue et un identifiant mal formé', async () => {
    expect((await appel({ ...GESTE, kind: 'selfie' })).status).toBe(400);
    expect((await appel({ ...GESTE, request_uuid: 'x' })).status).toBe(400);
    expect(createEvent).not.toHaveBeenCalled();
  });
});

describe('les refus d’Odoo sont traduits, jamais relayés bruts', () => {
  it.each([
    ['unprocessable', 'event_kind_invalid', 422, 'nature'],
    ['unprocessable', 'event_note_required', 422, 'note'],
    ['unprocessable', 'event_note_too_long', 422, 'trop longue'],
    ['conflict', 'event_state_not_allowed', 409, 'plus d’événement'],
    ['conflict', 'idempotency_conflict', 409, 'déjà été traitée'],
  ] as const)('%s/%s → %i', async (code, refus, statut, extrait) => {
    vi.mocked(createEvent).mockRejectedValue(
      new OpsGatewayError(code, 'x', refus));
    const reponse = await appel(GESTE);
    expect(reponse.status).toBe(statut);
    const corps = await reponse.json();
    expect(corps.code).toBe(refus);
    expect(corps.error).toContain(extrait);
  });

  it('ne laisse fuir ni identifiant interne ni détail de panne', async () => {
    vi.mocked(createEvent).mockRejectedValue(
      new Error('ECONNREFUSED 127.0.0.1:18169 shipment_id=688'));
    const reponse = await appel(GESTE);
    expect(reponse.status).toBe(503);
    const corps = JSON.stringify(await reponse.json());
    for (const interdit of ['ECONNREFUSED', '18169', 'shipment_id', '688']) {
      expect(corps).not.toContain(interdit);
    }
  });
});

describe('le débit propre aux événements', () => {
  it('refuse au-delà de vingt gestes distincts, budget des réceptions intact',
    async () => {
      for (let index = 0; index < 20; index += 1) {
        expect((await appel({ ...GESTE, request_uuid: crypto.randomUUID() }))
          .status, `geste ${index + 1}`).toBe(200);
      }
      const refuse = await appel({ ...GESTE, request_uuid: crypto.randomUUID() });
      expect(refuse.status).toBe(429);
      expect(Number(refuse.headers.get('retry-after'))).toBeGreaterThan(0);
      expect(vi.mocked(createEvent)).toHaveBeenCalledTimes(20);
    });

  it('la clé d’un événement n’est pas celle des créations de client', () => {
    expect(cleEvenementDemande(UUID)).not.toBe(cleDemandeComptee(UUID));
    expect(cleEvenementDemande(UUID)).toMatch(/^ops:events:uuid:/);
    expect(cleDemandeComptee(UUID)).toMatch(/^ops:customers:create:uuid:/);
  });

  it('un UUID déjà employé par une autre mutation ne vole pas ce budget',
    async () => {
      // Une autre mutation a consommé CE même uuid, dans SON espace à elle.
      checkRateLimit(cleDemandeComptee(UUID), 1, OPS_EVENT_SESSION.fenetreMs);
      const avant = peekRateLimit(
        cleEvenementSession('session'), OPS_EVENT_SESSION.limite);
      expect((await appel(GESTE)).status).toBe(200);
      const apres = peekRateLimit(
        cleEvenementSession('session'), OPS_EVENT_SESSION.limite);
      expect(apres.remaining, 'le geste doit consommer son propre budget')
        .toBe(avant.remaining - 1);
    });

  it('mais la reprise agit bien, dans l’espace des événements', async () => {
    checkRateLimit(cleEvenementDemande(UUID), 1, OPS_EVENT_SESSION.fenetreMs);
    const avant = peekRateLimit(
      cleEvenementSession('session'), OPS_EVENT_SESSION.limite);
    expect((await appel(GESTE)).status).toBe(200);
    const apres = peekRateLimit(
      cleEvenementSession('session'), OPS_EVENT_SESSION.limite);
    expect(apres.remaining, 'un geste déjà compté ne se recompte pas')
      .toBe(avant.remaining);
  });

  it('une reprise du même geste ne consomme pas une seconde unité', async () => {
    for (let index = 0; index < 50; index += 1) {
      expect((await appel(GESTE)).status, `tentative ${index + 1}`).toBe(200);
    }
    // Le budget est resté quasi intact : un geste neuf passe encore.
    expect((await appel({ ...GESTE, request_uuid: crypto.randomUUID() })).status)
      .toBe(200);
  });
});

describe('GET · la liste', () => {
  it('rend la liste sans jamais la mettre en cache', async () => {
    const reponse = await GET(
      new Request(`https://ops.test/api/intakes/${REFERENCE}/events`), contexte());
    expect(reponse.status).toBe(200);
    expect(reponse.headers.get('cache-control')).toContain('no-store');
    expect((await reponse.json()).data).toEqual(LISTE);
  });

  it('refuse sans session, et traduit un dossier introuvable', async () => {
    vi.mocked(readOpsSession).mockResolvedValue(null);
    expect((await GET(new Request('https://ops.test/x'), contexte())).status)
      .toBe(401);

    vi.mocked(readOpsSession).mockResolvedValue({
      odooSessionId: 'session', issuedAt: 1 });
    vi.mocked(fetchEvents).mockRejectedValue(
      new OpsGatewayError('not_found', 'introuvable'));
    expect((await GET(new Request('https://ops.test/x'), contexte())).status)
      .toBe(404);
  });
});
