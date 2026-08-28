import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
  }),
}));

const { FormulaireColis } = await import(
  '@/features/reception/FormulaireColis'
);

function rendu(): string {
  return renderToStaticMarkup(
    <FormulaireColis
      consolidation="AIR-DSS-CDG-2026-002"
      customer="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
      familles={[{
        code: 'non_food',
        name: 'Non alimentaire',
      }]}
    />,
  );
}

describe('formulaire de première ligne', () => {
  const html = rendu();

  it('affiche tous les champs terrain demandés', () => {
    for (const libelle of [
      'Type de colis',
      'Catégorie',
      'Désignation',
      'Quantité',
      'Poids annoncé',
      'Poids exact total',
      'Dimensions',
      'Méthode facturation',
      'Famille tarifaire',
      'Valeur déclarée du contenu',
    ]) {
      expect(html).toContain(libelle);
    }
  });

  it('ne propose ni véhicule ni conteneur', () => {
    expect(html).not.toContain('value="vehicle"');
    expect(html).not.toContain('value="container"');
  });

  it('porte le bon avertissement de valeur douanière', () => {
    expect(html).toContain(
      'pas le prix du transport',
    );
  });

  it('parle uniquement au BFF', () => {
    const source = FormulaireColis.toString();
    expect(source).toContain('/api/intakes');
    expect(source).not.toContain('/api/v1/ops/');
    expect(source).not.toContain('API_KEY');
  });

  it('génère request_uuid et line_uuid avant le POST', () => {
    const source = FormulaireColis.toString();
    expect(source).toContain('crypto.randomUUID()');
    expect(source).toContain('request_uuid');
    expect(source).toContain('line_uuid');
  });

  it('n’envoie aucune identité calculée serveur', () => {
    const source = FormulaireColis.toString();
    for (const interdit of [
      'partner_id',
      'shipment_id',
      'collection_local_ref',
      'external_line_key',
      'manual_unit_price_eur',
    ]) {
      expect(source).not.toContain(interdit);
    }
  });

  it('prévoit À définir et Sur devis sans afficher 0 €', () => {
    const source = FormulaireColis.toString();
    expect(source).toContain('À définir');
    expect(source).toContain('Sur devis');
    expect(source).not.toContain('0 €');
  });
});

