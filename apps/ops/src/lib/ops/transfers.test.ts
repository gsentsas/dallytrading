import { describe, expect, it } from 'vitest';
import { transferRequest } from './transfers';

describe('transferts caisse', () => {
  it('refuse les champs décidés par le serveur', () => {
    const base = { request_uuid:'00000000-0000-4000-8000-000000000001', to_actor:'Dalanda', transfer_date:'2026-08-29', amount:100000, currency_code:'XOF', payment_method:'cash', reason:'Remise', comment:'' };
    expect(transferRequest.safeParse({...base, from_actor:'Gilles'}).success).toBe(false);
    expect(transferRequest.safeParse(base).success).toBe(true);
  });
});
