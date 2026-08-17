import type { Metadata } from 'next';
import { cookies } from 'next/headers';

import { CartLines } from '@/features/shop/CartLines';
import { getServerEnv } from '@/lib/env';
import { logger, newCorrelationId } from '@/lib/logger';
import {
  CART_COOKIE,
  MAX_CART_LINES,
  unsealCart,
  type Cart,
} from '@/lib/shop/cart';
import { ShopOdooGateway } from '@/lib/shop/odoo-shop';
import type { CartView } from '@/lib/shop/dto';
import { pageMetadata } from '@/lib/seo';

/**
 * `noindex` sans condition d'environnement : le panier d'un visiteur n'a rien à
 * faire dans un index, et une page qui dépend d'un cookie ne peut de toute façon
 * pas être archivée utilement.
 */
export const metadata: Metadata = pageMetadata({
  title: 'Mon panier',
  description: 'Les articles que vous avez sélectionnés dans la boutique DallyTrading.',
  path: '/boutique/panier',
  noindex: true,
});

/** Dépend d'un cookie : jamais pré-rendu, jamais mis en cache. */
export const dynamic = 'force-dynamic';

/**
 * La page panier.
 *
 * ## Le premier rendu est déjà tarifé
 *
 * Le panier est lu et tarifé côté serveur, avant l'envoi. Laisser le composant
 * client le charger après affichage produirait un panier vide pendant une
 * fraction de seconde, puis un saut de mise en page — et rendrait la page
 * inutilisable sans JavaScript.
 *
 * ## Un cookie illisible ne casse pas la page
 *
 * Clé rotée, déploiement à deux secrets, ou quelqu'un qui essaie des variantes :
 * le résultat est le même, un panier vide qui fonctionne. C'est aussi ce que fait
 * la route `/api/shop/cart`, qui remplace en plus le cookie fautif dès la
 * première requête.
 */
export default async function PanierPage() {
  const correlationId = newCorrelationId();
  const brut = (await cookies()).get(CART_COOKIE)?.value;

  let panier: Cart | null = null;
  if (brut) {
    try {
      panier = unsealCart(brut, getServerEnv().SHOP_CART_SECRET);
    } catch {
      logger.warn('Shop cart cookie rejected on cart page', { correlationId });
    }
  }

  const vue = await tarifer(panier, correlationId);

  return (
    <main className="mx-auto max-w-4xl px-4 py-10 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-navy-900 sm:text-4xl">Mon panier</h1>
      </header>
      <CartLines initial={vue} />
    </main>
  );
}

/** Un panier vide, tel qu'il est rendu quand il n'y a rien à tarifer. */
function vide(): CartView {
  return {
    lines: [],
    removed: [],
    itemCount: 0,
    subtotal: 0,
    currency: '',
    total: 0,
    lineCount: 0,
    maxLines: MAX_CART_LINES,
  };
}

async function tarifer(panier: Cart | null, correlationId: string): Promise<CartView> {
  if (!panier || panier.lines.length === 0) return vide();
  try {
    const resolu = await new ShopOdooGateway().resolveCart(panier.lines, correlationId);
    return { ...resolu, lineCount: resolu.lines.length, maxLines: MAX_CART_LINES };
  } catch (error) {
    // Panier vide plutôt qu'un prix inventé. Le cookie est conservé : le contenu
    // réapparaîtra tarifé au prochain essai.
    logger.error('Cart pricing failed on cart page', {
      correlationId,
      error: error instanceof Error ? error.name : 'unknown',
    });
    return vide();
  }
}
