/**
 * Le panier, vu du navigateur.
 *
 * `GET`    — le panier tarifé.
 * `POST`   — fixe la quantité d'une référence. Zéro retire la ligne.
 * `DELETE` — vide le panier.
 *
 * ## Une seule mutation pour trois gestes
 *
 * Ajouter, modifier et retirer se réduisent tous à « cette référence doit finir à
 * cette quantité ». Trois routes distinctes auraient trois façons de dépasser les
 * bornes et trois endroits à corriger ; celle-ci n'en a qu'un.
 *
 * ## Ce que le navigateur envoie, et ce qu'il ne peut pas envoyer
 *
 * Une référence et une quantité. Pas de prix, pas de sous-total, pas de devise,
 * pas d'identifiant de panier. Le panier lui-même n'est pas dans le corps de la
 * requête : il est lu depuis le cookie scellé, modifié côté serveur, et rescellé.
 * Le navigateur ne décrit donc jamais l'état du panier — il demande une
 * transition.
 *
 * ## Le cookie altéré est refusé, puis remplacé
 *
 * Refuser sans remplacer laisserait le visiteur bloqué : chaque requête suivante
 * représenterait le même cookie invalide, et la boutique resterait cassée jusqu'à
 * ce qu'il pense à vider ses cookies. Le refus est donc accompagné d'un panier
 * neuf.
 */

import { NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';

import { getServerEnv } from '@/lib/env';
import { siteIsHttps } from '@/lib/shop/deployment';
import { logger } from '@/lib/logger';
import { checkOrigin } from '@/lib/portal/csrf';
import {
  CART_COOKIE,
  CartError,
  MAX_CART_LINES,
  MAX_LINE_QUANTITY,
  cartCookieOptions,
  clearLines,
  isValidReference,
  newCart,
  sealCart,
  setLine,
  unsealCart,
  type Cart,
} from '@/lib/shop/cart';
import { ShopGatewayError, ShopOdooGateway } from '@/lib/shop/odoo-shop';
import type { CartView } from '@/lib/shop/dto';

/**
 * Le panier est propre à un visiteur : jamais mis en cache.
 *
 * Servi depuis un cache partagé — un proxy, un CDN — le panier d'un visiteur
 * atterrirait chez le suivant.
 */
const NO_STORE = {
  'Cache-Control': 'no-store, private, max-age=0',
  Pragma: 'no-cache',
} as const;

interface Reponse {
  readonly body: unknown;
  readonly status: number;
  /** Panier à resceller dans la réponse. Absent = cookie inchangé. */
  readonly cart?: Cart;
}

export async function GET(request: Request): Promise<NextResponse> {
  const correlationId = randomUUID();
  const { cart, altered } = lireCookie(request);
  const vue = await tarifer(cart, correlationId);
  // Un cookie altéré est remplacé même sur un GET : sinon le visiteur reste
  // bloqué sur un panier qu'il ne peut ni lire ni vider.
  return repondre({
    body: { success: true, data: vue },
    status: 200,
    ...(altered ? { cart } : {}),
  });
}

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = randomUUID();

  const refusOrigine = verifierOrigine(request);
  if (refusOrigine) return refusOrigine;

  let charge: unknown;
  try {
    charge = await request.json();
  } catch {
    return repondre({
      body: erreur('invalid_body', 'A JSON body is required.'),
      status: 400,
    });
  }

  const demande = lireDemande(charge);
  if (!demande) return refusDemande();

  const { cart } = lireCookie(request);

  let modifie: Cart;
  try {
    modifie = setLine(cart, demande.reference, demande.quantity);
  } catch (error) {
    if (error instanceof CartError && error.message === 'cart is full') {
      return repondre({
        body: erreur('cart_full', `A cart holds at most ${MAX_CART_LINES} lines.`),
        status: 422,
      });
    }
    return refusDemande();
  }

  // Une référence inconnue ou non publiée ne doit pas entrer dans le panier :
  // sinon le cookie accumulerait des lignes fantômes que chaque résolution
  // retirerait, et le visiteur ne saurait pas que son ajout n'a rien fait.
  //
  // La vérification passe par le catalogue, donc par la même règle de
  // publication : un produit non publié et un produit inexistant échouent
  // identiquement.
  if (demande.quantity > 0) {
    const etat = await estPubliable(demande.reference, correlationId);
    if (etat === 'absent') {
      return repondre({
        body: erreur('not_found', 'Product not found.'),
        status: 404,
      });
    }
    if (etat === 'indisponible') {
      return repondre({
        body: erreur('unavailable', 'The shop is unavailable.'),
        status: 503,
      });
    }
  }

  const vue = await tarifer(modifie, correlationId);
  return repondre({
    body: { success: true, data: vue },
    status: 200,
    cart: modifie,
  });
}

export async function DELETE(request: Request): Promise<NextResponse> {
  const correlationId = randomUUID();

  const refusOrigine = verifierOrigine(request);
  if (refusOrigine) return refusOrigine;

  const { cart } = lireCookie(request);
  const vide = clearLines(cart);
  const vue = await tarifer(vide, correlationId);
  return repondre({
    body: { success: true, data: vue },
    status: 200,
    cart: vide,
  });
}

// ---------------------------------------------------------------------------
// Interne
// ---------------------------------------------------------------------------

