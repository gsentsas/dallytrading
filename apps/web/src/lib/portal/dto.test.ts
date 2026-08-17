import { describe, expect, it } from 'vitest';

import {
  FORBIDDEN_KEYS,
  portalDashboardSchema,
  portalDocumentSchema,
  portalListSchema,
  portalProfileSchema,
  portalProfileUpdateSchema,
  portalQuoteDecisionSchema,
  portalQuoteSchema,
  portalShipmentDetailSchema,
  portalSourcingDetailSchema,
  portalTradeSchema,
} from './dto';

const quote = {
  reference: 'DT-2026-000001',
  service: 'import_export',
  status: 'new',
  createdOn: '2026-08-15',
  origin: 'Dakar',
  destination: 'Abidjan',
  goodsDescription: null,
  quantity: '12 cartons',
  canDecide: false,
  customerDecisionAt: null,
};

describe('schémas stricts', () => {
  it('accepte une projection Odoo conforme', () => {
    expect(portalQuoteSchema.parse(quote)).toEqual(quote);
  });

  it('REFUSE une clé inattendue au lieu de la retirer', () => {
    /*
     * L'assertion la plus importante du fichier.
     *
     * Un schéma qui « strippe » accepterait un payload contenant `margin` et le
     * retirerait en silence : la page s'afficherait, personne ne saurait qu'Odoo
     * a commencé à envoyer une marge, et le jour où un composant sérialiserait
     * l'objet brut la marge partirait. Refuser fait échouer la page — bruyant,
     * et c'est le but.
     */
    const result = portalQuoteSchema.safeParse({ ...quote, margin: 4200 });
    expect(result.success).toBe(false);
  });

  it.each(FORBIDDEN_KEYS)('refuse le champ interdit %s', (key) => {
    const result = portalQuoteSchema.safeParse({ ...quote, [key]: 'peu importe' });
    expect(result.success).toBe(false);
  });

  it('refuse un champ manquant', () => {
    const { reference: _removed, ...incomplete } = quote;
    expect(portalQuoteSchema.safeParse(incomplete).success).toBe(false);
  });

  it('refuse un type incorrect', () => {
    expect(portalQuoteSchema.safeParse({ ...quote, quantity: 12 }).success).toBe(false);
  });
});

