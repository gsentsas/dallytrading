/**
 * Le reçu tel qu'il s'affiche et tel qu'il s'imprime.
 *
 * Aucun calcul ici. Les montants arrivent déjà écrits par le serveur, dans les
 * mêmes caractères que le PDF : reformater à l'écran ferait un jour dire au
 * papier et à l'écran deux choses différentes sur un arrondi, et c'est le
 * client qui le remarquerait.
 *
 * Ce qui n'a pas de prix ne s'affiche pas comme un prix. Un article sur devis
 * porte « à définir », jamais « 0 € » — un client y lirait « rien à payer ».
 */

import type { Recu } from '@/lib/ops/receipts';

export function RecuDocument({ recu }: { recu: Recu }) {
  return (
    <article className="recu">
      <header className="recu-entete">
        <div>
          <p className="recu-societe">{recu.company.name}</p>
          {recu.company.address ? (
            <p className="attenue recu-petit">{recu.company.address}</p>
          ) : null}
          {recu.company.phone ? (
            <p className="attenue recu-petit">{recu.company.phone}</p>
          ) : null}
        </div>
        <div className="recu-titre">
          <p>{recu.document.title}</p>
          <p className="attenue recu-petit">Établi le {recu.document.generated_at}</p>
        </div>
      </header>

      <section className="recu-dossier">
        <p className="recu-etiquette">DOSSIER</p>
        <p className="reference recu-numero">{recu.reference}</p>
      </section>

      <section className="carte">
        <p className="recu-etiquette">CLIENT</p>
        <p className="route" style={{ margin: 0 }}>{recu.customer.name}</p>
        {recu.customer.phone ? <p className="attenue" style={{ margin: 0 }}>{recu.customer.phone}</p> : null}
        {recu.customer.address ? <p className="attenue" style={{ margin: 0 }}>{recu.customer.address}</p> : null}
        {recu.customer.email ? <p className="attenue" style={{ margin: 0 }}>{recu.customer.email}</p> : null}
      </section>

      <section className="carte">
        <p className="recu-etiquette">EXPÉDITION</p>
        <p style={{ margin: 0 }}>Réception : {recu.received_on}</p>
        <p style={{ margin: 0 }}>Transport : {recu.transport_mode_label}</p>
        {recu.consolidation.origin ? (
          <p style={{ margin: 0 }}>
            Trajet : {recu.consolidation.origin} → {recu.consolidation.destination}
          </p>
        ) : null}
        {recu.consolidation.reference ? (
          <p className="attenue" style={{ margin: 0 }}>
            Départ : {recu.consolidation.reference}
          </p>
        ) : null}
      </section>

      <section className="carte">
        <p className="recu-etiquette">MARCHANDISES PRISES EN CHARGE</p>
        <ul className="recu-articles">
          {recu.articles.map((article, index) => (
            <li key={`${article.description}-${index}`}>
              <p style={{ margin: 0 }}>{article.description}</p>
              <p className="attenue recu-petit" style={{ margin: 0 }}>
                {article.tariff_family} · {article.quantity} ×{' '}
                {article.exact_weight_display}
                {article.dimensions ? ` · ${article.dimensions}` : ''}
              </p>
              <p className="recu-montant" style={{ margin: 0 }}>
                {article.transport_amount_eur === null
                  ? 'Tarif à définir'
                  : `${article.applied_unit_price_display}/kg · ${article.transport_amount_display}`}
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section className="carte">
        <p className="recu-etiquette">PAIEMENTS REÇUS</p>
        {recu.payments.length === 0 ? (
          <p style={{ margin: 0 }}>Aucun paiement reçu à ce jour.</p>
        ) : (
          <ul className="recu-articles">
            {recu.payments.map((paiement, index) => (
              <li key={`${paiement.date}-${index}`}>
                <p style={{ margin: 0 }}>
                  {paiement.date} · <strong>{paiement.amount_display}</strong> ·{' '}
                  {paiement.method}
                </p>
                <p className="attenue recu-petit" style={{ margin: 0 }}>
                  {paiement.collected_by ? `reçu par ${paiement.collected_by}` : ''}
                  {paiement.wave_reference ? ` · réf. ${paiement.wave_reference}` : ''}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="carte recu-totaux">
        <p>
          <span>Articles</span><span>{recu.totals.articles_count}</span>
        </p>
        <p>
          <span>Poids total</span><span>{recu.totals.weight_display}</span>
        </p>
        <p>
          <span>Total transport</span>
          <span>
            {recu.totals.transport_amount_eur === null
              ? 'À définir'
              : recu.totals.transport_amount_display}
          </span>
        </p>
        {recu.totals.paid.map((paye) => (
          <p key={paye.currency_code}>
            <span>Montant reçu</span><span>{paye.display}</span>
          </p>
        ))}
        <p className="recu-solde">
          <span>Reste à payer</span>
          <span>
            {recu.totals.balance_eur === null
              ? 'Voir le détail des paiements'
              : recu.totals.balance_display}
          </span>
        </p>
        {/* Jamais un solde inventé : soustraire des francs d'un total en euros
            demanderait un taux que personne n'a choisi. */}
        {recu.totals.balance_reason === 'currency_mismatch' ? (
          <p className="attenue recu-petit">
            Les paiements et le tarif ne sont pas dans la même monnaie : le
            solde ne peut pas être arrêté sur ce document.
          </p>
        ) : null}
        {recu.totals.balance_reason === 'pricing_incomplete' ? (
          <p className="attenue recu-petit">
            Le tarif de tous les articles n’est pas encore arrêté.
          </p>
        ) : null}
      </section>

      <footer className="attenue recu-petit">
        {recu.operator.name ? (
          <p style={{ margin: 0 }}>
            Marchandises réceptionnées par {recu.operator.name}.
          </p>
        ) : null}
        {recu.invoice_number ? (
          <p style={{ margin: 0 }}>Facture associée : {recu.invoice_number}.</p>
        ) : null}
        <p style={{ marginBottom: 0 }}>
          Ce document atteste de la prise en charge des marchandises décrites
          ci-dessus. Il ne constitue pas une facture.
        </p>
      </footer>
    </article>
  );
}
