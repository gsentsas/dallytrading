/** Contrat public du journal métier Dally Ops. */

import { z } from 'zod';

import { opsGetQuery } from '@/lib/auth/odoo-ops';

/**
 * Les actions du journal métier, telles que le serveur les publie.
 *
 * Le contrat est strict et sans repli : un code que le serveur publie mais que
 * cette liste ignore fait échouer l'analyse de **toute** la page, et le fil
 * d'activité répond alors 503. Un geste de chargement écrit `package_loaded`
 * ou `package_unloaded` ; les déclarer ici n'est donc pas une politesse, c'est
 * ce qui empêche le premier chargement d'éteindre le journal.
 */
export const activityEvent = z.enum([
  'customer_created',
  'intake_created',
  'intake_line_added',
  'intake_line_updated',
  'package_loaded',
  'package_unloaded',
  'payment_recorded',
  'wave_payment_recorded',
  'expense_recorded',
  'expense_receipt_attached',
  'cash_transfer_recorded',
  'cash_transfer_received',
  'appointment_recorded',
  'appointment_marked_present',
  'appointment_marked_absent',
  'appointment_rescheduled',
]);

const activityChange = z.object({
  field: z.string().min(1).max(80),
  label: z.string().min(1).max(120),
  old_value: z.string().max(500),
  new_value: z.string().max(500),
}).strict();

export const activityItem = z.object({
  event: activityEvent,
  category: z.enum([
    'customer', 'reception', 'article', 'correction', 'payment',
    'expense', 'loading', 'transfer', 'appointment',
  ]),
  label: z.string().min(1).max(160),
  occurred_at: z.string().datetime({ offset: true }),
  actor: z.string().min(1).max(200),
  dossier_reference: z.string().nullable(),
  dossier_label: z.string().nullable(),
  summary: z.string().max(500),
  changes: z.array(activityChange).max(32),
}).strict();

export const activityPage = z.object({
  events: z.array(activityItem).max(100),
  next_cursor: z.string().min(1).max(512).nullable(),
  // Le fuseau que le serveur a réellement utilisé pour borner la journée.
  // L'écran formate les heures avec celui-là et non avec le sien : autour de
  // minuit, les deux ne désignent pas le même jour.
  timezone: z.string().min(1).max(64),
  date: z.string().date().optional(),
  scope: z.enum(['mine', 'team']).optional(),
  dossier_reference: z.string().optional(),
  dossier_label: z.string().nullable().optional(),
}).strict();

export type ActivityItem = z.infer<typeof activityItem>;
export type ActivityPage = z.infer<typeof activityPage>;

export interface ActivityQuery {
  readonly date?: string;
  readonly cursor?: string;
  readonly limit?: number;
  readonly type?: z.infer<typeof activityEvent>;
  readonly scope?: 'mine' | 'team';
}

function query(options: ActivityQuery): Record<string, string> {
  const result: Record<string, string> = {};
  if (options.date !== undefined) result.date = options.date;
  if (options.cursor !== undefined) result.cursor = options.cursor;
  if (options.limit !== undefined) result.limit = String(options.limit);
  if (options.type !== undefined) result.type = options.type;
  if (options.scope !== undefined) result.scope = options.scope;
  return result;
}

export async function fetchActivity(
  options: ActivityQuery,
  session: string,
  correlation: string,
): Promise<ActivityPage> {
  return activityPage.parse(await opsGetQuery(
    'activity', query(options), session, correlation,
  ));
}

export async function fetchIntakeActivity(
  reference: string,
  options: Pick<ActivityQuery, 'cursor' | 'limit' | 'type'>,
  session: string,
  correlation: string,
): Promise<ActivityPage> {
  if (!/^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$/.test(reference)) {
    throw new Error('Référence de dossier invalide.');
  }
  return activityPage.parse(await opsGetQuery(
    `intakes/${reference}/activity`, query(options), session, correlation,
  ));
}