describe('contrats métier', () => {
  it('le devis n’a aucune clé au-delà de la projection autorisée', () => {
    expect(Object.keys(portalQuoteSchema.parse(quote)).sort()).toEqual([
      'canDecide', 'createdOn', 'customerDecisionAt', 'destination',
      'goodsDescription', 'origin', 'quantity', 'reference', 'service', 'status',
    ]);
  });

  it('accepte uniquement les deux commandes de décision documentées', () => {
    expect(portalQuoteDecisionSchema.parse({ decision: 'accept' })).toEqual({
      decision: 'accept',
    });
    expect(portalQuoteDecisionSchema.parse({
      decision: 'reject', reason: '  Conditions non adaptées  ',
    })).toEqual({
      decision: 'reject', reason: 'Conditions non adaptées',
    });
  });

  it.each([
    { decision: 'maybe' },
    { decision: 'accept', reason: 'non' },
    { decision: 'accept', state: 'won' },
    { decision: 'reject', partner_id: 7 },
    { decision: 'reject', margin: 0 },
    { decision: 'reject', reason: 'x'.repeat(501) },
    { decision: 'reject', reason: '<b>non</b>' },
    { decision: 'reject', reason: 'ligne\nsuivante' },
  ])('refuse une décision ou une clé hors contrat : %j', (payload) => {
    expect(portalQuoteDecisionSchema.safeParse(payload).success).toBe(false);
  });

  it('l’opération de trading ne porte que le volet vente', () => {
    const trade = {
      reference: 'DT-TRD-1', subject: 'Objet', operationType: 'purchase_resale',
      operationTypeLabel: 'Achat-revente', status: 'draft', saleTotal: 1000,
      currency: 'XOF', origin: null, destination: null, expectedClose: null,
      createdOn: '2026-08-15',
    };
    const parsed = portalTradeSchema.parse(trade);
    expect(parsed).not.toHaveProperty('purchaseSubtotal');
    expect(parsed).not.toHaveProperty('margin');
    expect(parsed).not.toHaveProperty('supplierId');
    // `saleTotal` est bien là : c'est ce que le client doit.
    expect(parsed.saleTotal).toBe(1000);
  });

  it('le détail sourcing porte les propositions', () => {
    const detail = {
      reference: 'DT-SRC-1', status: 'sourcing', productName: 'Produit',
      productReference: 'REF-1', quantity: 10, unit: 'Units',
      createdOn: '2026-08-15',
      proposals: [{
        reference: 'DT-PRP-1', status: 'sent', productName: 'Produit',
        quantity: 10, unit: 'Units', unitPrice: 42, total: 420,
        currency: 'XOF', validUntil: null, estimatedDelivery: null,
        commercialTerms: null,
      }],
    };
    const parsed = portalSourcingDetailSchema.parse(detail);
    expect(parsed.proposals).toHaveLength(1);
    expect(parsed.proposals[0]).not.toHaveProperty('costBasis');
  });

  it('refuse une proposition portant une base de coût', () => {
    const detail = {
      reference: 'DT-SRC-1', status: 'sourcing', productName: null,
      productReference: null, quantity: 1, unit: null, createdOn: null,
      proposals: [{
        reference: 'DT-PRP-1', status: 'sent', productName: null,
        quantity: 1, unit: null, unitPrice: 1, total: 1, currency: null,
        validUntil: null, estimatedDelivery: null, commercialTerms: null,
        costBasis: 30,
      }],
    };
    expect(portalSourcingDetailSchema.safeParse(detail).success).toBe(false);
  });

  it('le détail expédition porte les colis et la timeline', () => {
    const detail = {
      reference: 'DT-SHP-1', transportMode: 'sea', transportModeLabel: 'Sea Freight',
      origin: 'Dakar', destination: 'Abidjan', status: 'in_transit',
      statusLabel: 'In Transit', departureDate: null, estimatedArrival: null,
      actualArrival: null, lastUpdate: null, carrierTrackingNumber: null,
      containerNumber: null, goodsDescription: null, packagesCount: 1,
      timeline: [{
        date: '2026-08-15', status: 'in_transit', statusLabel: 'In Transit',
        location: 'Dakar', description: null,
      }],
      packages: [{
        packageType: 'Crate', description: null, quantity: 4,
        totalWeightKg: 50, totalVolumeCbm: 1.2,
      }],
      documents: [{
        reference: 'DOC-7', name: 'connaissement.pdf',
        documentType: 'transport', documentTypeLabel: 'Document de transport',
        relatedTo: 'Expédition', relatedReference: 'DT-SHP-1',
        publishedOn: '2026-08-15',
      }],
    };
    const parsed = portalShipmentDetailSchema.parse(detail);
    expect(parsed.packages).toHaveLength(1);
    expect(parsed.timeline).toHaveLength(1);
    expect(parsed.documents).toHaveLength(1);
    // Un événement interne porterait `internalNote` : le schéma le refuserait.
    expect(parsed.timeline[0]).not.toHaveProperty('internalNote');
    // Et le document ne porte jamais l'identifiant de sa pièce jointe Odoo :
    // le connaître inviterait à tenter `/web/content/<id>`.
    expect(parsed.documents[0]).not.toHaveProperty('attachmentId');
  });

  it('le détail expédition refuse un champ interne sur un document', () => {
    // `.strict()` refuse toute clé hors contrat : un document du dossier
    // opérationnel ne peut pas se glisser dans la réponse en emportant ses
    // champs internes.
    const detail = {
      reference: 'DT-SHP-2', transportMode: 'air', transportModeLabel: 'Air Freight',
      origin: 'Paris', destination: 'Dakar', status: 'draft',
      statusLabel: 'Draft', departureDate: null, estimatedArrival: null,
      actualArrival: null, lastUpdate: null, carrierTrackingNumber: null,
      containerNumber: null, goodsDescription: null, packagesCount: 0,
      timeline: [], packages: [],
      documents: [{
        reference: 'DOC-8', name: 'interne.pdf',
        documentType: 'other', documentTypeLabel: 'Autre',
        relatedTo: 'Expédition', relatedReference: 'DT-SHP-2',
        publishedOn: null, internalNote: 'CANARY_INTERNAL_DOCUMENT',
      }],
    };
    expect(() => portalShipmentDetailSchema.parse(detail)).toThrow();
  });

  it('le document n’expose aucun identifiant de pièce jointe', () => {
    const document = {
      reference: 'DOC-1', name: 'Facture', documentType: 'other',
      documentTypeLabel: 'Autre', relatedTo: 'Expédition',
      relatedReference: 'DT-SHP-1', publishedOn: '2026-08-15',
    };
    const parsed = portalDocumentSchema.parse(document);
    expect(parsed).not.toHaveProperty('attachmentId');
    expect(portalDocumentSchema.safeParse({ ...document, attachmentId: 7 }).success)
      .toBe(false);
  });
});

