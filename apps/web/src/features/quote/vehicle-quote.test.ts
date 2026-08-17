/**
 * Le devis véhicule, côté contrat public.
 *
 * Ce que ces tests défendent tient en une phrase : le mode de transport ne se
 * devine pas. Le reste — VIN, couleur, nombre de clés — se corrige après coup
 * sans conséquence. Un mode absent qui serait complété par un défaut produirait
 * une expédition maritime là où le client attendait un camion, et personne ne
 * s'en apercevrait avant la livraison.
 */

import { describe, expect, it } from 'vitest';

import { quoteRequestSchema, toQuoteInput } from './quote-schema';

const BASE = {
  serviceCode: 'freight_vehicle',
  lastName: 'Ba',
  email: 'client@exemple.invalid',
  originCity: 'Paris',
  destinationCity: 'Dakar',
  requestUuid: '3f1c2b7e-8a4d-4c1f-9b2e-6d5a7c8e9f01',
};

const VEHICULE = {
  vehicleMake: 'Toyota',
  vehicleModel: 'Hilux',
  vehicleYear: '2019',
  vehicleCategory: 'van' as const,
  vehicleCondition: 'running' as const,
  vehicleTransportMode: 'sea' as const,
};

describe('devis véhicule — schéma public', () => {
  it('accepte un véhicule maritime complet', () => {
    const parsed = quoteRequestSchema.parse({ ...BASE, ...VEHICULE });
    expect(parsed.vehicleTransportMode).toBe('sea');
    expect(parsed.vehicleCategory).toBe('van');
  });

  it('accepte un véhicule routier', () => {
    const parsed = quoteRequestSchema.parse({
      ...BASE, ...VEHICULE, vehicleTransportMode: 'road',
    });
    expect(parsed.vehicleTransportMode).toBe('road');
  });

  it('refuse un mode de transport inconnu', () => {
    expect(() =>
      quoteRequestSchema.parse({
        ...BASE, ...VEHICULE, vehicleTransportMode: 'teleportation',
      }),
    ).toThrow();
  });

  it('refuse une catégorie hors énumération', () => {
    expect(() =>
      quoteRequestSchema.parse({ ...BASE, ...VEHICULE, vehicleCategory: 'fusée' }),
    ).toThrow();
  });

  it('normalise le VIN en majuscules et sans espaces', () => {
    const parsed = quoteRequestSchema.parse({
      ...BASE, ...VEHICULE, vehicleVin: '  jt1234567890abcd  ',
    });
    expect(parsed.vehicleVin).toBe('JT1234567890ABCD');
  });

  it('accepte un VIN court mais plausible', () => {
    // Les véhicules d'avant 1981 n'ont pas de VIN de 17 caractères. Refuser un
    // dossier légitime pour cette raison coûte plus cher qu'accepter un numéro
    // atypique : le client abandonne, et personne ne sait pourquoi.
    const parsed = quoteRequestSchema.parse({
      ...BASE, ...VEHICULE, vehicleVin: 'ABC123',
    });
    expect(parsed.vehicleVin).toBe('ABC123');
  });

  it('refuse un VIN absurde ou dangereux', () => {
    for (const vin of ['AB', '<script>alert(1)</script>']) {
      expect(() =>
        quoteRequestSchema.parse({ ...BASE, ...VEHICULE, vehicleVin: vin }),
      ).toThrow();
    }
  });
});

describe('devis véhicule — entrée transmise à Odoo', () => {
  it('transmet le mode de transport au backend', () => {
    // Sans cette sérialisation, les champs existeraient dans le formulaire et
    // n'atteindraient jamais Odoo : le devis serait refusé en 422 sans que rien
    // n'indique pourquoi.
    const payload = toQuoteInput(quoteRequestSchema.parse({ ...BASE, ...VEHICULE }));
    expect(payload).toMatchObject({
      vehicleMake: 'Toyota',
      vehicleModel: 'Hilux',
      vehicleTransportMode: 'sea',
    });
  });

  it("n'envoie pas d'adresse fantôme quand l'enlèvement est décoché", () => {
    // Le cas réel : le client coche, saisit une adresse, puis décoche. Sans ce
    // nettoyage, l'exploitation recevrait une adresse d'enlèvement pour une
    // prestation qui n'a pas été commandée.
    const payload = toQuoteInput(
      quoteRequestSchema.parse({
        ...BASE, ...VEHICULE,
        vehiclePickupRequested: false,
        vehiclePickupAddress: '12 rue Résiduelle, Paris',
      }),
    );
    expect(payload).not.toHaveProperty('vehiclePickupAddress');
    expect(payload).not.toHaveProperty('vehiclePickupRequested');
  });

  it("transmet l'adresse quand l'enlèvement est demandé", () => {
    const payload = toQuoteInput(
      quoteRequestSchema.parse({
        ...BASE, ...VEHICULE,
        vehiclePickupRequested: true,
        vehiclePickupAddress: '12 rue Réelle, Paris',
      }),
    );
    expect(payload).toMatchObject({
      vehiclePickupRequested: true,
      vehiclePickupAddress: '12 rue Réelle, Paris',
    });
  });

  it('applique la même règle à la livraison', () => {
    const payload = toQuoteInput(
      quoteRequestSchema.parse({
        ...BASE, ...VEHICULE,
        vehicleDeliveryRequested: false,
        vehicleDeliveryAddress: 'Adresse fantôme',
      }),
    );
    expect(payload).not.toHaveProperty('vehicleDeliveryAddress');
  });

  it("n'invente jamais de mode de transport", () => {
    // Le champ est facultatif dans le schéma — c'est le serveur qui l'exige
    // pour ce service. Ce qui compte ici : rien ne le remplit à la place du
    // client.
    const payload = toQuoteInput(
      quoteRequestSchema.parse({
        ...BASE,
        vehicleMake: 'Toyota',
        vehicleModel: 'Hilux',
      }),
    );
    expect(payload).not.toHaveProperty('vehicleTransportMode');
  });
});
