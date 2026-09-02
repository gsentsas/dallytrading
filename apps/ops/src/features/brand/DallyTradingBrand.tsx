import Link from 'next/link';

/**
 * Identité DallyTrading dans l'application terrain.
 *
 * Le pictogramme vient directement du logo officiel fourni par le propriétaire
 * de la marque. Le wordmark reste en texte pour rester parfaitement lisible
 * dans l'en-tête compact de l'application mobile.
 */
export function DallyTradingBrand() {
  return (
    <Link
      className="ops-brand"
      href="/"
      aria-label="DallyTrading — retour à l’accueil de Dally Ops"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className="ops-brand-icon"
        src="/icones/dallytrading-ops-192.png"
        alt=""
        aria-hidden="true"
        width={52}
        height={52}
      />
      <span className="ops-brand-copy">
        <span className="ops-brand-wordmark" aria-hidden="true">
          <span className="ops-brand-dally">Dally</span>
          <span className="ops-brand-trading">Trading</span>
        </span>
        <span className="ops-brand-signature">IMPORT • EXPORT • LOGISTICS • SOLUTIONS</span>
        <span className="ops-brand-app">Dally Ops</span>
      </span>
    </Link>
  );
}
