import { describe, expect, it } from 'vitest';
import {
  FORBIDDEN_PUBLIC_FIELDS,
  STEP_FIELDS,
  STEP_LABELS,
  TRADE_OPERATION_TYPES,
  TRADE_STEPS,
  findForbiddenField,
  isBotSubmission,
  toTradeInput,
  tradeFormSchema,
  type TradeFormData,
} from './trade-schema';

const UUID = '7c9e6679-7425-40de-944b-e07fc1f90ae7';

function valid(overrides: Record<string, unknown> = {}) {
  return {
    requestUuid: UUID,
    operationType: 'purchase_resale',
    subject: 'Import de riz parfumé',
    contactName: 'Aminata Diallo',
    email: 'aminata@example.com',
    ...overrides,
  };
}

describe('tradeFormSchema', () => {
  it('accepts a minimal valid enquiry', () => {
    const result = tradeFormSchema.safeParse(valid());
    expect(result.success).toBe(true);
  });

  it('requires an operation type', () => {
    const result = tradeFormSchema.safeParse(valid({ operationType: undefined }));
    expect(result.success).toBe(false);
  });

  it('refuses an operation type the module does not declare', () => {
    const result = tradeFormSchema.safeParse(valid({ operationType: 'franchise' }));
    expect(result.success).toBe(false);
  });

  it('accepts every declared operation type', () => {
    for (const type of TRADE_OPERATION_TYPES) {
      const result = tradeFormSchema.safeParse(
        valid({ operationType: type.value }),
      );
      expect(result.success, `${type.value} was rejected`).toBe(true);
    }
  });

  it('requires a subject long enough to be a subject', () => {
    expect(tradeFormSchema.safeParse(valid({ subject: 'x' })).success).toBe(false);
  });

  it('requires a way to reply', () => {
    const result = tradeFormSchema.safeParse(
      valid({ email: undefined, phone: undefined }),
    );
    expect(result.success).toBe(false);
  });

  it('accepts a phone alone', () => {
    const result = tradeFormSchema.safeParse(
      valid({ email: undefined, phone: '+221 77 123 45 67' }),
    );
    expect(result.success).toBe(true);
  });

  it('reports the missing-contact rule on a field the contact step owns', () => {
    // Otherwise the message appears on a step the user cannot act from, which reads
    // as the form being broken.
    const result = tradeFormSchema.safeParse(
      valid({ email: undefined, phone: undefined }),
    );
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((issue) => issue.path.join('.'));
      expect(paths).toContain('email');
      expect(STEP_FIELDS.contact).toContain('email');
    }
  });

  it('rejects a malformed idempotency key', () => {
    expect(
      tradeFormSchema.safeParse(valid({ requestUuid: 'not-a-uuid' })).success,
    ).toBe(false);
  });

  it('normalises a country code to upper case', () => {
    const result = tradeFormSchema.safeParse(valid({ destinationCountry: 'sn' }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.destinationCountry).toBe('SN');
    }
  });

  it('rejects a country code that is not two letters', () => {
    expect(
      tradeFormSchema.safeParse(valid({ destinationCountry: 'SEN' })).success,
    ).toBe(false);
  });

  it('turns an empty optional field into undefined rather than an empty string', () => {
    const result = tradeFormSchema.safeParse(valid({ company: '   ' }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.company).toBeUndefined();
    }
  });

  it('bounds free text', () => {
    expect(
      tradeFormSchema.safeParse(valid({ description: 'x'.repeat(10_001) })).success,
    ).toBe(false);
  });

  it('rejects a malformed email', () => {
    expect(tradeFormSchema.safeParse(valid({ email: 'aminata@' })).success).toBe(
      false,
    );
  });
});

describe('isBotSubmission', () => {
  it('flags a filled honeypot', () => {
    const parsed = tradeFormSchema.parse(valid({ website: 'http://spam.example' }));
    expect(isBotSubmission(parsed)).toBe(true);
  });

  it('does not flag an empty honeypot', () => {
    const parsed = tradeFormSchema.parse(valid());
    expect(isBotSubmission(parsed)).toBe(false);
  });
});