describe('profil', () => {
  const profile = {
    name: 'Client',
    email: 'client@example.com',
    phone: null,
    company: 'Client SARL',
    street: null,
    street2: null,
    zip: null,
    city: 'Dakar',
    country: 'Sénégal',
  };

  it('valide exactement la projection profil en lecture', () => {
    expect(portalProfileSchema.parse(profile)).toEqual(profile);
    expect(portalProfileSchema.safeParse({ ...profile, partnerId: 7 }).success)
      .toBe(false);
  });

  it('accepte un diff autorisé et le normalise', () => {
    expect(portalProfileUpdateSchema.parse({
      phone: '  +221 77 000 00 00  ',
      city: '  Dakar Plateau ',
    })).toEqual({ phone: '+221 77 000 00 00', city: 'Dakar Plateau' });
  });

  it.each([
    {},
    { partner_id: 7 },
    { company_id: 1 },
    { groups_id: [4] },
    { parent_id: 8 },
    { credit_limit: 500000 },
    { email: 'nouveau@example.com' },
    { city: 'x'.repeat(129) },
    { phone: 'javascript:alert(1)' },
    { street: '<b>Rue</b>' },
  ])('rejette le payload %j', (payload) => {
    expect(portalProfileUpdateSchema.safeParse(payload).success).toBe(false);
  });
});

describe('enveloppes', () => {
  it('valide une liste paginée', () => {
    const schema = portalListSchema(portalQuoteSchema);
    expect(schema.parse({ items: [quote], total: 1, limit: 20, offset: 0 }).total)
      .toBe(1);
  });

  it('accepte une liste vide', () => {
    const schema = portalListSchema(portalQuoteSchema);
    expect(schema.parse({ items: [], total: 0, limit: 20, offset: 0 }).items)
      .toHaveLength(0);
  });

  it('refuse une liste sans total', () => {
    const schema = portalListSchema(portalQuoteSchema);
    expect(schema.safeParse({ items: [], limit: 20, offset: 0 }).success).toBe(false);
  });

  it('valide le tableau de bord et ses cinq compteurs', () => {
    const dashboard = {
      counters: { quotes: 2, sourcing: 1, trades: 1, shipments: 1, documents: 1 },
      recent: { quotes: [quote], sourcing: [], trades: [], shipments: [], documents: [] },
    };
    expect(portalDashboardSchema.parse(dashboard).counters.quotes).toBe(2);
  });

  it('refuse un tableau de bord auquel il manque une section', () => {
    const dashboard = {
      counters: { quotes: 0, sourcing: 0, trades: 0, shipments: 0, documents: 0 },
      recent: { quotes: [], sourcing: [], trades: [], shipments: [] },
    };
    expect(portalDashboardSchema.safeParse(dashboard).success).toBe(false);
  });
});
