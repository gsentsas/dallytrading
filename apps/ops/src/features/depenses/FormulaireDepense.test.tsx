import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

const { FormulaireDepense } = await import('@/features/depenses/FormulaireDepense');

function rendu(): string {
  return renderToStaticMarkup(
    <FormulaireDepense
      depart="AIR-DSS-CDG-2026-002"
      payeur="Gilles"
      onAnnuler={() => undefined}
      soumettre={async () => ({ ok: true })}
    />,
  );
}

describe('formulaire de dépense', () => {
  const html = rendu();

  it('demande ce qu’une dépense de terrain a besoin de dire', () => {
    for (const libelle of ['Nature', 'Description', 'Bénéficiaire', 'Montant',
                           'Devise', 'Payé par', 'Date', 'Commentaire']) {
      expect(html).toContain(libelle);
    }
  });

  it('affiche le payeur sans permettre de le changer', () => {
    expect(html).toContain('Gilles');
    // Aucun champ de saisie du payeur : l'imputation vient du compte, pas de
    // ce qu'un opérateur tape.
    expect(html).not.toContain('name="paid_by"');
    expect(html).not.toContain('id="payeur-saisie"');
  });

  it('ne propose que les quatre modes de paiement autorisés', () => {
    for (const mode of ['cash', 'wave', 'bank', 'other']) {
      expect(html).toContain(`value="${mode}"`);
    }
    for (const absent of ['orange_money', 'cheque', 'card']) {
      expect(html).not.toContain(`value="${absent}"`);
    }
  });

  it('n’offre aucun choix d’état ni de source', () => {
    for (const interdit of ['validated', 'google_sheets', 'legacy_xlsx',
                            'backoffice', 'external_expense_key']) {
      expect(html).not.toContain(interdit);
    }
  });

  it('interdit une date future dès la saisie', () => {
    const aujourdhui = new Date().toISOString().slice(0, 10);
    expect(html).toContain(`max="${aujourdhui}"`);
  });
});

describe('ce que le formulaire n’envoie pas', () => {
  const html = rendu();

  it('ne contient aucun identifiant Odoo à soumettre', () => {
    for (const interdit of ['consolidation_id', 'company_id', 'currency_id',
                            'partner_id', 'expense_id']) {
      expect(html).not.toContain(interdit);
    }
  });

  it('n’ouvre aucune adresse : la soumission passe par le BFF', () => {
    // Pas d'`action` : c'est `soumettre` qui décide, et il ne connaît que
    // `/api/expenses`.
    expect(html).not.toContain('action=');
    expect(html).not.toContain('crm.dallytrading.com');
    expect(html).not.toContain('/api/v1/ops/');
  });
});
