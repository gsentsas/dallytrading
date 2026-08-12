import { describe, expect, it } from 'vitest';
import {
  isBotSubmission,
  quoteFormSchema,
  toLeadInput,
  type QuoteFormData,
} from './schema';

/**
 * The schema is the server-side gate on everything a stranger can submit. These
 * tests pin the boundary between "accept" and "reject", because both mistakes are
 * expensive: too strict turns away customers, too loose fills the CRM with junk.
 */

const VALID_UUID = '3f2504e0-4f89-41d3-9a0c-0305e82c3301';

function payload(overrides: Record<string, unknown> = {}) {
  return {
    requestUuid: VALID_UUID,
    serviceCode: 'freight_sea',
    lastName: 'Ndiaye',
    firstName: 'Aliou',
    email: 'aliou@example.com',
    phone: '+221 77 123 45 67',
    ...overrides,
  };
}

describe('quoteFormSchema', () => {
  it('accepts a complete submission', () => {
    const result = quoteFormSchema.safeParse(payload());
    expect(result.success).toBe(true);
  });

  it('requires a valid UUID', () => {
    for (const value of ['', 'not-a-uuid', '123', VALID_UUID.slice(0, -1)]) {
      expect(quoteFormSchema.safeParse(payload({ requestUuid: value })).success).toBe(
        false,
      );
    }
  });

  it('requires a last name', () => {
    expect(quoteFormSchema.safeParse(payload({ lastName: '' })).success).toBe(false);
    expect(quoteFormSchema.safeParse(payload({ lastName: '   ' })).success).toBe(
      false,
    );
  });

  it('requires a service code in the expected format', () => {
    expect(quoteFormSchema.safeParse(payload({ serviceCode: '' })).success).toBe(
      false,
    );
    expect(
      quoteFormSchema.safeParse(payload({ serviceCode: 'Freight-Sea' })).success,
    ).toBe(false);
    expect(
      quoteFormSchema.safeParse(payload({ serviceCode: 'freight_sea' })).success,
    ).toBe(true);
  });

  it('requires at least an email or a phone', () => {
    const result = quoteFormSchema.safeParse(
      payload({ email: '', phone: '' }),
    );
    expect(result.success).toBe(false);
  });

  it('accepts a phone with no email', () => {
    expect(quoteFormSchema.safeParse(payload({ email: '' })).success).toBe(true);
  });

  it('accepts an email with no phone', () => {
    expect(quoteFormSchema.safeParse(payload({ phone: '' })).success).toBe(true);
  });

  it('rejects malformed email addresses', () => {
    for (const value of ['nope', 'a@b', '@example.com', 'a@@b.com', 'a b@c.com']) {
      expect(quoteFormSchema.safeParse(payload({ email: value })).success).toBe(
        false,
      );
    }
  });

  it('accepts international phone formats', () => {
    // An import/export business must not turn away foreign prospects.
    for (const value of [
      '+221 77 123 45 67',
      '0033 6 12 34 56 78',
      '+1 (555) 010-9999',
      '771234567',
    ]) {
      expect(quoteFormSchema.safeParse(payload({ phone: value })).success).toBe(
        true,
      );
    }
  });

  it('rejects a phone with too few digits', () => {
    expect(quoteFormSchema.safeParse(payload({ phone: '123' })).success).toBe(false);
  });

  it('trims and uppercases the country code', () => {
    const result = quoteFormSchema.safeParse(payload({ countryCode: ' sn ' }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.countryCode).toBe('SN');
    }
  });

  it('rejects a country code of the wrong length', () => {
    expect(quoteFormSchema.safeParse(payload({ countryCode: 'SEN' })).success).toBe(
      false,
    );
  });

  it('turns empty optional strings into undefined', () => {
    const result = quoteFormSchema.safeParse(
      payload({ companyName: '', city: '   ' }),
    );
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.companyName).toBeUndefined();
      expect(result.data.city).toBeUndefined();
    }
  });

  it('rejects an over-long message', () => {
    expect(
      quoteFormSchema.safeParse(payload({ message: 'x'.repeat(20_001) })).success,
    ).toBe(false);
  });

  it('ignores fields it does not declare', () => {
    // Strips rather than trusts: a caller must not be able to set arbitrary data.
    const result = quoteFormSchema.safeParse(
      payload({ expectedRevenue: 999_999, userId: 1 }),
    );
    expect(result.success).toBe(true);
    if (result.success) {
      expect('expectedRevenue' in result.data).toBe(false);
      expect('userId' in result.data).toBe(false);
    }
  });
});

describe('isBotSubmission', () => {
  it('flags a filled honeypot', () => {
    const result = quoteFormSchema.safeParse(payload({ website: 'http://spam.example' }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(isBotSubmission(result.data)).toBe(true);
    }
  });

  it('does not flag an absent or empty honeypot', () => {
    const absent = quoteFormSchema.safeParse(payload());
    const empty = quoteFormSchema.safeParse(payload({ website: '' }));
    expect(absent.success && isBotSubmission(absent.data)).toBe(false);
    expect(empty.success && isBotSubmission(empty.data)).toBe(false);
  });
});

describe('toLeadInput', () => {
  it('maps the fields the gateway expects', () => {
    const parsed = quoteFormSchema.safeParse(
      payload({ companyName: 'Ndiaye SARL', countryCode: 'SN', city: 'Dakar' }),
    );
    expect(parsed.success).toBe(true);
    if (!parsed.success) return;

    const input = toLeadInput(parsed.data);
    expect(input).toMatchObject({
      serviceCode: 'freight_sea',
      lastName: 'Ndiaye',
      firstName: 'Aliou',
      companyName: 'Ndiaye SARL',
      countryCode: 'SN',
      city: 'Dakar',
    });
  });

  it('drops the honeypot and the idempotency key', () => {
    const parsed = quoteFormSchema.safeParse(payload({ website: 'spam' }));
    expect(parsed.success).toBe(true);
    if (!parsed.success) return;

    const input = toLeadInput(parsed.data) as unknown as Record<string, unknown>;
    // requestUuid travels as a separate argument: it describes the call, not
    // the lead. The honeypot is plumbing and must never reach the ERP.
    expect('website' in input).toBe(false);
    expect('requestUuid' in input).toBe(false);
  });

  it('omits absent optional fields rather than sending empty strings', () => {
    const parsed = quoteFormSchema.safeParse(payload({ companyName: '' }));
    expect(parsed.success).toBe(true);
    if (!parsed.success) return;

    const input = toLeadInput(parsed.data) as unknown as Record<string, unknown>;
    expect('companyName' in input).toBe(false);
  });

  it('accepts data typed as QuoteFormData', () => {
    // Compile-time guard: toLeadInput must keep accepting the schema's output
    // type, so a schema change that breaks the mapping fails typecheck.
    const parsed = quoteFormSchema.safeParse(payload());
    if (!parsed.success) throw new Error('fixture should parse');
    const data: QuoteFormData = parsed.data;
    expect(toLeadInput(data).lastName).toBe('Ndiaye');
  });
});
