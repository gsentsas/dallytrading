import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/ops/appointments', async (load) => {
  const original = await load<typeof import('@/lib/ops/appointments')>();
  return { ...original, createAppointment: vi.fn(), fetchAppointments: vi.fn() };
});

const auth = await import('@/lib/auth/auth');
const service = await import('@/lib/ops/appointments');
const { resetRateLimits } = await import('@/lib/rate-limit');
const route = await import('@/app/api/appointments/route');

const UUID = '00000000-0000-4000-8000-000000000001';
const BODY = {
  request_uuid: UUID, customer_reference: UUID, kind: 'dropoff' as const,
  start_at: '2026-08-31T10:00:00Z', end_at: '2026-08-31T10:30:00Z',
  consolidation_reference: null, location: 'Dépôt', note: '',
};

function request(path = '/api/appointments', body: unknown = BODY, origin = 'https://ops.example.test') {
  return new Request(`https://ops.example.test${path}`, {
    method: 'POST', headers: { 'content-type': 'application/json', origin },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  resetRateLimits();
  vi.clearAllMocks();
  vi.mocked(auth.readOpsSession).mockResolvedValue({ odooSessionId: 'session', issuedAt: Date.now() });
});

describe('BFF Agenda', () => {
  it('refuse une origine étrangère avant tout appel', async () => {
    const response = await route.POST(request('/api/appointments', BODY, 'https://evil.invalid'));
    expect(response.status).toBe(403);
    expect(service.createAppointment).not.toHaveBeenCalled();
  });

  it('refuse strictement un champ partner_id', async () => {
    const response = await route.POST(request('/api/appointments', { ...BODY, partner_id: 7 }));
    expect(response.status).toBe(400);
    expect(service.createAppointment).not.toHaveBeenCalled();
  });

  it('présente seulement la session Ops au service', async () => {
    vi.mocked(service.createAppointment).mockResolvedValue({
      status: 'created', appointment: {
        reference: UUID, kind: 'dropoff', status: 'scheduled',
        start_at: BODY.start_at, end_at: BODY.end_at,
        customer: { name: 'Aissatou', phone: '', whatsapp: '' },
        consolidation_reference: null, location: 'Dépôt', note: '',
        rescheduled_from_reference: null, rescheduled_to_reference: null,
      },
    });
    const response = await route.POST(request());
    expect(response.status).toBe(200);
    expect(service.createAppointment).toHaveBeenCalledWith(
      BODY, 'session', expect.any(String));
  });

  it('valide la plage GET avant le service', async () => {
    const bad = await route.GET(new Request(
      'https://ops.example.test/api/appointments?from=2026-08-01T00:00:00Z&to=2026-10-01T00:00:00Z'));
    expect(bad.status).toBe(400);
    expect(service.fetchAppointments).not.toHaveBeenCalled();
  });

  it('lit aujourd’hui avec Origin, session, débit et schéma', async () => {
    vi.mocked(service.fetchAppointments).mockResolvedValue({
      from: '2026-08-31T00:00:00Z', to: '2026-09-01T00:00:00Z', appointments: [],
    });
    const response = await route.GET(new Request(
      'https://ops.example.test/api/appointments?from=2026-08-31T00:00:00Z&to=2026-09-01T00:00:00Z',
      { headers: { origin: 'https://ops.example.test' } }));
    expect(response.status).toBe(200);
    expect(service.fetchAppointments).toHaveBeenCalledWith(
      { from: '2026-08-31T00:00:00Z', to: '2026-09-01T00:00:00Z' },
      'session', expect.any(String));
  });
});
