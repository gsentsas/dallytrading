import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

const { FormulaireWave } = await import('@/features/reception/FormulaireWave');

const CONTEXTE = {
  intake_reference: 'AIR-DSS-CDG-TEST-001-A001',
  customer_name: 'Aissatou Kandji',
  payment_method: 'wave' as const,
  beneficiary: 'Gilles',
  currencies: ['XOF'],
  payments: { items: [], summary: [] },
};

function rendu(): string {
  return renderToStaticMarkup(
    <FormulaireWave
      contexte={CONTEXTE}
      onAnnuler={() => undefined}
      soumettre={async () => ({ ok: true })}
    />,
  );
}

describe('formulaire d’encaissement Wave', () => {
  const html = rendu();

  it('annonce le bénéficiaire, le dossier et le client', () => {
    expect(html).toContain('BÉNÉFICIAIRE');
    expect(html).toContain('GILLES');
    expect(html).toContain('AIR-DSS-CDG-TEST-001-A001');
    expect(html).toContain('Aissatou Kandji');
  });

  it('n’offre aucun moyen de choisir le bénéficiaire ni le moyen', () => {
    // Les deux viennent du serveur : les rendre modifiables ferait promettre
    // une imputation que le serveur ne ferait pas.
    for (const interdit of ['name="beneficiary"', 'id="beneficiaire-saisie"',
                            'name="payment_method"', 'id="mode-paiement"',
                            'value="cash"', 'value="bank"']) {
      expect(html).not.toContain(interdit);
    }
  });

  it('demande le montant, la devise, la référence Wave et la date', () => {
    for (const libelle of ['Montant', 'Devise', 'Référence Wave', 'Date d’encaissement']) {
      expect(html).toContain(libelle);
    }
  });

  it('annonce la référence Wave comme facultative', () => {
    expect(html).toContain('facultative');
  });

  it('interdit une date future dès la saisie', () => {
    expect(html).toContain(`max="${new Date().toISOString().slice(0, 10)}"`);
  });

  it('ne contient aucun identifiant Odoo à soumettre', () => {
    for (const interdit of ['partner_id', 'shipment_id', 'company_id',
                            'currency_id', 'collection_id', 'invoice_id']) {
      expect(html).not.toContain(interdit);
    }
  });

  it('n’invente aucune vérification Wave', () => {
    // L'écran enregistre ce que l'opérateur constate ; il n'interroge pas Wave.
    for (const interdit of ['wa.me', 'wave.com', 'otp', 'code de confirmation',
                            'vérifier auprès de Wave']) {
      expect(html.toLowerCase()).not.toContain(interdit.toLowerCase());
    }
  });

  it('parle uniquement au BFF', () => {
    const source = FormulaireWave.toString();
    expect(source).not.toContain('/api/v1/ops/');
    expect(source).not.toContain('API_KEY');
  });
});