describe('toTradeInput', () => {
  it('drops the honeypot and the idempotency key', () => {
    const parsed = tradeFormSchema.parse(
      valid({ website: 'http://spam.example' }),
    );
    const input = toTradeInput(parsed);
    const serialised = JSON.stringify(input);

    expect(serialised).not.toContain('spam.example');
    expect(serialised).not.toContain(UUID);
  });

  it('nests the contact to match the API contract', () => {
    const parsed = tradeFormSchema.parse(
      valid({ company: 'Diallo & Fils', phone: '+221771234567' }),
    );
    const input = toTradeInput(parsed);

    expect(input.contact.name).toBe('Aminata Diallo');
    expect(input.contact.company).toBe('Diallo & Fils');
    expect(input.contact.phone).toBe('+221771234567');
  });

  it('omits absent optional keys rather than sending empty strings', () => {
    const parsed = tradeFormSchema.parse(valid());
    const input = toTradeInput(parsed);

    expect('description' in input).toBe(false);
    expect('originCountry' in input).toBe(false);
    expect('company' in input.contact).toBe(false);
  });

  it('carries no internal commercial field', () => {
    // The real guarantee is structural — the input type has no such key — but a leak
    // introduced by a later edit should fail here rather than in production.
    const parsed = tradeFormSchema.parse(valid());
    const serialised = JSON.stringify(toTradeInput(parsed)).toLowerCase();

    for (const forbidden of [
      'margin',
      'cost',
      'internal',
      'supplier',
      'commission',
      'purchase_price',
      'approval',
      'negotiation',
    ]) {
      expect(serialised, `'${forbidden}' reached the gateway payload`).not.toContain(
        forbidden,
      );
    }
  });
});

describe('findForbiddenField', () => {
  it('finds an internal field at the top level', () => {
    expect(findForbiddenField({ ...valid(), internal_margin: 9999 })).toBe(
      'internal_margin',
    );
  });

  it('finds one smuggled inside a nested object', () => {
    expect(
      findForbiddenField({ ...valid(), contact: { supplier_score: 5 } }),
    ).toBe('supplier_score');
  });

  it('finds one inside an array', () => {
    expect(findForbiddenField({ lines: [{ purchase_unit_price: 12 }] })).toBe(
      'purchase_unit_price',
    );
  });

  it('catches the camelCase spelling too', () => {
    // A JavaScript integrator will write camelCase without thinking about it.
    expect(findForbiddenField({ netMargin: 400 })).toBe('netMargin');
  });

  it('returns null for a legitimate body', () => {
    expect(findForbiddenField(valid())).toBeNull();
  });

  it('does not choke on a deeply nested or cyclic-looking body', () => {
    let node: Record<string, unknown> = { leaf: true };
    for (let i = 0; i < 40; i += 1) node = { nested: node };
    expect(() => findForbiddenField(node)).not.toThrow();
  });

  it('covers every field the model calls internal', () => {
    for (const field of [
      'internal_cost',
      'purchase_margin',
      'internal_margin',
      'supplier_score',
      'internal_commission',
      'negotiation_notes',
      'approval_status',
    ]) {
      expect(
        FORBIDDEN_PUBLIC_FIELDS as ReadonlyArray<string>,
        `'${field}' would be silently stripped instead of refused`,
      ).toContain(field);
    }
  });

  it('refuses the workflow fields a caller must not set', () => {
    expect(findForbiddenField({ state: 'contracted' })).toBe('state');
    expect(findForbiddenField({ responsible_id: 3 })).toBe('responsible_id');
  });
});

describe('the step definition', () => {
  it('has six steps', () => {
    expect(TRADE_STEPS).toHaveLength(6);
  });

  it('labels every step', () => {
    for (const step of TRADE_STEPS) {
      expect(STEP_LABELS[step]).toBeTruthy();
    }
  });

  it('assigns every validated field to exactly one step', () => {
    const assigned = TRADE_STEPS.flatMap((step) => STEP_FIELDS[step]);
    expect(new Set(assigned).size).toBe(assigned.length);
  });

  it('covers every user-facing field the schema validates', () => {
    // Fields excluded on purpose: the idempotency key and the honeypot are not shown,
    // and the source URLs are filled by the browser.
    const notShown = new Set([
      'requestUuid',
      'website',
      'sourceUrl',
      'referrerUrl',
    ]);
    const assigned = new Set(TRADE_STEPS.flatMap((step) => STEP_FIELDS[step]));
    const parsed = tradeFormSchema.parse(valid()) as TradeFormData;

    for (const key of Object.keys(parsed)) {
      if (notShown.has(key)) continue;
      expect(assigned.has(key), `'${key}' belongs to no step`).toBe(true);
    }
  });

  it('puts the operation type first', () => {
    // It is the answer that determines what the rest of the conversation is about.
    expect(TRADE_STEPS[0]).toBe('operation');
    expect(STEP_FIELDS.operation).toContain('operationType');
  });

  it('leaves the review step with no fields of its own', () => {
    expect(STEP_FIELDS.review).toHaveLength(0);
  });
});
