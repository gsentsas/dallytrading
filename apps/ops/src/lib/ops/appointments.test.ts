import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', () => ({
  opsGet: vi.fn(), opsGetQuery: vi.fn(), opsPost: vi.fn(),
}));

const gateway = await import('@/lib/auth/odoo-ops');
const appointments = await import('@/lib/ops/appointments');

const UUID = '00000000-0000-4000-8000-000000000001';
const DETAIL = {
  reference: UUID, kind: 'dropoff', status: 'scheduled',
  start_at: '2026-08-31T10:00:00+00:00', end_at: '2026-08-31T10:30:00+00:00',
  customer: { name: 'Aissatou', phone: '+221771234567', whatsapp: '+221761234567' },
  consolidation_reference: 'AIR-1', location: 'Dépôt', note: '',
  rescheduled_from_reference: null, rescheduled_to_reference: null,
};

beforeEach(() => vi.clearAllMocks());

describe('contrats Agenda', () => {
  it('exige des ISO offset-aware et une fin postérieure', () => {
    const valid = {
      request_uuid: UUID, customer_reference: UUID, kind: 'dropoff',
      start_at: '2026-08-31T12:00:00+02:00', end_at: '2026-08-31T12:30:00+02:00',
      consolidation_reference: null, location: 'Dépôt', note: '',
    };
    expect(appointments.appointmentCreateRequest.safeParse(valid).success).toBe(true);
    expect(appointments.appointmentCreateRequest.safeParse({
      ...valid, start_at: '2026-08-31T12:00:00',
    }).success).toBe(false);
    expect(appointments.appointmentCreateRequest.safeParse({
      ...valid, end_at: valid.start_at,
    }).success).toBe(false);
  });

  it('refuse toute clé native ou technique fournie par le navigateur', () => {
    const base = {
      request_uuid: UUID, customer_reference: UUID, kind: 'call',
      start_at: '2026-08-31T10:00:00Z', end_at: '2026-08-31T10:30:00Z',
      location: 'Dépôt', note: '',
    };
    for (const field of ['partner_id', 'user_id', 'name', 'partner_ids',
                         'attendee_ids', 'alarm_ids', 'state', 'status']) {
      expect(appointments.appointmentCreateRequest.safeParse({
        ...base, [field]: 1,
      }).success).toBe(false);
    }
  });

  it('borne la plage à 31 jours', () => {
    expect(appointments.appointmentRange.safeParse({
      from: '2026-08-01T00:00:00Z', to: '2026-09-01T00:00:00Z',
    }).success).toBe(true);
    expect(appointments.appointmentRange.safeParse({
      from: '2026-08-01T00:00:00Z', to: '2026-09-01T00:00:01Z',
    }).success).toBe(false);
  });

  it('la liste refuse un téléphone et tout identifiant Odoo inattendu', async () => {
    vi.mocked(gateway.opsGetQuery).mockResolvedValue({
      from: '2026-08-31T00:00:00+00:00', to: '2026-09-01T00:00:00+00:00',
      appointments: [{ ...DETAIL, customer: { name: 'Aissatou', phone: 'secret' },
        note: undefined, rescheduled_from_reference: undefined,
        rescheduled_to_reference: undefined }],
    });
    await expect(appointments.fetchAppointments({
      from: '2026-08-31T00:00:00+00:00', to: '2026-09-01T00:00:00+00:00',
    }, 'session', 'corr')).rejects.toBeDefined();
  });

  it('la création valide strictement le DTO Odoo', async () => {
    vi.mocked(gateway.opsPost).mockResolvedValue({
      status: 'created', appointment: { ...DETAIL, calendar_event_id: 7 },
    });
    await expect(appointments.createAppointment({
      request_uuid: UUID, customer_reference: UUID, kind: 'dropoff',
      start_at: DETAIL.start_at, end_at: DETAIL.end_at,
      consolidation_reference: null, location: 'Dépôt', note: '',
    }, 'session', 'corr')).rejects.toBeDefined();
  });

  it('n’envoie jamais le request_uuid du navigateur à Odoo', async () => {
    // Le navigateur en fournit un, et c'est voulu : le squelette de mutation
    // s'en sert pour ne pas compter deux fois une reprise réseau. Mais
    // `prepare-reception` ne crée aucun objet métier — le handle client est
    // déjà idempotent par contrainte d'unicité — donc rien n'a à être
    // dédupliqué côté Odoo, et l'identifiant s'arrête au BFF.
    vi.mocked(gateway.opsPost).mockResolvedValue({
      customer_reference: UUID, customer_name: 'Aissatou',
      consolidation_reference: 'AIR-1',
    });
    await appointments.prepareAppointmentReception(UUID, 'session', 'corr');
    expect(gateway.opsPost).toHaveBeenCalledWith(
      `appointments/${UUID}/prepare-reception`, {}, 'session', 'corr');
    const [, corps] = vi.mocked(gateway.opsPost).mock.calls[0] ?? [];
    expect(corps).toEqual({});
    expect(JSON.stringify(corps)).not.toContain('request_uuid');
  });

  it('encode la plage via la passerelle contrôlée', async () => {
    vi.mocked(gateway.opsGetQuery).mockResolvedValue({
      from: '2026-08-31T00:00:00+00:00', to: '2026-09-01T00:00:00+00:00',
      appointments: [],
    });
    const range = { from: '2026-08-31T00:00:00+00:00', to: '2026-09-01T00:00:00+00:00' };
    await appointments.fetchAppointments(range, 'session', 'corr');
    expect(gateway.opsGetQuery).toHaveBeenCalledWith(
      'appointments', range, 'session', 'corr');
  });
});
