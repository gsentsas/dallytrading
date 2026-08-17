/**
 * Le devis groupage, côté contrat public et portail.
 *
 * Un seul enjeu : le mode physique ne se devine pas. Le poids taxable se
 * calcule à 167 kg/m³ en aérien contre 1000 en maritime — une consolidation
 * aérienne prise pour du maritime serait facturée six fois trop cher sur du
 * fret léger et volumineux.
 */

import { describe, expect, it } from 'vitest';

import { quoteRequestSchema, toQuoteInput } from './quote-schema';
import {
  portalGroupageSchema,
  portalQuoteDetailSchema,
  portalShipmentDetailSchema,
} from '@/lib/portal/dto';

const BASE = {
  serviceCode: 'freight_groupage',
  lastName: 'Ba',
  email: 'client@exemple.invalid',
  originCity: 'Dakar',
  destinationCity: 'Paris',
  requestUuid: '3f1c2b7e-8a4d-4c1f-9b2e-6d5a7c8e9f01',
  goodsDescription: 'Textile',
};

describe('formulaire public — groupage', () => {
  it('accepte un groupage maritime', () => {
    const parsed = quoteRequestSchema.parse({ ...BASE, groupageTransportMode: 'sea' });
    expect(parsed.groupageTransportMode).toBe('sea');
  });

  it('accepte un groupage aérien', () => {
    const parsed = quoteRequestSchema.parse({ ...BASE, groupageTransportMode: 'air' });
    expect(parsed.groupageTransportMode).toBe('air');
  });

  it('refuse un mode inconnu', () => {
    expect(() =>
      quoteRequestSchema.parse({ ...BASE, groupageTransportMode: 'teleportation' }),
    ).toThrow();
  });

  it("refuse le mode historique « groupage » comme mode de transport", () => {
    // Le client ne doit jamais pouvoir renvoyer le service en guise de mode :
    // c'est exactement la confusion que le champ existe pour empêcher.
    expect(() =>
      quoteRequestSchema.parse({ ...BASE, groupageTransportMode: 'groupage' }),
    ).toThrow();
  });

  it('transmet le mode au backend', () => {
    const payload = toQuoteInput(
      quoteRequestSchema.parse({ ...BASE, groupageTransportMode: 'air' }),
    );
    expect(payload).toMatchObject({ groupageTransportMode: 'air' });
  });

  it("n'invente aucun mode quand le client n'en donne pas", () => {
    // Le champ est facultatif dans le schéma : c'est le serveur qui l'exige
    // pour ce service. Ce qui compte ici, c'est que rien ne le remplisse.
    const payload = toQuoteInput(quoteRequestSchema.parse(BASE));
    expect(payload).not.toHaveProperty('groupageTransportMode');
  });

  it('laisse les autres services intacts', () => {
    const parsed = quoteRequestSchema.parse({ ...BASE, serviceCode: 'freight_sea' });
    expect(parsed.groupageTransportMode).toBeUndefined();
  });
});

// ─────────────────────────────────────────────────────────────────────────

const DEVIS = {
  reference: 'DT-2026-1', service: 'freight_groupage', status: 'quoted',
  createdOn: '2026-08-17', origin: 'Dakar', destination: 'Paris',
  goodsDescription: null, quantity: null, canDecide: true,
  customerDecisionAt: null,
};

const EXPEDITION = {
  reference: 'DT-SHP-1', transportMode: 'air', transportModeLabel: 'Air Freight',
  origin: 'Dakar', destination: 'Paris', status: 'draft', statusLabel: 'Draft',
  departureDate: null, estimatedArrival: null, actualArrival: null,
  lastUpdate: null, carrierTrackingNumber: null, containerNumber: null,
  goodsDescription: null, packagesCount: 0,
  timeline: [], packages: [], documents: [],
};

describe('contrat portail — groupage', () => {
  it('accepte un devis groupage maritime', () => {
    const parsed = portalQuoteDetailSchema.parse({
      ...DEVIS,
      groupage: { transportMode: 'sea', transportModeLabel: 'Groupage maritime' },
    });
    expect(parsed.groupage?.transportModeLabel).toBe('Groupage maritime');
  });

  it('accepte un devis sans groupage — clé absente, pas nulle', () => {
    expect(portalQuoteDetailSchema.parse(DEVIS).groupage).toBeUndefined();
  });

  it('accepte une expédition groupée aérienne portant les deux notions', () => {
    // Le point du contrat : « Groupage » et « Aérien » coexistent. Les fondre
    // ferait disparaître celle qui décide du poids taxable.
    const parsed = portalShipmentDetailSchema.parse({
      ...EXPEDITION,
      shipmentType: { code: 'groupage', label: 'Groupage' },
    });
    expect(parsed.transportMode).toBe('air');
    expect(parsed.shipmentType?.label).toBe('Groupage');
  });

  it('accepte une expédition historique sans type d’envoi', () => {
    expect(() => portalShipmentDetailSchema.parse(EXPEDITION)).not.toThrow();
  });

  it.each(['internalRate', 'supplierCost', 'tk_shipment_id'])(
    'refuse %s dans le bloc groupage',
    (champ) => {
      expect(() =>
        portalGroupageSchema.parse({
          transportMode: 'sea', transportModeLabel: 'Groupage maritime',
          [champ]: 'fuite',
        }),
      ).toThrow();
    },
  );
});
