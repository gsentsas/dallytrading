import { describe, expect, it } from 'vitest';
import {
  QUOTE_SERVICES,
  findService,
  stepsForService,
  STEP_LABELS,
} from './services';

describe('QUOTE_SERVICES', () => {
  it('uses codes in the format Odoo enforces', () => {
    // dally.service.type constrains codes to lowercase, digits and underscore. A
    // divergence here would be rejected at submission with a 422.
    for (const service of QUOTE_SERVICES) {
      expect(service.code).toMatch(/^[a-z0-9_]+$/);
    }
  });

  it('has unique codes', () => {
    const codes = QUOTE_SERVICES.map((service) => service.code);
    expect(new Set(codes).size).toBe(codes.length);
  });

  it('covers the codes seeded by dally_core', () => {
    // Kept in step with dally_core/data/dally_service_type_data.xml. A missing
    // entry means a service exists in Odoo but cannot be requested from the site.
    const expected = [
      'import_export', 'freight_sea', 'freight_air', 'freight_vehicle',
      'freight_groupage', 'logistics', 'sourcing', 'trade', 'agrobusiness',
      'ecommerce', 'business_solutions', 'other',
    ];
    const codes = QUOTE_SERVICES.map((service) => service.code);
    for (const code of expected) {
      expect(codes).toContain(code);
    }
  });

  it('gives every service a label and a description', () => {
    for (const service of QUOTE_SERVICES) {
      expect(service.label.length).toBeGreaterThan(2);
      expect(service.description.length).toBeGreaterThan(10);
    }
  });
});

describe('findService', () => {
  it('resolves a known code', () => {
    expect(findService('freight_sea')?.label).toBe('Fret maritime');
  });

  it('returns undefined for an unknown code', () => {
    expect(findService('nope')).toBeUndefined();
    expect(findService('')).toBeUndefined();
  });
});

describe('stepsForService', () => {
  it('shows only service, contact and confirm before a choice is made', () => {
    expect(stepsForService(null)).toEqual(['service', 'contact', 'confirm']);
  });

  it('adds route and cargo for a freight service', () => {
    expect(stepsForService('freight_sea')).toEqual([
      'service', 'route', 'cargo', 'contact', 'confirm',
    ]);
  });

  it('omits the route step for sourcing', () => {
    // Asking a sourcing prospect for a port of loading is how a form gets
    // abandoned (§79).
    const steps = stepsForService('sourcing');
    expect(steps).not.toContain('route');
    expect(steps).toContain('cargo');
  });

  it('omits both route and cargo for e-commerce', () => {
    expect(stepsForService('ecommerce')).toEqual([
      'service', 'contact', 'confirm',
    ]);
  });

  it('always starts with service and ends with confirm', () => {
    for (const service of QUOTE_SERVICES) {
      const steps = stepsForService(service.code);
      expect(steps[0]).toBe('service');
      expect(steps[steps.length - 1]).toBe('confirm');
    }
  });

  it('never repeats a step', () => {
    for (const service of QUOTE_SERVICES) {
      const steps = stepsForService(service.code);
      expect(new Set(steps).size).toBe(steps.length);
    }
  });

  it('falls back to the minimal path for an unknown code', () => {
    expect(stepsForService('does_not_exist')).toEqual([
      'service', 'contact', 'confirm',
    ]);
  });

  it('labels every step it can produce', () => {
    for (const service of QUOTE_SERVICES) {
      for (const step of stepsForService(service.code)) {
        expect(STEP_LABELS[step]).toBeTruthy();
      }
    }
  });
});
