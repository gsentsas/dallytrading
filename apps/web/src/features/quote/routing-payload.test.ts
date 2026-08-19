/**
 * Ce que le formulaire envoie au serveur, pour l'acheminement structuré.
 *
 * Le schéma public et le mappeur sont deux étapes distinctes : le premier
 * valide et normalise, le second choisit ce qui part. Les deux sont éprouvés
 * ici, parce qu'un champ validé mais oublié dans le mappeur produit exactement
 * le même symptôme qu'un champ jamais saisi — une demande qui arrive vide.
 */

import { describe, expect, it } from 'vitest';

import { quoteRequestSchema, toQuoteInput } from './quote-schema';

const BASE = {
  requestUuid: '3f1b0c9e-2a4d-4f6b-9c1e-8d7a5b4c3e2f',
  serviceCode: 'freight_sea',
  lastName: 'Diallo',
  email: 'client@example.invalid',
};

describe('validation des codes de référentiel', () => {
  it('accepte et normalise un code en majuscules', () => {
    const resultat = quoteRequestSchema.parse({
      ...BASE, originPortCode: 'sndkr', destinationPortCode: 'FRLEH',
      originStateCode: 'dk', incotermCode: 'fob',
    });
    expect(resultat.originPortCode).toBe('SNDKR');
    expect(resultat.destinationPortCode).toBe('FRLEH');
    expect(resultat.originStateCode).toBe('DK');
    expect(resultat.incotermCode).toBe('FOB');
  });

  it('traite une chaîne vide comme une absence', () => {
    const resultat = quoteRequestSchema.parse({
      ...BASE, originPortCode: '', incotermCode: '   ',
    });
    expect(resultat.originPortCode).toBeUndefined();
    expect(resultat.incotermCode).toBeUndefined();
  });

  it('refuse ce qui ne peut pas être un code', () => {
    for (const valeur of ['SN DKR', 'SN;DROP', '../etc', 'é']) {
      expect(
        quoteRequestSchema.safeParse({ ...BASE, originPortCode: valeur }).success,
      ).toBe(false);
    }
  });

  it('refuse une date qui n’est pas un jour ISO', () => {
    for (const valeur of ['15/09/2026', '2026-13-45', 'demain']) {
      expect(
        quoteRequestSchema.safeParse({ ...BASE, desiredDate: valeur }).success,
      ).toBe(false);
    }
    expect(
      quoteRequestSchema.parse({ ...BASE, desiredDate: '2026-09-15' }).desiredDate,
    ).toBe('2026-09-15');
  });

  it('n’exige aucun de ces champs', () => {
    // Un visiteur qui ne connaît pas son port doit pouvoir demander un devis.
    expect(quoteRequestSchema.safeParse(BASE).success).toBe(true);
  });
});

describe('mappeur vers la passerelle', () => {
  it('transmet chaque code renseigné', () => {
    const data = quoteRequestSchema.parse({
      ...BASE,
      originStateCode: 'DK', destinationStateCode: '76',
      originPortCode: 'SNDKR', destinationPortCode: 'FRLEH',
      incotermCode: 'FOB',
      pickupRequested: true, pickupAddress: '12 rue du Port',
      deliveryRequested: true, deliveryAddress: '3 avenue de la Gare',
      desiredDate: '2026-09-15',
    });
    expect(toQuoteInput(data)).toMatchObject({
      originStateCode: 'DK',
      destinationStateCode: '76',
      originPortCode: 'SNDKR',
      destinationPortCode: 'FRLEH',
      incotermCode: 'FOB',
      pickupRequested: true,
      pickupAddress: '12 rue du Port',
      deliveryRequested: true,
      deliveryAddress: '3 avenue de la Gare',
      desiredDate: '2026-09-15',
    });
  });

  it('omet ce qui n’a pas été renseigné, plutôt que d’envoyer du vide', () => {
    const input = toQuoteInput(quoteRequestSchema.parse(BASE));
    for (const champ of [
      'originStateCode', 'destinationStateCode', 'originPortCode',
      'destinationPortCode', 'incotermCode', 'pickupAddress', 'desiredDate',
    ]) {
      expect(input).not.toHaveProperty(champ);
    }
  });

  it('n’invente aucun champ interne', () => {
    const input = toQuoteInput(quoteRequestSchema.parse({ ...BASE, originPortCode: 'SNDKR' }));
    for (const interdit of [
      'carrierPartnerId', 'vesselId', 'airlineId', 'frequentRouteId',
      'shippingLine', 'cost', 'margin',
    ]) {
      expect(input).not.toHaveProperty(interdit);
    }
  });
});
