import { describe, expect, it } from 'vitest';
import {
  SOURCING_CURRENCIES,
  SOURCING_STEPS,
  STEP_FIELDS,
  STEP_LABELS,
  isBotSubmission,
  sourcingFormSchema,
  toSourcingInput,
} from './sourcing-schema';

const VALID_UUID = '3f2504e0-4f89-41d3-9a0c-0305e82c3301';

function payload(overrides: Record<string, unknown> = {}) {
  return {
    requestUuid: VALID_UUID,
    productName: 'Panneaux solaires 400W',
    quantity: '200',
    lastName: 'Diallo',
    email: 'awa@example.com',
    ...overrides,
  };
}

describe('sourcingFormSchema', () => {
  it('accepts a minimal valid request', () => {
    expect(sourcingFormSchema.safeParse(payload()).success).toBe(true);
  });

  it('requires a product name of some substance', () => {
    expect(sourcingFormSchema.safeParse(payload({ productName: '' })).success)
      .toBe(false);
    expect(sourcingFormSchema.safeParse(payload({ productName: 'x' })).success)
      .toBe(false);
  });

  it('requires a name', () => {
    expect(sourcingFormSchema.safeParse(payload({ lastName: '   ' })).success)
      .toBe(false);
  });

  it('requires a way to reply', () => {
    expect(
      sourcingFormSchema.safeParse(payload({ email: '', phone: '' })).success,
    ).toBe(false);
    expect(
      sourcingFormSchema.safeParse(payload({ email: '', phone: '771234567' }))
        .success,
    ).toBe(true);
  });

  it('rejects a malformed email', () => {
    for (const bad of ['nope', 'a@b', '@example.com', 'a b@c.com']) {
      expect(sourcingFormSchema.safeParse(payload({ email: bad })).success)
        .toBe(false);
    }
  });

  // ─── Quantity ────────────────────────────────────────────────────

  it('parses a quantity sent as a string', () => {
    const result = sourcingFormSchema.safeParse(payload({ quantity: '1250.5' }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.quantity).toBe(1250.5);
    }
  });

  it('rejects a zero or negative quantity', () => {
    for (const value of ['0', '-5', 0, -5]) {
      expect(sourcingFormSchema.safeParse(payload({ quantity: value })).success)
        .toBe(false);
    }
  });

  it('rejects an absurd or non-numeric quantity', () => {
    expect(
      sourcingFormSchema.safeParse(payload({ quantity: '99999999999' })).success,
    ).toBe(false);
    expect(sourcingFormSchema.safeParse(payload({ quantity: 'beaucoup' })).success)
      .toBe(false);
  });

  it('requires a quantity', () => {
    const withoutQuantity = payload();
    delete (withoutQuantity as Record<string, unknown>).quantity;
    expect(sourcingFormSchema.safeParse(withoutQuantity).success).toBe(false);
  });

  // ─── Budget ──────────────────────────────────────────────────────

  it('treats an empty budget as absent, not as zero', () => {
    // "Not decided yet" and "zero budget" are different statements.
    const result = sourcingFormSchema.safeParse(payload({ budget: '' }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.budget).toBeUndefined();
    }
  });

  it('rejects a negative budget', () => {
    expect(sourcingFormSchema.safeParse(payload({ budget: '-100' })).success)
      .toBe(false);
  });

  it('accepts every offered currency', () => {
    for (const entry of SOURCING_CURRENCIES) {
      expect(
        sourcingFormSchema.safeParse(payload({ currency: entry.code })).success,
      ).toBe(true);
    }
  });

  it('rejects a currency outside the offered list', () => {
    expect(sourcingFormSchema.safeParse(payload({ currency: 'ZZZ' })).success)
      .toBe(false);
  });

  // ─── Countries and dates ─────────────────────────────────────────

  it('normalises country codes', () => {
    const result = sourcingFormSchema.safeParse(
      payload({ preferredOriginCountry: ' cn ', destinationCountry: 'sn' }),
    );
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.preferredOriginCountry).toBe('CN');
      expect(result.data.destinationCountry).toBe('SN');
    }
  });

  it('rejects a country code of the wrong length', () => {
    expect(
      sourcingFormSchema.safeParse(payload({ destinationCountry: 'SEN' })).success,
    ).toBe(false);
  });

  it('accepts an ISO date and rejects other formats', () => {
    expect(
      sourcingFormSchema.safeParse(payload({ requestedDeadline: '2026-06-01' }))
        .success,
    ).toBe(true);
    for (const bad of ['01/06/2026', '2026-6-1', '2026-13-01', 'bientôt']) {
      expect(
        sourcingFormSchema.safeParse(payload({ requestedDeadline: bad })).success,
      ).toBe(false);
    }
  });

  it('rejects a date that does not exist', () => {
    // 30 February parses in some engines; it must not here.
    expect(
      sourcingFormSchema.safeParse(payload({ requestedDeadline: '2026-02-30' }))
        .success,
    ).toBe(false);
  });

  // ─── Field stripping ─────────────────────────────────────────────

  it('ignores fields it does not declare', () => {
    const result = sourcingFormSchema.safeParse(
      payload({ state: 'completed', responsibleId: 1, internalNotes: 'x' }),
    );
    expect(result.success).toBe(true);
    if (result.success) {
      expect('state' in result.data).toBe(false);
      expect('responsibleId' in result.data).toBe(false);
      expect('internalNotes' in result.data).toBe(false);
    }
  });
});

