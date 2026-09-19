import type { ListeDepenses } from '@/lib/ops/expenses';

export function DepensesNonAffectees({ liste }: { liste: ListeDepenses }) {
  if (liste.expenses.length === 0) return null;

  return (
    <section className="ops-unassigned-expenses" aria-labelledby="depenses-non-affectees-titre">
      <div className="ops-section-heading">
        <h2 id="depenses-non-affectees-titre">DÉPENSES NON AFFECTÉES</h2>
        <p>{liste.expenses.length} écriture(s) historique(s)</p>
      </div>
      <p className="attenue">
        Ces dépenses sont bien dans la caisse, mais aucune référence de consolidation
        suffisamment sûre ne permet de les rattacher automatiquement.
      </p>
      {liste.expenses.map((depense) => (
        <section className="carte" key={depense.reference}>
          <div className="ops-depart-card-top">
            <span className="ops-state-pill"><span aria-hidden="true" />Historique</span>
            <span>{depense.expense_date}</span>
          </div>
          <p style={{ margin: '0.35rem 0 0' }}>
            <strong>{depense.description || depense.category}</strong>
          </p>
          <p className="attenue" style={{ margin: '0.25rem 0 0' }}>
            {[
              depense.category,
              depense.paid_by ? `Payé par ${depense.paid_by}` : '',
              depense.payment_method,
            ].filter(Boolean).join(' · ')}
          </p>
          <p style={{ margin: '0.4rem 0 0' }}>
            <strong>{depense.amount} {depense.currency_code}</strong>
          </p>
        </section>
      ))}
      {liste.summary.map((total) => (
        <p key={total.currency_code} style={{ margin: '0.5rem 0 0' }}>
          <strong>Total non affecté : {total.amount} {total.currency_code}</strong>
        </p>
      ))}
    </section>
  );
}
