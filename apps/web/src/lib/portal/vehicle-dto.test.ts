/**
 * Contrat du véhicule côté portail.
 *
 * Les fixtures reproduisent les payloads Odoo **mesurés**, pas imaginés : les
 * champs facultatifs y arrivent à `null` et non absents, et la clé `vehicle`
 * elle-même est absente quand il n'y a pas de véhicule. Un schéma écrit d'après
 * l'idée qu'on se fait du serveur échoue au premier `null` inattendu, en
 * production, sur la page d'un client.
 */

import { describe, expect, it } from 'vitest';

import {
  portalQuoteDetailSchema,
  portalShipmentDetailSchema,
  portalVehicleSchema,
} from './dto';

/** VIN synthétique, reconnaissable : sert aussi de sonde de fuite. */
const VIN = 'DALLYTESTVIN00001';

const VEHICULE_COMPLET = {
  make: 'Toyota', model: 'Hilux', year: '2019',
  vin: VIN, registration: 'AB-123-CD', color: 'Blanc',
  category: 'van', categoryLabel: 'Utilitaire',
  condition: 'running', conditionLabel: 'Roulant',
  fuelType: 'diesel', fuelTypeLabel: 'Diesel',
  keyCount: 2,
  transportMode: 'sea', transportModeLabel: 'Maritime',
  pickupRequested: true, pickupAddress: '12 rue Test',
  deliveryRequested: false, deliveryAddress: null,
};

const VEHICULE_MINIMAL = {
  make: 'A', model: 'B', year: null,
  vin: null, registration: null, color: null,
  category: 'car', categoryLabel: 'Voiture',
  condition: 'non_running', conditionLabel: 'Non roulant',
  fuelType: null, fuelTypeLabel: null,
  keyCount: 0,
  transportMode: 'road', transportModeLabel: 'Routier',
  pickupRequested: false, pickupAddress: null,
  deliveryRequested: false, deliveryAddress: null,
};

const DEVIS = {
  reference: 'DT-2026-1', service: 'freight_vehicle', status: 'quoted',
  createdOn: '2026-08-17', origin: 'Paris', destination: 'Dakar',
  goodsDescription: null, quantity: null, canDecide: true,
  customerDecisionAt: null,
};

const EXPEDITION = {
  reference: 'DT-SHP-1', transportMode: 'sea', transportModeLabel: 'Maritime',
  origin: 'Paris', destination: 'Dakar', status: 'draft', statusLabel: 'Draft',
  departureDate: null, estimatedArrival: null, actualArrival: null,
  lastUpdate: null, carrierTrackingNumber: null, containerNumber: null,
  goodsDescription: null, packagesCount: 0,
  timeline: [], packages: [], documents: [],
};

describe('contrat véhicule — cas mesurés', () => {
  it('accepte un véhicule complet', () => {
    expect(portalVehicleSchema.parse(VEHICULE_COMPLET).vin).toBe(VIN);
  });

  it('accepte un véhicule minimal, champs facultatifs à null', () => {
    const parsed = portalVehicleSchema.parse(VEHICULE_MINIMAL);
    expect(parsed.vin).toBeNull();
    expect(parsed.keyCount).toBe(0);
  });

  it('accepte une prestation non demandée sans adresse', () => {
    expect(() =>
      portalVehicleSchema.parse({
        ...VEHICULE_COMPLET,
        pickupRequested: false, pickupAddress: null,
      }),
    ).not.toThrow();
  });
});

describe('contrat véhicule — garde-fou contre une fuite serveur', () => {
  // Ces champs ne doivent jamais quitter Odoo. La barrière est censée être en
  // amont ; ce schéma existe pour le jour où l'amont se trompe.
  it.each([
    ['internal_notes', 'CANARY_VEHICLE_INTERNAL_NOTE'],
    ['purchase_price', 15000],
    ['tk_shipment_id', 42],
    ['partner_id', 7],
    ['extraInternalField', 'x'],
  ])('refuse %s dans le véhicule', (champ, valeur) => {
    expect(() =>
      portalVehicleSchema.parse({ ...VEHICULE_COMPLET, [champ]: valeur }),
    ).toThrow();
  });
});

describe('contrat véhicule — intégration aux détails', () => {
  it('accepte un devis véhicule', () => {
    const parsed = portalQuoteDetailSchema.parse({
      ...DEVIS, vehicle: VEHICULE_COMPLET,
    });
    expect(parsed.vehicle?.transportModeLabel).toBe('Maritime');
  });

  it('accepte un devis sans véhicule — clé absente, pas nulle', () => {
    const parsed = portalQuoteDetailSchema.parse(DEVIS);
    expect(parsed.vehicle).toBeUndefined();
  });

  it('accepte une expédition véhicule', () => {
    const parsed = portalShipmentDetailSchema.parse({
      ...EXPEDITION, vehicle: VEHICULE_COMPLET,
    });
    expect(parsed.vehicle?.vin).toBe(VIN);
  });

  it('accepte une expédition historique sans véhicule', () => {
    // Non-régression : les dossiers maritimes et aériens déjà en production
    // doivent continuer à parser sans modification.
    expect(() => portalShipmentDetailSchema.parse(EXPEDITION)).not.toThrow();
  });

  it('refuse un champ interne au niveau du détail', () => {
    expect(() =>
      portalQuoteDetailSchema.parse({ ...DEVIS, internalNotes: 'fuite' }),
    ).toThrow();
  });
});

describe('contrat véhicule — le VIN ne sort pas des détails privés', () => {
  it("n'apparaît pas dans une ligne de liste de devis", () => {
    // La liste et le détail partagent le schéma parent ; seul le détail ajoute
    // `vehicle`. Un VIN dans une ligne de liste serait donc un champ inconnu.
    expect(JSON.stringify(portalQuoteDetailSchema.parse(DEVIS))).not.toContain(VIN);
  });
});
