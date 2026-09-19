import type { AccountingStatus } from '@/lib/ops/accounting-status';

const LABELS: Record<AccountingStatus, string> = {
  registered: 'Comptabilisé',
  awaiting_invoice: 'En attente de facture',
  channel_setup_required: 'Canal comptable à configurer',
  invoice_already_paid_review: 'Facture déjà soldée – rapprochement à vérifier',
  needs_review: 'Comptabilisation à vérifier par un responsable',
};

export function accountingStatusLabel(status: string): string {
  if (status in LABELS) return LABELS[status as AccountingStatus];
  return LABELS.needs_review;
}

export function accountingStatusNeedsAttention(status: string): boolean {
  return status === 'channel_setup_required'
    || status === 'invoice_already_paid_review'
    || status === 'needs_review';
}
