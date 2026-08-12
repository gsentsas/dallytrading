import { describe, expect, it } from 'vitest';
import type { ServiceType } from '@/services/odoo/types';
import {
  isBotSubmission,
  quoteRequestSchema,
  stepsForService,
  toQuoteInput,
  validateServiceRequirements,
  STEP_LABELS,
} from './quote-schema';

const VALID_UUID = '3f2504e0-4f89-41d3-9a0c-0305e82c3301';

/** Build a service with all flags off, then switch on what a case needs. */
function service(overrides: Partial<ServiceType> = {}): ServiceType {
  return {
    code: 'freight_sea',
    name: 'Fret maritime',
    description: '',
    active: true,
    sort_order: 10,
    requires_origin: false,
    requires_destination: false,
    requires_weight: false,
    requires_volume: false,
    requires_vehicle: false,
    requires_budget: false,
    requires_goods: false,
    ...overrides,
  };
}

function payload(overrides: Record<string, unknown> = {}) {
  return {
    requestUuid: VALID_UUID,
    serviceCode: 'freight_sea',
    lastName: 'Ndiaye',
    email: 'aliou@example.com',
    ...overrides,
  };
}

describe('quoteRequestSchema', () => {
  it('accepts a minimal valid submission', () => {
    expect(quoteRequestSchema.safeParse(payload()).success).toBe(true);
  });

  it('requires a valid UUID', () => {
    for (const value of ['', 'nope', VALID_UUID.slice(0, -1)]) {
      expect(quoteRequestSchema.safeParse(payload({ requestUuid: value })).success)
        .toBe(false);
    }
  });

  it('requires a service code in the format Odoo enforces', () => {
    expect(quoteRequestSchema.safeParse(payload({ serviceCode: 'Fret-Sea' }))
      .success).toBe(false);
    expect(quoteRequestSchema.safeParse(payload({ serviceCode: 'freight_sea' }))
      .success).toBe(true);
  });

  it('requires a name and a contact channel', () => {
    expect(quoteRequestSchema.safeParse(payload({ lastName: '   ' })).success)
      .toBe(false);
    expect(quoteRequestSchema.safeParse(payload({ email: '', phone: '' })).success)
      .toBe(false);
    expect(quoteRequestSchema.safeParse(payload({ email: '', phone: '771234567' }))
      .success).toBe(true);
  });

  it('parses numeric fields sent as strings', () => {
    const result = quoteRequestSchema.safeParse(
      payload({ weightKg: '1250.5', volumeCbm: '3.2', packagesCount: '12' }),
    );
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.weightKg).toBe(1250.5);
      expect(result.data.volumeCbm).toBe(3.2);
      expect(result.data.packagesCount).toBe(12);
    }
  });

  it('treats an empty numeric field as absent, not as zero', () => {
    // "Not known yet" and "weighs nothing" are different statements, and an
    // operator needs to tell them apart.
    const result = quoteRequestSchema.safeParse(payload({ weightKg: '' }));
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.weightKg).toBeUndefined();
    }
  });

  it('rejects negative and absurd numbers', () => {
    expect(quoteRequestSchema.safeParse(payload({ weightKg: '-5' })).success)
      .toBe(false);
    expect(quoteRequestSchema.safeParse(payload({ weightKg: '99999999999' }))
      .success).toBe(false);
    expect(quoteRequestSchema.safeParse(payload({ volumeCbm: 'beaucoup' }))
      .success).toBe(false);
  });

  it('normalises country codes', () => {
    const result = quoteRequestSchema.safeParse(
      payload({ originCountryCode: ' fr ', destinationCountryCode: 'sn' }),
    );
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.originCountryCode).toBe('FR');
      expect(result.data.destinationCountryCode).toBe('SN');
    }
  });

  it('ignores fields it does not declare', () => {
    const result = quoteRequestSchema.safeParse(
      payload({ state: 'won', userId: 1, internalNotes: 'x' }),
    );
    expect(result.success).toBe(true);
    if (result.success) {
      expect('state' in result.data).toBe(false);
      expect('userId' in result.data).toBe(false);
      expect('internalNotes' in result.data).toBe(false);
    }
  });
});

describe('isBotSubmission', () => {
  it('flags a filled honeypot', () => {
    const result = quoteRequestSchema.safeParse(payload({ website: 'http://spam' }));
    expect(result.success && isBotSubmission(result.data)).toBe(true);
  });

  it('does not flag an absent honeypot', () => {
    const result = quoteRequestSchema.safeParse(payload());
    expect(result.success && isBotSubmission(result.data)).toBe(false);
  });
});