describe('isBotSubmission', () => {
  it('flags a filled honeypot', () => {
    const result = sourcingFormSchema.safeParse(payload({ website: 'http://spam' }));
    expect(result.success && isBotSubmission(result.data)).toBe(true);
  });

  it('does not flag an absent honeypot', () => {
    const result = sourcingFormSchema.safeParse(payload());
    expect(result.success && isBotSubmission(result.data)).toBe(false);
  });
});

describe('steps', () => {
  it('has five steps in the order the form presents them', () => {
    expect(SOURCING_STEPS).toEqual([
      'product', 'quantity', 'route', 'contact', 'confirm',
    ]);
  });

  it('labels every step', () => {
    for (const step of SOURCING_STEPS) {
      expect(STEP_LABELS[step]).toBeTruthy();
    }
  });

  it('assigns every validated field to exactly one step', () => {
    // A field on no step would never be validated during navigation; a field on two
    // would report the same error twice.
    const seen = new Set<string>();
    for (const step of SOURCING_STEPS) {
      for (const field of STEP_FIELDS[step]) {
        expect(seen.has(field)).toBe(false);
        seen.add(field);
      }
    }
  });

  it('covers the required fields across the steps', () => {
    const all = SOURCING_STEPS.flatMap((step) => [...STEP_FIELDS[step]]);
    for (const required of ['productName', 'quantity', 'lastName', 'email']) {
      expect(all).toContain(required);
    }
  });

  it('leaves the confirmation step without fields of its own', () => {
    expect(STEP_FIELDS.confirm).toEqual([]);
  });
});

describe('toSourcingInput', () => {
  function parsed(overrides: Record<string, unknown> = {}) {
    const result = sourcingFormSchema.safeParse(payload(overrides));
    if (!result.success) throw new Error('fixture should parse');
    return result.data;
  }

  it('nests customer and product to match the API contract', () => {
    const input = toSourcingInput(parsed({
      firstName: 'Awa', companyName: 'Diallo Trading',
      productDescription: 'Résidentiel',
    }));

    expect(input.customer).toMatchObject({
      lastName: 'Diallo', firstName: 'Awa', company: 'Diallo Trading',
      email: 'awa@example.com',
    });
    expect(input.product).toMatchObject({
      name: 'Panneaux solaires 400W', description: 'Résidentiel',
    });
    expect(input.quantity).toBe(200);
  });

  it('always declares the sourcing service', () => {
    expect(toSourcingInput(parsed()).serviceCode).toBe('sourcing');
  });

  it('drops the honeypot and the idempotency key', () => {
    const input = toSourcingInput(parsed({ website: 'spam' })) as unknown as
      Record<string, unknown>;
    expect('website' in input).toBe(false);
    expect('requestUuid' in input).toBe(false);
  });

  it('omits absent optional fields rather than sending empty values', () => {
    const input = toSourcingInput(parsed()) as unknown as Record<string, unknown>;
    expect('budget' in input).toBe(false);
    expect('preferredOriginCountry' in input).toBe(false);
    expect('utm' in input).toBe(false);
  });

  it('nests utm only when something was captured', () => {
    const withUtm = toSourcingInput(parsed({ utmSource: 'google' }));
    expect(withUtm.utm).toMatchObject({ source: 'google' });

    const withoutUtm = toSourcingInput(parsed()) as unknown as
      Record<string, unknown>;
    expect('utm' in withoutUtm).toBe(false);
  });

  it('carries no field that could disclose internal data', () => {
    // The input type has no place for a supplier, a cost or a margin — those exist
    // only inside Odoo, on models the sourcing API user cannot reach.
    const serialised = JSON.stringify(toSourcingInput(parsed()));
    for (const forbidden of [
      'supplier', 'offer', 'cost', 'margin', 'internal', 'score',
    ]) {
      expect(serialised.toLowerCase()).not.toContain(forbidden);
    }
  });
});
