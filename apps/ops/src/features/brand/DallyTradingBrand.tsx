import Link from 'next/link';

/**
 * L'identité DallyTrading dans l'application terrain.
 *
 * ## Une image, pas une reconstruction
 *
 * Le logo complet — emblème circulaire, wordmark DallyTrading, signature — est
 * affiché depuis le fichier officiel, tel quel. Rien n'est redessiné en CSS :
 * une approximation du logo d'une entreprise est pire que pas de logo, parce
 * qu'elle a l'air presque juste, et c'est exactement ainsi qu'une mauvaise
 * version finit sur une facture imprimée. C'est déjà la règle du site public
 * (`apps/web/public/brand/README.md`) ; elle vaut ici aussi.
 *
 * ## Pourquoi une plaque blanche
 *
 * L'application a un fond très sombre (`--ops-fond`, #0f172a) et l'œuvre
 * officielle est marine et verte sur transparence : posée directement, elle
 * disparaîtrait. La plaque ne modifie ni les couleurs ni la composition du
 * logo — elle lui rend le fond blanc sur lequel il a été dessiné.
 *
 * ## « Dally Ops »
 *
 * C'est le nom de l'outil, pas de la marque. Il reste un libellé distinct, à
 * côté du logo, et n'est jamais composé avec lui.
 */
export function DallyTradingBrand() {
  return (
    <Link
      className="ops-brand"
      href="/"
      aria-label="DallyTrading — retour à l’accueil de Dally Ops"
    >
      {/*
        Un <img> simple, pas next/image : une marque de taille fixe ne gagne
        rien à l'optimiseur, et le fichier est déjà dimensionné pour l'écran.
      */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className="ops-brand-logo"
        src="/brand/dallytrading-logo.png"
        alt="DallyTrading"
        width={640}
        height={460}
      />
      <span className="ops-brand-app">Dally Ops</span>
    </Link>
  );
}
