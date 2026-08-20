import type { Metadata } from 'next';
import Link from 'next/link';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

import { CheckoutForm } from '@/features/shop/CheckoutForm';
import { getServerEnv } from '@/lib/env';
import { logger, newCorrelationId } from '@/lib/logger';
import { PORTAL_COOKIE, isExpired, unsealSession } from '@/lib/portal/session';
import { PortalOdooGateway, type PortalIdentity } from '@/lib/portal/odoo-portal';
import { CART_COOKIE, MAX_CART_LINES, unsealCart, type Cart } from '@/lib/shop/cart';
import type { DeliveryMethod } from '@/lib/shop/delivery';
import type { CartView } from '@/lib/shop/dto';
import { ShopDeliveryGateway } from '@/lib/shop/odoo-delivery';
import { ShopOdooGateway } from '@/lib/shop/odoo-shop';
import { pageMetadata } from '@/lib/seo';

export const metadata: Metadata = pageMetadata({
  title: 'Finaliser ma commande',
  description: 'Renseignez vos coordonnées et validez votre commande DallyTrading.',
  path: '/boutique/commande',
  noindex: true,
});

export const dynamic = 'force-dynamic';

export default async function CommandePage() {
  const correlationId = newCorrelationId();
  const jar = await cookies();

  const panier = lirePanier(jar.get(CART_COOKIE)?.value, correlationId);
  if (!panier || panier.lines.length === 0) redirect('/boutique/panier');

  const [vue, methods] = await Promise.all([
    tarifer(panier, correlationId),
    chargerMethodes(correlationId),
  ]);

  if (vue.lines.length === 0) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 lg:px-8">
        <h1 className="text-3xl font-bold text-navy-900">Finaliser ma commande</h1>
        <div role="alert" className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-900">
          <p className="font-semibold">Votre panier n’est pas commandable</p>
          <p className="mt-2 text-sm">
            Les articles ne sont plus disponibles, ou la boutique est momentanément indisponible.
          </p>
          <Link href="/boutique/panier" className="mt-4 inline-flex underline">Revoir mon panier</Link>
        </div>
      </main>
    );
  }

  if (methods.length === 0) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 lg:px-8">
        <h1 className="text-3xl font-bold text-navy-900">Finaliser ma commande</h1>
        <div role="alert" className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-900">
          <p className="font-semibold">Aucune méthode de remise disponible</p>
          <p className="mt-2 text-sm">
            La commande ne peut pas être finalisée pour le moment. Aucun mode ni tarif de livraison n’est inventé côté site.
          </p>
          <Link href="/boutique/panier" className="mt-4 inline-flex underline">Retour au panier</Link>
        </div>
      </main>
    );
  }

  const client = await identifier(jar.get(PORTAL_COOKIE)?.value, correlationId);

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-navy-900 sm:text-4xl">Finaliser ma commande</h1>
        <p className="mt-3 max-w-2xl text-mist-600">
          Votre commande est enregistrée comme demande. Odoo décide des frais de remise selon la méthode choisie ; aucun prix de livraison n’est calculé dans le navigateur.
        </p>
      </header>

      <CheckoutForm
        cart={vue}
        signedIn={client !== null}
        customerName={client?.name ?? null}
        methods={methods}
      />
    </main>
  );
}

function lirePanier(brut: string | undefined, correlationId: string): Cart | null {
  if (!brut) return null;
  try {
    return unsealCart(brut, getServerEnv().SHOP_CART_SECRET);
  } catch {
    logger.warn('Cart cookie rejected on checkout page', { correlationId });
    return null;
  }
}

function vide(): CartView {
  return {
    lines: [], removed: [], itemCount: 0, subtotal: 0, currency: '',
    total: 0, lineCount: 0, maxLines: MAX_CART_LINES,
  };
}

async function tarifer(panier: Cart, correlationId: string): Promise<CartView> {
  try {
    const resolu = await new ShopOdooGateway().resolveCart(panier.lines, correlationId);
    return { ...resolu, lineCount: resolu.lines.length, maxLines: MAX_CART_LINES };
  } catch (error) {
    logger.error('Cart pricing failed on checkout page', {
      correlationId,
      error: error instanceof Error ? error.name : 'unknown',
    });
    return vide();
  }
}

async function chargerMethodes(correlationId: string): Promise<readonly DeliveryMethod[]> {
  try {
    return await new ShopDeliveryGateway().getMethods(correlationId);
  } catch (error) {
    logger.error('Delivery methods unavailable on checkout page', {
      correlationId,
      error: error instanceof Error ? error.name : 'unknown',
    });
    return [];
  }
}

async function identifier(
  brut: string | undefined,
  correlationId: string,
): Promise<{ name: string } | null> {
  if (!brut) return null;
  try {
    const session = unsealSession(brut, getServerEnv().PORTAL_SESSION_SECRET);
    if (isExpired(session)) return null;
    const identite = await new PortalOdooGateway().get<PortalIdentity>(
      '/me',
      session.odooSessionId,
      correlationId,
    );
    return { name: identite.name };
  } catch {
    logger.info('Checkout page: no usable portal session', { correlationId });
    return null;
  }
}
