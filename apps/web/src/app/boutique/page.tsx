import type { Metadata } from 'next';

import { EmptyCatalogue, ProductCard, ShopUnavailable } from '@/features/shop/ui';
import { logger, newCorrelationId } from '@/lib/logger';
import { ShopOdooGateway } from '@/lib/shop/odoo-shop';
import type { ShopCatalogue } from '@/lib/shop/dto';
import { pageMetadata } from '@/lib/seo';

export const metadata: Metadata = pageMetadata({
  title: 'Boutique',
  description:
    'Le catalogue en ligne de DallyTrading : équipements et pièces disponibles ' +
    'à la commande, avec des prix tenus à jour depuis notre ERP.',
  path: '/boutique',
});

/**
 * Le catalogue public.
 *
 * ## Rendu à la demande, malgré la tentation de le figer
 *
 * Une vitrine se prête à la génération statique. On s'en abstient : la
 * dépublication d'un produit doit prendre effet tout de suite. Un catalogue
 * pré-rendu continuerait d'afficher un article retiré de la vente jusqu'à la
 * prochaine régénération, et personne ne penserait à la déclencher.
 *
 * Le coût est absorbé par l'en-tête `Cache-Control` posé par Odoo sur la réponse
 * du catalogue : deux minutes, assez pour amortir les rafales, assez court pour
 * qu'une dépublication se propage en minutes.
 *
 * ## Aucun secret ne s'approche du navigateur
 *
 * L'appel part du serveur, avec la clé `shop:read`. Le composant ne reçoit que la
 * projection publique, donc rien de ce que le navigateur pourrait lire n'est
 * autre chose que ce que la page affiche.
 */
export const dynamic = 'force-dynamic';

export default async function BoutiquePage() {
  const correlationId = newCorrelationId();

  let catalogue: ShopCatalogue | null = null;
  try {
    catalogue = await new ShopOdooGateway().getCatalogue(correlationId);
  } catch (error) {
    // La page reste affichée, avec un encart honnête. Une erreur 500 sur la
    // vitrine ferait disparaître le reste du site pour le visiteur.
    logger.error('Shop catalogue unavailable', {
      correlationId,
      error: error instanceof Error ? error.name : 'unknown',
    });
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-navy-900 sm:text-4xl">Boutique</h1>
        <p className="mt-3 max-w-2xl text-mist-600">
          Les articles ci-dessous sont commandables en ligne. Les prix sont ceux
          de notre tarif en vigueur ; la livraison est chiffrée séparément selon
          la destination.
        </p>
      </header>

      {catalogue === null && <ShopUnavailable />}

      {catalogue !== null && catalogue.products.length === 0 && <EmptyCatalogue />}

      {catalogue !== null && catalogue.products.length > 0 && (
        <>
          {catalogue.categories.length > 0 && (
            <p className="mb-6 text-sm text-mist-600">
              {catalogue.categories
                .map((categorie) => `${categorie.name} (${categorie.productCount})`)
                .join(' · ')}
            </p>
          )}
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {catalogue.products.map((produit) => (
              <ProductCard key={produit.reference} product={produit} />
            ))}
          </div>
        </>
      )}
    </main>
  );
}
