/**
 * Composants de la vitrine.
 *
 * Server Components sauf mention contraire : une tuile produit n'a ni état ni
 * interaction, et la marquer `'use client'` par habitude enverrait ce code au
 * navigateur pour rien.
 *
 * Aucun nouveau système de design — les classes reprennent la charte du site
 * (navy / mist / green), pour que la boutique ressemble à DallyTrading et non à
 * une application greffée.
 *
 * ## Le prix vient du serveur, déjà formaté ou déjà nombre
 *
 * Rien ici ne calcule un prix, n'applique une remise, ni ne convertit une devise.
 * Le seul travail de mise en forme est l'affichage — séparateurs de milliers et
 * code devise — et il est fait avec la locale, pas à la main.
 */

import Link from 'next/link';

import type { ShopAvailability, ShopProduct } from '@/lib/shop/dto';

/**
 * Met un montant en forme pour l'affichage.
 *
 * `Intl.NumberFormat` plutôt qu'un `toFixed` maison : les montants de la région
 * s'écrivent avec des séparateurs de milliers, et un montant à six chiffres sans
 * séparateur est illisible.
 *
 * La devise vient d'Odoo. Elle est passée à `Intl` comme code ISO, avec repli en
 * suffixe quand ce n'en est pas un — le tarif de la boutique est libre de porter
 * n'importe quel nom, et une exception au milieu d'un rendu ferait tomber la page
 * entière pour un problème de mise en forme.
 */
export function formatPrice(amount: number, currency: string): string {
  const estCodeIso = /^[A-Z]{3}$/.test(currency);
  if (estCodeIso) {
    try {
      return new Intl.NumberFormat('fr-FR', {
        style: 'currency',
        currency,
        maximumFractionDigits: 0,
      }).format(amount);
    } catch {
      // Code à trois lettres qu'Intl ne connaît pas : on retombe plus bas.
    }
  }
  const nombre = new Intl.NumberFormat('fr-FR', {
    maximumFractionDigits: 0,
  }).format(amount);
  return currency ? `${nombre} ${currency}` : nombre;
}

/**
 * Étiquette de disponibilité.
 *
 * Les libellés sont ici et non côté Odoo, contrairement à `stockPolicyLabel` :
 * celui-ci décrit une donnée métier, celle-là décrit un état d'affichage. La
 * différence compte, parce qu'`out_of_stock` doit pouvoir changer de formulation
 * commerciale sans toucher à l'ERP.
 */
const DISPONIBILITE: Record<ShopAvailability, { label: string; className: string }> = {
  on_order: {
    label: 'Sur commande',
    className: 'bg-mist-100 text-navy-800',
  },
  in_stock: {
    label: 'En stock',
    className: 'bg-green-100 text-green-900',
  },
  out_of_stock: {
    label: 'Réapprovisionnement en cours',
    className: 'bg-amber-100 text-amber-900',
  },
};

export function AvailabilityBadge({
  availability,
}: {
  availability: ShopAvailability;
}) {
  const { label, className } = DISPONIBILITE[availability];
  return (
    <span
      className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${className}`}
    >
      {label}
    </span>
  );
}

/** Une tuile du catalogue. Cliquable en entier, vers la fiche. */
export function ProductCard({ product }: { product: ShopProduct }) {
  return (
    <article className="flex flex-col rounded-xl border border-mist-200 bg-white p-5 transition hover:border-navy-300 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-lg font-semibold text-navy-900">
          <Link
            href={`/boutique/${product.reference}`}
            className="hover:underline"
          >
            {product.name}
          </Link>
        </h2>
        <AvailabilityBadge availability={product.availability} />
      </div>

      {product.category && (
        <p className="mt-1 text-xs uppercase tracking-wide text-mist-500">
          {product.category.name}
        </p>
      )}

      {product.summary && (
        <p className="mt-3 flex-1 text-sm text-mist-600">{product.summary}</p>
      )}

      <p className="mt-4 text-xl font-bold text-navy-900">
        {formatPrice(product.price, product.currency)}
      </p>

      <Link
        href={`/boutique/${product.reference}`}
        className="mt-4 inline-flex items-center justify-center rounded-lg border border-navy-200 px-4 py-2 text-sm font-medium text-navy-800 hover:bg-mist-50"
      >
        Voir le produit
      </Link>
    </article>
  );
}

/**
 * Catalogue vide.
 *
 * Ne dit pas « aucun résultat » : il n'y a pas de recherche, et cette formulation
 * laisserait croire qu'un produit pourrait exister ailleurs. Un catalogue sans
 * produit publié n'a pas de produit publié, c'est tout.
 */
export function EmptyCatalogue() {
  return (
    <div className="rounded-xl border border-dashed border-mist-300 bg-white p-10 text-center">
      <p className="text-mist-600">
        Notre catalogue en ligne s’ouvre prochainement. En attendant, nos équipes
        répondent à toute demande par devis.
      </p>
      <Link
        href="/devis"
        className="mt-4 inline-flex rounded-lg bg-navy-800 px-5 py-2.5 text-sm font-semibold text-white hover:bg-navy-900"
      >
        Demander un devis
      </Link>
    </div>
  );
}

/**
 * Panne de l'ERP.
 *
 * Ni code d'erreur, ni URL Odoo, ni identifiant de corrélation : ce dernier vit
 * dans les journaux serveur, où le support le retrouve. Sur la page, il
 * n'aiderait personne et cartographierait notre infrastructure.
 */
export function ShopUnavailable() {
  return (
    <div
      role="alert"
      className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-900"
    >
      <p className="font-semibold">Boutique momentanément indisponible</p>
      <p className="mt-2 text-sm">
        Le catalogue n’a pas pu être chargé. Merci de réessayer dans quelques
        instants.
      </p>
    </div>
  );
}
