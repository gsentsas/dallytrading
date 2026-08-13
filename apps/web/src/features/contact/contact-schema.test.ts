import { describe, expect, it } from 'vitest';
import {
  CONTACT_SUBJECTS,
  contactFormSchema,
  isBotSubmission,
  subjectLabel,
  toLeadInput,
} from './contact-schema';

const VALID_UUID = '3f2504e0-4f89-41d3-9a0c-0305e82c3301';

function payload(overrides: Record<string, unknown> = {}) {
  return {
    requestUuid: VALID_UUID,
    lastName: 'Ndiaye',
    email: 'aliou@example.com',
    message: 'Je souhaite un renseignement sur vos services de fret maritime.',
    ...overrides,
  };
}

describe('contactFormSchema', () => {
  it('accepts a minimal valid message', () => {
    expect(contactFormSchema.safeParse(payload()).success).toBe(true);
  });

  it('requires a name', () => {
    expect(contactFormSchema.safeParse(payload({ lastName: '  ' })).success)
      .toBe(false);
  });

  it('requires a way to reply', () => {
    expect(contactFormSchema.safeParse(payload({ email: '', phone: '' })).success)
      .toBe(false);
    expect(
      contactFormSchema.safeParse(payload({ email: '', phone: '+221 77 123 45 67' }))
        .success,
    ).toBe(true);
  });

  it('requires a message with some substance', () => {
    // A three-character message is not a request; it is someone testing the form.
    expect(contactFormSchema.safeParse(payload({ message: 'ok' })).success)
      .toBe(false);
    expect(contactFormSchema.safeParse(payload({ message: '' })).success)
      .toBe(false);
  });

  it('rejects a malformed email', () => {
    for (const bad of ['nope', 'a@b', '@example.com', 'a b@c.com']) {
      expect(contactFormSchema.safeParse(payload({ email: bad })).success)
        .toBe(false);
    }
  });

  it('defaults the subject to a general question', () => {
    const result = contactFormSchema.safeParse(payload());
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.subject).toBe('other');
    }
  });

  it('accepts every offered subject', () => {
    for (const subject of CONTACT_SUBJECTS) {
      expect(
        contactFormSchema.safeParse(payload({ subject: subject.value })).success,
      ).toBe(true);
    }
  });

  it('rejects a subject outside the offered list', () => {
    // Odoo would reject an unknown code anyway; failing here gives a usable message
    // instead of a 422 round trip.
    expect(contactFormSchema.safeParse(payload({ subject: 'invented' })).success)
      .toBe(false);
  });

  it('ignores fields it does not declare', () => {
    const result = contactFormSchema.safeParse(
      payload({ userId: 1, state: 'won', internalNotes: 'x' }),
    );
    expect(result.success).toBe(true);
    if (result.success) {
      expect('userId' in result.data).toBe(false);
      expect('internalNotes' in result.data).toBe(false);
    }
  });
});

describe('isBotSubmission', () => {
  it('flags a filled honeypot', () => {
    const result = contactFormSchema.safeParse(payload({ website: 'http://spam' }));
    expect(result.success && isBotSubmission(result.data)).toBe(true);
  });

  it('does not flag an absent honeypot', () => {
    const result = contactFormSchema.safeParse(payload());
    expect(result.success && isBotSubmission(result.data)).toBe(false);
  });
});

describe('subjectLabel', () => {
  it('resolves a known subject', () => {
    expect(subjectLabel('freight_sea')).toBe('Fret maritime');
  });

  it('falls back for an unknown subject', () => {
    expect(subjectLabel('inexistant')).toBe('Question générale');
  });
});

describe('toLeadInput', () => {
  it('maps the subject onto the lead service', () => {
    // This is what lets the sales team route a message without reading it first.
    const result = contactFormSchema.safeParse(payload({ subject: 'freight_air' }));
    if (!result.success) throw new Error('fixture should parse');
    expect(toLeadInput(result.data).serviceCode).toBe('freight_air');
  });

  it('carries the message through', () => {
    const result = contactFormSchema.safeParse(payload());
    if (!result.success) throw new Error('fixture should parse');
    expect(toLeadInput(result.data).message).toContain('fret maritime');
  });

  it('drops the honeypot and the idempotency key', () => {
    const result = contactFormSchema.safeParse(payload({ website: 'spam' }));
    if (!result.success) throw new Error('fixture should parse');
    const input = toLeadInput(result.data) as unknown as Record<string, unknown>;
    expect('website' in input).toBe(false);
    expect('requestUuid' in input).toBe(false);
    expect('subject' in input).toBe(false);
  });

  it('does not forward the referrer into a UTM field', () => {
    // utmSource is what the CRM groups by for attribution. Putting a referrer URL
    // there would corrupt those reports with values that are not campaign sources.
    const result = contactFormSchema.safeParse(
      payload({ referrerUrl: 'https://www.google.com/' }),
    );
    if (!result.success) throw new Error('fixture should parse');
    const input = toLeadInput(result.data) as unknown as Record<string, unknown>;
    expect(input.utmSource).toBeUndefined();
  });

  it('omits absent optional fields rather than sending empty strings', () => {
    const result = contactFormSchema.safeParse(payload());
    if (!result.success) throw new Error('fixture should parse');
    const input = toLeadInput(result.data) as unknown as Record<string, unknown>;
    expect('companyName' in input).toBe(false);
    expect('whatsapp' in input).toBe(false);
  });
});
