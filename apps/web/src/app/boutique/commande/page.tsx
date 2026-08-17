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
import { ShopOdooGateway } from '@/lib/shop/odoo-shop';
import type { CartView } from '@/lib/shop/dto';
import { pageMetadata } from '@/lib/seo';

/**
 * `noindex` sans condition : cette page dépend d'un cookie de panier, et son
 * contenu est propre à un visiteur. Elle n'a rien à faire dans un index.
 */
export const metadata: Metadata = pageMetadata({
  title: 'Finaliser ma commande',
  description: 'Renseignez vos coordonnées et validez votre commande DallyTrading.',
  path: '/boutique/commande',
  noindex: true,
});

export const dynamic = 'force-dynamic';

/**
 * La page de commande.
 *
 * ## Le panier est relu et retarifé ici
 *
 * À chaque affichage, comme à chaque envoi. Le panier vit dans un cookie qui peut
 * avoir trente jours : afficher un total calculé à la mise au panier ferait
 * valider un montant périmé. La relecture est aussi ce qui écarte les produits
 * dépubliés depuis — ils disparaissent du récapitulatif, et le client le voit
 * avant de valider plutôt qu'après.
 *
 * ## L'identité affichée vient d'Odoo
 *
 * Pour un client connecté, le nom montré est celui de son profil, lu par la
 * passerelle portail sous sa propre session. Le formulaire ne le lui demande pas :
 * le lui demander laisserait croire qu'il peut le changer ici, et l'envoyer serait
 * refusé côté serveur.
 */
export default async function CommandePage() {
  const correlationId = newCorrelationId();
  const jar = await cookies();

  const panier = lirePanier(jar.get(CART_COOKIE)?.value, correlationId);
  if (!panier || panier.lines.length === 0) {
    // Rien à commander : on renvoie au panier plutôt que d'afficher un formulaire
    // qui ne pourrait pas aboutir.
    redirect('/boutique/panier');
  }

  const vue = await tarifer(panier, correlationId);
  if (vue.lines.length === 0) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 lg:px-8">
        <h1 className="text-3xl font-bold text-navy-900">Finaliser ma commande</h1>
        <div
          role="alert"
          className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-900"
        >
          <p className="font-semibold">Votre panier n’est pas commandable</p>
          <p className="mt-2 text-sm">
            Les articles ne sont plus disponibles, ou la boutique est
            momentanément indisponible.
          </p>
          <Link href="/boutique/panier" className="mt-4 inline-flex underline">
            Revoir mon panier
          </Link>
        </div>
      </main>
    );
  }

  const client = await identifier(jar.get(PORTAL_COOKIE)?.value, correlationId);

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-navy-900 sm:text-4xl">
          Finaliser ma commande
        </h1>
        <p className="mt-3 max-w-2xl text-mist-600">
          Votre commande est enregistrée comme demande : nous vérifions la
          disponibilité puis vous recontactons pour la confirmer. Aucun paiement
          n’est demandé en ligne.
        </p>
      </header>

      <CheckoutForm
        cart={vue}
        signedIn={client !== null}
        customerName={client?.name ?? null}
      />
    </main>
  );
}

/** Le panier du cookie, ou `null`. Un cookie illisible ne casse pas la page. */
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
    // Panier vide plutôt qu'un prix inventé : le client ne doit pas pouvoir
    // valider une commande dont le montant n'a pas été calculé par Odoo.
    logger.error('Cart pricing failed on checkout page', {
      correlationId,
      error: error instanceof Error ? error.name : 'unknown',
    });
    return vide();
  }
}

/**
 * Le client connecté, ou `null`.
 *
 * Une session illisible ou expirée ne bloque pas : le visiteur commande en
 * invité. Le refuser serait plus strict et moins utile — il n'a rien fait de mal,
 * et son cookie a simplement vieilli.
 *
 * Le nom vient d'Odoo, lu sous la session du client. Le BFF n'ajoute aucun
 * filtre : il n'a rien à ajouter, et tout ce qu'il ajouterait serait une décision
 * de sécurité prise du mauvais côté.
 */
async function identifier(
  brut: string | undefined,
  correlationId: string,
): Promise<{ name: string } | null> {
  if (!brut) return null;
  try {
    const session = unsealSession(brut, getServerEnv().PORTAL_SESSION_SECRET);
    if (isExpired(session)) return null;
    // `/api/v1/portal/me` sous la session du client : c'est Odoo qui décide de
    // qui il s'agit, pas le cookie qui l'affirme.
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
