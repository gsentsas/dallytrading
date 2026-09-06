import type { Reconciliation } from '@/lib/ops/intake-lines';

/**
 * L'état du dossier dans les trois systèmes, tel que le serveur le dit.
 *
 * ## Ce que cet écran ne calcule pas
 *
 * Rien. Pas un montant, pas un reste à payer, pas un nombre d'articles non
 * facturés. Tout vient d'Odoo, qui seul sait ce qu'une pièce comptabilisée
 * porte et ce qu'une ligne couvre. Sommer les colis ici donnerait un nombre
 * plausible — et faux le jour où un frais de dossier s'ajoute, ou celui où un
 * complément est émis.
 *
 * De même pour la synchronisation : l'écran ne devine pas si un envoi va
 * repartir. Il affiche le message que le serveur a rédigé pour l'opérateur.
 */

const LIBELLE_PROJECTION: Record<Reconciliation['sheet']['state'], string> = {
  synced: 'Synchronisé',
  pending: 'En attente',
  retry: 'Nouvelle tentative prévue',
  failed: 'Échec de synchronisation',
  absent: 'Non demandé',
};

/** L'état comptable, dit en français de comptoir. */
const LIBELLE_FACTURE: Record<string, string> = {
  none: 'Aucune facture',
  draft: 'Brouillon',
  posted: 'Comptabilisée',
  cancel: 'Annulée',
};

function montant(valeur: number, devise: string): string {
  return `${valeur.toLocaleString('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ${devise === 'EUR' ? '€' : devise}`;
}

export function SynchronisationDossier(
  { etat }: { readonly etat: Reconciliation },
): React.JSX.Element {
  const { crm, sheet, billing } = etat;
  const facture =
    LIBELLE_FACTURE[billing.primary_invoice_state] ?? billing.primary_invoice_state;

  return (
    <section aria-labelledby="synchronisation-titre" data-testid="synchronisation-dossier">
      <h2 id="synchronisation-titre">Synchronisation</h2>

      <section className="carte" data-testid="etat-crm">
        <h3 style={{ margin: 0, fontSize: '0.85rem' }}>CRM</h3>
        <p style={{ margin: '0.25rem 0 0', fontWeight: 600 }}>
          {crm.state === 'recorded' ? 'Enregistré' : crm.state}
        </p>
      </section>

      <section className="carte" data-testid="etat-tableur">
        <h3 style={{ margin: 0, fontSize: '0.85rem' }}>Tableur</h3>
        <p style={{ margin: '0.25rem 0 0', fontWeight: 600 }}>
          {LIBELLE_PROJECTION[sheet.state]}
        </p>
        <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
          {sheet.operator_message}
        </p>
      </section>

      <section className="carte" data-testid="etat-facturation">
        <h3 style={{ margin: 0, fontSize: '0.85rem' }}>Facturation</h3>
        {billing.primary_invoice_number === null ? (
          <p className="attenue" style={{ margin: '0.25rem 0 0' }}>
            Aucune facture émise pour ce dossier.
          </p>
        ) : (
          <>
            <p style={{ margin: '0.25rem 0 0', fontWeight: 600 }}>
              {billing.primary_invoice_number}
            </p>
            <p style={{ margin: '0.2rem 0 0' }}>
              {montant(billing.primary_invoice_amount, billing.currency)}
            </p>
            <p className="attenue" style={{ margin: '0.2rem 0 0' }}>{facture}</p>
            {billing.total_remaining_amount > 0 ? (
              <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
                Reste à payer sur le dossier&nbsp;:{' '}
                {montant(billing.total_remaining_amount, billing.currency)}
              </p>
            ) : null}
          </>
        )}
      </section>

      {billing.unbilled_lines_count > 0 ? (
        <section className="carte" data-testid="articles-non-factures">
          <h3 style={{ margin: 0, fontSize: '0.85rem' }}>Suppléments</h3>
          <p style={{ margin: '0.25rem 0 0', fontWeight: 600 }}>
            {billing.unbilled_lines_count === 1
              ? '1 article non facturé'
              : `${billing.unbilled_lines_count} articles non facturés`}
          </p>
          <p style={{ margin: '0.2rem 0 0' }}>
            {montant(billing.unbilled_amount, billing.currency)}
          </p>
        </section>
      ) : null}

      {billing.supplements.map((complement) => (
        <section
          className="carte"
          data-testid="facture-complementaire"
          key={complement.invoice_number ?? complement.amount}
        >
          <h3 style={{ margin: 0, fontSize: '0.85rem' }}>Facture complémentaire</h3>
          <p style={{ margin: '0.25rem 0 0', fontWeight: 600 }}>
            {complement.invoice_number ?? 'Brouillon'}
          </p>
          <p style={{ margin: '0.2rem 0 0' }}>
            {montant(complement.amount, billing.currency)}
          </p>
          <p className="attenue" style={{ margin: '0.2rem 0 0' }}>
            {LIBELLE_FACTURE[complement.invoice_state] ?? complement.invoice_state}
          </p>
        </section>
      ))}
    </section>
  );
}
