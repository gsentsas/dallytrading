import type { FicheLegacy } from '@/lib/ops/legacy-intake';

/**
 * La fiche d'un dossier que Dally Ops n'a pas créé.
 *
 * ## Ce que ce composant n'importe pas
 *
 * Aucun bloc de mutation : ni encaissement, ni transition d'état, ni photo, ni
 * événement, ni correction d'article. Ils ne sont pas désactivés, ils sont
 * absents. Un bouton grisé promet une action pour bientôt ; ici il n'y en aura
 * pas, et le dire franchement vaut mieux que le laisser espérer.
 *
 * ## Pourquoi un bandeau plutôt qu'une simple absence de boutons
 *
 * Un opérateur qui ne trouve pas le bouton d'encaissement conclut d'abord à
 * une panne. Le bandeau répond à la question avant qu'elle se pose.
 */
export function FicheLectureSeule({ fiche }: { fiche: FicheLegacy }) {
  return (
    <article data-testid="fiche-lecture-seule">
      <p className="badge" role="status" data-testid="bandeau-lecture-seule"
         style={{ display: 'block', margin: '0 0 1rem' }}>
        DOSSIER EN LECTURE SEULE
      </p>
      <p className="attenue" style={{ margin: '0 0 1.5rem' }}>
        Ces informations proviennent d’un dossier historique. Aucune
        modification n’est disponible depuis Dally Ops.
      </p>

      <section aria-labelledby="fiche-dossier-titre">
        <h2 id="fiche-dossier-titre">DOSSIER</h2>
        <dl className="paires">
          <Paire libelle="Référence" valeur={fiche.reference} testid="ls-reference" />
          {fiche.local_reference ? (
            <Paire libelle="Référence locale" valeur={fiche.local_reference}
                   testid="ls-reference-locale" />
          ) : null}
          <Paire libelle="État" valeur={fiche.state_label} testid="ls-etat" />
          <Paire libelle="Mode" valeur={fiche.transport_mode} testid="ls-mode" />
          <Paire libelle="Sens" valeur={fiche.direction} testid="ls-sens" />
          {fiche.consolidation_reference ? (
            <Paire libelle="Départ" valeur={fiche.consolidation_reference}
                   testid="ls-depart" />
          ) : null}
          {fiche.received_on ? (
            <Paire libelle="Reçu le" valeur={fiche.received_on} testid="ls-recu-le" />
          ) : null}
        </dl>
      </section>

      <section aria-labelledby="fiche-client-titre">
        <h2 id="fiche-client-titre">CLIENT</h2>
        <p style={{ margin: 0 }} data-testid="ls-client-nom">{fiche.customer.name}</p>
        {fiche.customer.phone ? (
          <p className="attenue" style={{ margin: 0 }} data-testid="ls-client-telephone">
            {fiche.customer.phone}
          </p>
        ) : null}
      </section>

      <section aria-labelledby="fiche-colis-titre">
        <h2 id="fiche-colis-titre">COLIS</h2>
        {fiche.lines.length === 0 ? (
          <p className="attenue" data-testid="ls-aucun-colis">
            Aucun colis enregistré sur ce dossier.
          </p>
        ) : null}
        {fiche.lines.map((ligne, rang) => (
          <section className="carte" key={rang} data-testid="ls-colis">
            <p style={{ margin: 0 }}>
              <strong>{ligne.description || ligne.package_type}</strong>
            </p>
            <p className="attenue" style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>
              {[
                ligne.goods_category,
                `${ligne.quantity} colis`,
                `${ligne.exact_weight_kg} kg`,
                ligne.volume_cbm ? `${ligne.volume_cbm} m³` : '',
              ].filter(Boolean).join(' · ')}
            </p>
          </section>
        ))}
      </section>

      <section aria-labelledby="fiche-totaux-titre">
        <h2 id="fiche-totaux-titre">TOTAUX</h2>
        <dl className="paires">
          <Paire libelle="Colis" valeur={String(fiche.totals.lines_count)}
                 testid="ls-total-colis" />
          <Paire libelle="Poids" valeur={`${fiche.totals.weight_kg} kg`}
                 testid="ls-total-poids" />
          <Paire libelle="Volume" valeur={`${fiche.totals.volume_cbm} m³`}
                 testid="ls-total-volume" />
        </dl>
      </section>

      <section aria-labelledby="fiche-encaissements-titre">
        <h2 id="fiche-encaissements-titre">ENCAISSEMENTS</h2>
        {fiche.payments.length === 0 ? (
          <p className="attenue" data-testid="ls-aucun-encaissement">
            Aucun encaissement enregistré sur ce dossier.
          </p>
        ) : null}
        {fiche.payments.map((paiement, rang) => (
          <section className="carte" key={rang} data-testid="ls-encaissement">
            <p style={{ margin: 0 }}>
              <strong>{paiement.amount} {paiement.currency_code}</strong>
            </p>
            <p className="attenue" style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>
              {[
                paiement.payment_date,
                paiement.payment_method.name,
                paiement.collector,
                paiement.accounting_status,
              ].filter(Boolean).join(' · ')}
            </p>
          </section>
        ))}
        {fiche.payment_summary.map((total, rang) => (
          <p key={rang} data-testid="ls-total-encaisse" style={{ margin: '0.5rem 0 0' }}>
            <strong>Total encaissé : {total.amount} {total.currency_code}</strong>
          </p>
        ))}
      </section>
    </article>
  );
}

function Paire(
  { libelle, valeur, testid }:
  { libelle: string; valeur: string; testid: string },
) {
  return (
    <>
      <dt className="attenue">{libelle}</dt>
      <dd data-testid={testid} style={{ margin: '0 0 0.5rem' }}>{valeur}</dd>
    </>
  );
}