/**
 * Refuse une mutation qui ne vient pas de notre propre site.
 *
 * `SameSite=Lax` bloque déjà l'essentiel, mais s'y fier seul ferait dépendre la
 * protection du navigateur du visiteur. Le même contrôle que sur les mutations du
 * portail, pour qu'il n'y ait pas une route où un relecteur doive se demander
 * pourquoi celle-ci diffère.
 */
function verifierOrigine(request: Request): NextResponse | null {
  const origine = checkOrigin(request.headers, getServerEnv().NEXT_PUBLIC_SITE_URL);
  if (origine.ok) return null;
  return repondre({
    body: erreur('forbidden_origin', 'Request origin is not allowed.'),
    status: 403,
  });
}

/** Une seule formulation du refus, pour que les variantes ne se distinguent pas. */
function refusDemande(): NextResponse {
  return repondre({
    body: erreur('invalid_request', 'A reference and a quantity are required.'),
    status: 422,
  });
}

/**
 * Lit le cookie, ou rend un panier neuf.
 *
 * `altered` distingue « pas de cookie » de « cookie illisible ». Le second est
 * journalisé — c'est le signe d'une clé rotée, d'un déploiement à deux secrets,
 * ou de quelqu'un qui essaie des variantes. Le visiteur, lui, obtient la même
 * chose dans les deux cas : un panier vide qui fonctionne.
 */
function lireCookie(request: Request): { cart: Cart; altered: boolean } {
  const brut = lireValeurCookie(request.headers.get('cookie'), CART_COOKIE);
  if (!brut) return { cart: newCart(), altered: false };
  try {
    return {
      cart: unsealCart(brut, getServerEnv().SHOP_CART_SECRET),
      altered: false,
    };
  } catch {
    logger.warn('Shop cart cookie rejected', { cookie: CART_COOKIE });
    return { cart: newCart(), altered: true };
  }
}

/**
 * Extrait une valeur de l'en-tête `Cookie`.
 *
 * Découpage manuel plutôt que `cookies()` de Next : cette route reçoit un
 * `Request` standard, et les tests l'appellent directement, sans le contexte de
 * requête de Next.
 */
function lireValeurCookie(entete: string | null, nom: string): string | null {
  if (!entete) return null;
  for (const morceau of entete.split(';')) {
    const separateur = morceau.indexOf('=');
    if (separateur === -1) continue;
    if (morceau.slice(0, separateur).trim() === nom) {
      return morceau.slice(separateur + 1).trim();
    }
  }
  return null;
}

/** La demande de transition, ou `null`. Rien n'est corrigé en silence. */
function lireDemande(
  charge: unknown,
): { reference: string; quantity: number } | null {
  if (typeof charge !== 'object' || charge === null) return null;
  const { reference, quantity } = charge as Record<string, unknown>;
  if (!isValidReference(reference)) return null;
  // Zéro est admis ici alors que `isValidQuantity` le refuse : c'est la façon de
  // retirer une ligne. Le seuil bas est donc vérifié à la main, et le seuil haut
  // reprend la constante partagée pour que les deux ne divergent pas.
  if (
    typeof quantity !== 'number' ||
    !Number.isInteger(quantity) ||
    quantity < 0 ||
    quantity > MAX_LINE_QUANTITY
  ) {
    return null;
  }
  return { reference, quantity };
}

/** Le produit est-il au catalogue publié ? */
async function estPubliable(
  reference: string,
  correlationId: string,
): Promise<'present' | 'absent' | 'indisponible'> {
  try {
    await new ShopOdooGateway().getProduct(reference, correlationId);
    return 'present';
  } catch (error) {
    if (error instanceof ShopGatewayError && error.code === 'not_found') {
      return 'absent';
    }
    return 'indisponible';
  }
}

/** Le panier vide, tel qu'il est rendu quand il n'y a rien à tarifer. */
function panierVide(): CartView {
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

/**
 * Tarife le panier, et dégrade proprement si Odoo est absent.
 *
 * Un panier vide n'appelle pas Odoo : la réponse est connue, et une requête
 * réseau par affichage pour obtenir un total de zéro serait du gaspillage sur la
 * page la plus visitée.
 *
 * Si Odoo est injoignable, on rend un panier vide plutôt qu'une erreur. Le
 * contenu du cookie est conservé — il sera tarifé au prochain essai — mais rien
 * n'est affiché avec un prix inventé.
 */
async function tarifer(cart: Cart, correlationId: string): Promise<CartView> {
  if (cart.lines.length === 0) return panierVide();

  try {
    const resolu = await new ShopOdooGateway().resolveCart(
      cart.lines,
      correlationId,
    );
    return { ...resolu, lineCount: resolu.lines.length, maxLines: MAX_CART_LINES };
  } catch (error) {
    logger.error('Cart pricing failed', {
      correlationId,
      code: error instanceof ShopGatewayError ? error.code : 'unknown',
    });
    return panierVide();
  }
}

function erreur(code: string, message: string) {
  return { success: false, error: { code, message } };
}

function repondre(reponse: Reponse): NextResponse {
  const sortie = NextResponse.json(reponse.body, {
    status: reponse.status,
    headers: NO_STORE,
  });
  if (reponse.cart) {
    const env = getServerEnv();
    sortie.cookies.set(
      CART_COOKIE,
      sealCart(reponse.cart, env.SHOP_CART_SECRET),
      cartCookieOptions(siteIsHttps()),
    );
  }
  return sortie;
}
