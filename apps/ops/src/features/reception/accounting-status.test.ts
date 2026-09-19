import { describe, expect, it } from 'vitest';

import {
  accountingStatusLabel,
  accountingStatusNeedsAttention,
} from '@/features/reception/accounting-status';
import { accountingStatusSchema } from '@/lib/ops/accounting-status';

describe('statuts comptables Ops', () => {
  it.each([
    ['registered', 'Comptabilisé'],
    ['awaiting_invoice', 'En attente de facture'],
    ['channel_setup_required', 'Canal comptable à configurer'],
    ['invoice_already_paid_review', 'Facture déjà soldée – rapprochement à vérifier'],
    ['needs_review', 'Comptabilisation à vérifier par un responsable'],
  ] as const)('affiche %s avec le libellé opérateur attendu', (status, label) => {
    expect(accountingStatusSchema.safeParse(status).success).toBe(true);
    expect(accountingStatusLabel(status)).toBe(label);
  });

  it('ne met pas en alerte une attente normale de facture', () => {
    expect(accountingStatusNeedsAttention('registered')).toBe(false);
    expect(accountingStatusNeedsAttention('awaiting_invoice')).toBe(false);
  });

  it('met en alerte les blocages qui demandent une action ou un rapprochement', () => {
    expect(accountingStatusNeedsAttention('channel_setup_required')).toBe(true);
    expect(accountingStatusNeedsAttention('invoice_already_paid_review')).toBe(true);
    expect(accountingStatusNeedsAttention('needs_review')).toBe(true);
  });
});
