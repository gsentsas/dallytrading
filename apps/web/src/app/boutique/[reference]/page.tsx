import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { AddToCart } from '@/features/shop/AddToCart';
import { AvailabilityBadge, formatPrice } from '@/features/shop/ui';
import { logger, newCorrelationId } from '@/lib/logger';
import { ShopGatewayError, ShopOdooGateway } from '@/lib/shop/odoo-shop';
import type { ShopProductDetail } from '@/lib/shop/dto';
import { pageMetadata } from '@/lib/seo';

export const dynamic = 'force-dynamic';

/**
 * Charge la fiche, ou distingue « absent » de « en panne ».
 *
 * Les deux doivent produire des pages différentes — un 404 et un encart de panne
 * — mais la fonction ne doit surtout pas distinguer *pourquoi* c'est absent : un
 * produit non publié et un slug inventé arrivent tous deux ici comme `not_found`,
 * parce qu'Odoo répond la même chose aux deux.
 */
async function charger(
  reference: string,
): Promise<
  { kind: 'found'; product: ShopProductDetail } | { kind: 'absent' } | { kind: 'panne' }
> {
  const correlationId = newCorrelationId();
  try {
    const product = await new ShopOdooGateway().getProduct(reference, correlationId);
    return { kind: 'found', product };
  } catch (error) {
    if (error instanceof ShopGatewayError && error.code === 'not_found') {
      return { kind: 'absent' };
    }
    logger.error('Shop product unavailable', {
      correlationId,
      code: error instanceof ShopGatewayError ? error.code : 'unknown',
    });
    return { kind: 'panne' };
  }
}

/**
 * Métadonnées de la fiche.
 *
 * Le titre vient d'Odoo. Pour un produit absent, on renvoie des métadonnées
 * neutres plutôt que de laisser fuir la référence demandée : lors du cycle fret,
 * une page 404 qui reprenait la référence dans ses liens canoniques avait produit
 * un faux positif d'exfiltration, et la même construction ferait ici du contenu
 * indexable à partir d'une chaîne fournie par un visiteur.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ reference: string }>;
}): Promise<Metadata> {
  const { reference } = await params;
  const resultat = await charger(reference);
  if (resultat.kind !== 'found') {
    return pageMetadata({
      title: 'Produit introuvable',
      description: 'Ce produit n’est pas disponible dans notre boutique en ligne.',
      path: '/boutique',
      noindex: true,
    });
  }
  return pageMetadata({
    title: resultat.product.name,
    description:
      resultat.product.summary ??
      `${resultat.product.name} — disponible à la commande chez DallyTrading.`,
    path: `/boutique/${resultat.product.reference}`,
  });
}

/**
 * La fiche produit.
 *
 * ## Un produit non publié est un produit inconnu
 *
 * `notFound()` dans les deux cas, donc la page 404 standard du site, identique
 * mot pour mot. Rien dans la réponse — ni le statut, ni le corps, ni un en-tête —
 * ne permet de dire si la référence existe. C'est le seul comportement qui
 * empêche d'énumérer un catalogue en préparation.
 *
 * ## Le prix n'est jamais recalculé ici
 *
 * Il arrive déjà décidé. Le composant client d'ajout au panier ne le reçoit même
 * pas : il n'envoie qu'une référence et une quantité.
 */
export default async function ProduitPage({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const { reference } = await params;
  const resultat = await charger(reference);

  if (resultat.kind === 'absent') {
    notFound();
  }

  if (resultat.kind === 'panne') {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 lg:px-8">
        <div
          role="alert"
          className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-900"
        >
          <p className="font-semibold">Boutique momentanément indisponible</p>
          <p className="mt-2 text-sm">
            Cette fiche n’a pas pu être chargée. Merci de réessayer dans quelques
            instants.
          </p>
        </div>
        <Link href="/boutique" className="mt-6 inline-flex text-navy-800 underline">
          Retour à la boutique
        </Link>
      </main>
    );
  }

  const { product } = resultat;

  return (
    <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 lg:px-8">
      <nav aria-label="Fil d’Ariane" className="mb-6 text-sm text-mist-600">
        <Link href="/boutique" className="hover:underline">
          Boutique
        </Link>
        {product.category && <span> · {product.category.name}</span>}
      </nav>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <h1 className="text-3xl font-bold text-navy-900">{product.name}</h1>
        <AvailabilityBadge availability={product.availability} />
      </div>

      {product.summary && <p className="mt-4 text-mist-600">{product.summary}</p>}

      <p className="mt-6 text-3xl font-bold text-navy-900">
        {formatPrice(product.price, product.currency)}
      </p>
      <p className="mt-1 text-sm text-mist-500">
        Prix unitaire par {product.unit} · {product.stockPolicyLabel}
      </p>

      <AddToCart reference={product.reference} />

      {product.description && (
        <section className="mt-10 border-t border-mist-200 pt-6">
          <h2 className="text-lg font-semibold text-navy-900">Description</h2>
          {/*
            `whitespace-pre-line` et non `dangerouslySetInnerHTML` : la
            description vient d'un champ Odoo que le personnel remplit, et
            l'injecter en HTML ferait de la vitrine publique une surface de XSS
            stockée depuis l'ERP. Les retours à la ligne suffisent.
          */}
          <p className="mt-3 whitespace-pre-line text-mist-600">
            {product.description}
          </p>
        </section>
      )}

      <p className="mt-10 text-sm text-mist-500">
        Les frais de livraison ne sont pas inclus : ils dépendent de la destination
        et vous sont communiqués avant toute confirmation.
      </p>
    </main>
  );
}
