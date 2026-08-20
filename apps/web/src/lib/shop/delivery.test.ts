import { describe, expect, it } from 'vitest';

import {
  deliveryMethodSchema,
  shippingAddressSchema,
} from './delivery';

describe('méthodes de remise', () => {
  it('accepte une méthode publique strictement projetée', () => {
    const method = {
      code: 'dakar-express',
      name: 'Dakar express',
      kind: 'delivery' as const,
      requiresAddress: true,
      feePolicy: 'fixed' as const,
      feeAmount: 2500,
      currency: 'XOF',
      help: 'Livraison dans Dakar.',
    };
    expect(deliveryMethodSchema.parse(method)).toEqual(method);
  });

  it('refuse identifiants et champs internes', () => {
    expect(() => deliveryMethodSchema.parse({
      code: 'pickup',
      name: 'Retrait',
      kind: 'pickup',
      requiresAddress: false,
      feePolicy: 'free',
      feeAmount: 0,
      currency: 'XOF',
      help: '',
      id: 42,
    })).toThrow();
  });
});

describe('adresse de livraison', () => {
  it('normalise les champs facultatifs vides en absence', () => {
    const parsed = shippingAddressSchema.parse({
      name: 'Dépôt Dakar',
      phone: '   ',
      street: '10 avenue du Port',
      street2: '',
      city: 'Dakar',
      zip: '',
      country_code: '',
    });

    expect(parsed.name).toBe('Dépôt Dakar');
    expect(parsed.phone).toBeUndefined();
    expect(parsed.street2).toBeUndefined();
    expect(parsed.zip).toBeUndefined();
    expect(parsed.country_code).toBeUndefined();
  });

  it('normalise le code pays en majuscules', () => {
    expect(shippingAddressSchema.parse({ country_code: 'sn' }).country_code).toBe('SN');
  });

  it('refuse une clé ou un montant non contractuel', () => {
    expect(() => shippingAddressSchema.parse({ street: 'Rue 1', fee: 1 })).toThrow();
    expect(() => shippingAddressSchema.parse({ street: 'Rue 1', partner_id: 3 })).toThrow();
  });
});
