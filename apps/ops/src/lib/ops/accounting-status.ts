import { z } from 'zod';

export const accountingStatusSchema = z.enum([
  'registered',
  'awaiting_invoice',
  'channel_setup_required',
  'invoice_already_paid_review',
  'needs_review',
]);

export type AccountingStatus = z.infer<typeof accountingStatusSchema>;
