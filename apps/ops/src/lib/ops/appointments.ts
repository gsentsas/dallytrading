import { z } from 'zod';

import { opsGet, opsGetQuery, opsPost } from '@/lib/auth/odoo-ops';
import { preparedReceptionSchema } from '@/features/agenda/reception-context';

export const appointmentKind = z.enum(['dropoff', 'pickup', 'call', 'whatsapp', 'other']);
export const appointmentStatus = z.enum(['scheduled', 'present', 'absent', 'rescheduled']);
const awareIso = z.string().datetime({ offset: true });

export const appointmentCreateRequest = z.object({
  request_uuid: z.string().uuid(),
  customer_reference: z.string().uuid(),
  kind: appointmentKind,
  start_at: awareIso,
  end_at: awareIso,
  consolidation_reference: z.string().trim().min(1).max(120).nullable().optional(),
  location: z.string().trim().min(1).max(200),
  note: z.string().trim().max(2000),
}).strict().refine((body) => new Date(body.end_at) > new Date(body.start_at), {
  message: 'La fin doit suivre le début.', path: ['end_at'],
});

export const appointmentActionRequest = z.object({
  request_uuid: z.string().uuid(),
}).strict();

export const appointmentRescheduleRequest = z.object({
  request_uuid: z.string().uuid(),
  start_at: awareIso,
  end_at: awareIso,
}).strict().refine((body) => new Date(body.end_at) > new Date(body.start_at), {
  message: 'La fin doit suivre le début.', path: ['end_at'],
});

export const appointmentRange = z.object({
  from: awareIso,
  to: awareIso,
}).strict().refine((range) => {
  const duration = new Date(range.to).getTime() - new Date(range.from).getTime();
  return duration > 0 && duration <= 31 * 24 * 60 * 60 * 1000;
}, { message: 'Plage invalide.' });

const customerList = z.object({ name: z.string() }).strict();
const customerDetail = z.object({
  name: z.string(), phone: z.string(), whatsapp: z.string(),
}).strict();

const appointmentBase = {
  reference: z.string().uuid(),
  kind: appointmentKind,
  status: appointmentStatus,
  start_at: awareIso,
  end_at: awareIso,
  consolidation_reference: z.string().nullable(),
  location: z.string(),
} as const;

export const appointmentListItem = z.object({
  ...appointmentBase,
  customer: customerList,
}).strict();

export const appointmentDetail = z.object({
  ...appointmentBase,
  customer: customerDetail,
  note: z.string(),
  rescheduled_from_reference: z.string().uuid().nullable(),
  rescheduled_to_reference: z.string().uuid().nullable(),
}).strict();

const appointmentListResult = z.object({
  from: awareIso,
  to: awareIso,
  appointments: z.array(appointmentListItem),
}).strict();

const appointmentMutationResult = z.object({
  status: z.enum(['created', 'present', 'absent', 'rescheduled', 'replayed']),
  appointment: appointmentDetail,
  previous_reference: z.string().uuid().optional(),
}).strict();

export type Appointment = z.infer<typeof appointmentListItem>;
export type AppointmentDetail = z.infer<typeof appointmentDetail>;
export type AppointmentCreateRequest = z.infer<typeof appointmentCreateRequest>;

export async function fetchAppointments(
  range: z.infer<typeof appointmentRange>, session: string, correlation: string,
) {
  return appointmentListResult.parse(await opsGetQuery(
    'appointments', range, session, correlation,
  ));
}

export async function fetchAppointment(reference: string, session: string, correlation: string) {
  return appointmentDetail.parse(await opsGet(
    `appointments/${encodeURIComponent(reference)}`, session, correlation,
  ));
}

export async function createAppointment(
  body: AppointmentCreateRequest, session: string, correlation: string,
) {
  return appointmentMutationResult.parse(await opsPost(
    'appointments', body, session, correlation,
  ));
}

export async function appointmentAction(
  reference: string, action: 'present' | 'absent', requestUuid: string,
  session: string, correlation: string,
) {
  return appointmentMutationResult.parse(await opsPost(
    `appointments/${encodeURIComponent(reference)}/${action}`,
    { request_uuid: requestUuid }, session, correlation,
  ));
}

export async function rescheduleAppointment(
  reference: string, body: z.infer<typeof appointmentRescheduleRequest>,
  session: string, correlation: string,
) {
  return appointmentMutationResult.parse(await opsPost(
    `appointments/${encodeURIComponent(reference)}/reschedule`,
    body, session, correlation,
  ));
}

export async function prepareAppointmentReception(
  reference: string, session: string, correlation: string,
) {
  return preparedReceptionSchema.parse(await opsPost(
    `appointments/${encodeURIComponent(reference)}/prepare-reception`,
    {}, session, correlation,
  ));
}