describe('validateServiceRequirements', () => {
  function parsed(overrides: Record<string, unknown> = {}) {
    const result = quoteRequestSchema.safeParse(payload(overrides));
    if (!result.success) throw new Error('fixture should parse');
    return result.data;
  }

  it('requires an origin when the service does', () => {
    const errors = validateServiceRequirements(
      parsed(), service({ requires_origin: true }),
    );
    expect(errors.originCity).toBeTruthy();
  });

  it('accepts a country code alone as an origin', () => {
    const errors = validateServiceRequirements(
      parsed({ originCountryCode: 'FR' }), service({ requires_origin: true }),
    );
    expect(errors.originCity).toBeUndefined();
  });

  it('requires a destination when the service does', () => {
    const errors = validateServiceRequirements(
      parsed(), service({ requires_destination: true }),
    );
    expect(errors.destinationCity).toBeTruthy();
  });

  it('requires nothing for a service with no route', () => {
    // Asking a sourcing prospect for a port of loading is how a form gets
    // abandoned.
    expect(
      validateServiceRequirements(parsed(), service({ requires_budget: true })),
    ).toEqual({});
  });

  it('does not require weight, volume or budget', () => {
    // Genuinely often unknown at enquiry time; refusing the request would turn
    // away real business.
    const errors = validateServiceRequirements(
      parsed({ originCity: 'Le Havre', destinationCity: 'Dakar' }),
      service({
        requires_origin: true, requires_destination: true,
        requires_weight: true, requires_volume: true, requires_budget: true,
      }),
    );
    expect(errors).toEqual({});
  });

  it('reports an unknown service', () => {
    expect(validateServiceRequirements(parsed(), undefined).serviceCode)
      .toBeTruthy();
  });
});

describe('stepsForService', () => {
  it('shows a minimal path before a service is chosen', () => {
    expect(stepsForService(undefined)).toEqual(['service', 'contact', 'confirm']);
  });

  it('adds a route step when origin or destination is needed', () => {
    expect(stepsForService(service({ requires_origin: true })))
      .toContain('route');
    expect(stepsForService(service({ requires_destination: true })))
      .toContain('route');
  });

  it('builds the air freight path: route then cargo', () => {
    expect(
      stepsForService(service({
        requires_origin: true, requires_destination: true,
        requires_weight: true, requires_goods: true,
      })),
    ).toEqual(['service', 'route', 'cargo', 'contact', 'confirm']);
  });

  it('builds the vehicle path: vehicle instead of cargo', () => {
    const steps = stepsForService(service({
      requires_origin: true, requires_destination: true, requires_vehicle: true,
    }));
    expect(steps).toContain('vehicle');
    expect(steps).not.toContain('cargo');
  });

  it('builds the sourcing path: cargo and budget, no route', () => {
    const steps = stepsForService(service({
      requires_goods: true, requires_budget: true,
    }));
    expect(steps).toEqual(['service', 'cargo', 'commercial', 'contact', 'confirm']);
  });

  it('builds a simple path for a service needing nothing', () => {
    expect(stepsForService(service())).toEqual(['service', 'contact', 'confirm']);
  });

  it('never repeats a step and always starts and ends the same way', () => {
    const combinations: Array<Partial<ServiceType>> = [
      {}, { requires_origin: true }, { requires_destination: true },
      { requires_weight: true }, { requires_volume: true },
      { requires_vehicle: true }, { requires_budget: true },
      { requires_goods: true },
      { requires_origin: true, requires_vehicle: true, requires_budget: true },
      {
        requires_origin: true, requires_destination: true, requires_weight: true,
        requires_volume: true, requires_goods: true, requires_budget: true,
      },
    ];
    for (const overrides of combinations) {
      const steps = stepsForService(service(overrides));
      expect(new Set(steps).size).toBe(steps.length);
      expect(steps[0]).toBe('service');
      expect(steps[steps.length - 1]).toBe('confirm');
      for (const step of steps) {
        expect(STEP_LABELS[step]).toBeTruthy();
      }
    }
  });

  it('derives steps only from flags, with no per-service special case', () => {
    // Two services with different codes but identical flags must produce
    // identical steps — that is what "Odoo is the source of truth" means here.
    const a = stepsForService(service({ code: 'freight_air', requires_weight: true }));
    const b = stepsForService(service({ code: 'agrobusiness', requires_weight: true }));
    expect(a).toEqual(b);
  });
});

describe('toQuoteInput', () => {
  it('maps structured fields rather than folding them into a message', () => {
    const result = quoteRequestSchema.safeParse(payload({
      originCity: 'Le Havre', destinationCity: 'Dakar',
      goodsDescription: 'Pièces auto', quantity: '3 palettes',
      weightKg: '750', volumeCbm: '5.4', packagesCount: '3',
      budget: '2M FCFA',
    }));
    if (!result.success) throw new Error('fixture should parse');

    const input = toQuoteInput(result.data);
    expect(input).toMatchObject({
      serviceCode: 'freight_sea',
      originCity: 'Le Havre',
      destinationCity: 'Dakar',
      goodsDescription: 'Pièces auto',
      quantity: '3 palettes',
      weightKg: 750,
      volumeCbm: 5.4,
      packagesCount: 3,
      budget: '2M FCFA',
    });
  });

  it('drops the honeypot and the idempotency key', () => {
    const result = quoteRequestSchema.safeParse(payload({ website: 'spam' }));
    if (!result.success) throw new Error('fixture should parse');

    const input = toQuoteInput(result.data) as unknown as Record<string, unknown>;
    expect('website' in input).toBe(false);
    expect('requestUuid' in input).toBe(false);
  });

  it('omits absent fields rather than sending empty values', () => {
    const result = quoteRequestSchema.safeParse(payload());
    if (!result.success) throw new Error('fixture should parse');

    const input = toQuoteInput(result.data) as unknown as Record<string, unknown>;
    expect('weightKg' in input).toBe(false);
    expect('vehicleMake' in input).toBe(false);
    expect('originCity' in input).toBe(false);
  });
});
