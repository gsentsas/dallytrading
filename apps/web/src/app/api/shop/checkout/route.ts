/**
 * `POST /api/shop/checkout` — la seule route du BFF qui crée une commande.
 *
 * ## Ce que le navigateur envoie, et ce qu'il ne peut pas envoyer
 *
 * Un mode de remise, et pour un invité son identité. C'est tout.
 *
 * Les **lignes** viennent du cookie scellé, pas du corps de la requête. Un
 * formulaire qui enverrait ses propres lignes permettrait de commander un contenu
 * différent de celui du panier affiché.
 *
 * L'**identifiant de panier** vient du même cookie. L'accepter du navigateur
 * laisserait choisir sa propre clé d'idempotence — donc rejouer la commande de
 * quelqu'un d'autre si on devinait son identifiant.
 *
 * Aucun prix ne traverse dans aucun sens : le montant rendu est celui qu'Odoo a
 * calculé au moment de créer la commande.
 *
 * ## Deux transports, décidés ici et pas par le navigateur
 *
 * Une session portail présente et valide → commande au nom du client, identité
 * lue par Odoo depuis `request.env.user.partner_id`. Pas de session → commande
 * invité, qui **exige** un bloc `customer`.
 *
 * La branche est décidée par la présence d'un cookie de session que nous avons
 * nous-mêmes scellé, jamais par un drapeau du corps de la requête.
 *
 * ## Rotation du panier
 *
 * Après une création réussie, le cookie est remplacé par un panier neuf, avec un
 * **nouvel** identifiant. Le client repart avec un panier vide, prêt pour une
 * commande suivante qui ne rejouera pas la précédente.
 *
 * Un rejeu de la requête initiale reste sûr : si la réponse précédente n'a pas
 * atteint le navigateur, celui-ci présente encore l'ancien cookie, Odoo reconnaît
 * l'identifiant et rend la **même** commande — jamais une seconde.
 */

import { NextResponse } from 'next/server';

import { getServerEnv } from '@/lib/env';
import { logger, newCorrelationId } from '@/lib/logger';
import { checkOrigin } from '@/lib/portal/csrf';
import { PORTAL_COOKIE, isExpired, unsealSession } from '@/lib/portal/session';
import { checkRateLimit, getClientIp } from '@/lib/rate-limit';
import {
  CART_COOKIE,
  cartCookieOptions,
  newCart,
  sealCart,
  unsealCart,
  type Cart,
} from '@/lib/shop/cart';
import { checkoutRequestSchema, type ShopOrder } from '@/lib/shop/checkout-schema';
import { CheckoutGatewayError, ShopCheckoutGateway } from '@/lib/shop/odoo-checkout';

/** Une commande est propre à un visiteur : jamais mise en cache. */
const NO_STORE = {
  'Cache-Control': 'no-store, private, max-age=0',
  Pragma: 'no-cache',
} as const;

/**
 * Taille maximale du corps.
 *
 * Le corps utile fait quelques centaines d'octets. Le plafond existe pour qu'une
 * requête de 10 Mo soit refusée avant d'être désérialisée, et non après.
 */
const MAX_BODY_BYTES = 8 * 1024;

/**
 * Commandes autorisées par IP et par fenêtre.
 *
 * Plus permissif que le formulaire de devis, parce qu'un rejeu légitime est
 * fréquent ici — double clic, reprise réseau, retour arrière — et qu'un rejeu ne
 * crée rien. Assez bas pour qu'une boucle automatisée ne remplisse pas l'ERP de
 * contacts invités.
 */
const CHECKOUT_LIMIT = 10;
const CHECKOUT_WINDOW_MS = 60_000;

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const env = getServerEnv();

  // ── Origine ───────────────────────────────────────────────────────────
  const origine = checkOrigin(request.headers, env.NEXT_PUBLIC_SITE_URL);
  if (!origine.ok) {
    return repondre({
      body: erreur('forbidden_origin', 'Requête refusée.'),
      status: 403,
    });
  }

  // ── Débit ─────────────────────────────────────────────────────────────
  const ip = getClientIp(request.headers);
  const debit = checkRateLimit(`shop-checkout:${ip}`, CHECKOUT_LIMIT, CHECKOUT_WINDOW_MS);
  if (!debit.allowed) {
    return repondre({
      body: erreur('rate_limited', 'Trop de tentatives. Merci de patienter un instant.'),
      status: 429,
      headers: { 'Retry-After': String(debit.retryAfterSeconds) },
    });
  }

  // ── Corps ─────────────────────────────────────────────────────────────
  const brut = await request.text();
  if (brut.length > MAX_BODY_BYTES) {
    return repondre({
      body: erreur('payload_too_large', 'Requête trop volumineuse.'),
      status: 413,
    });
  }

  let charge: unknown;
  try {
    charge = JSON.parse(brut);
  } catch {
    return repondre({
      body: erreur('invalid_body', 'Requête illisible.'),
      status: 400,
    });
  }

  const valide = checkoutRequestSchema.safeParse(charge);
  if (!valide.success) {
    // Le détail du refus n'est pas renvoyé : il décrirait le contrat interne.
    // Le formulaire valide déjà les mêmes règles et affiche ses propres messages.
    return repondre({
      body: erreur('invalid_request', 'Merci de vérifier les informations saisies.'),
      status: 422,
    });
  }

  // ── Panier ────────────────────────────────────────────────────────────
  const panier = lireCookiePanier(request);
  if (!panier) {
    // Cookie altéré, illisible, ou absent : aucune commande. Le client reprend
    // depuis son panier, qui sera reconstruit vide par la route panier.
    logger.warn('Checkout refused: unusable cart cookie', { correlationId });
    return repondre({
      body: erreur('cart_invalid', 'Votre panier n’a pas pu être lu. Merci de le reconstituer.'),
      status: 400,
    });
  }
  if (panier.lines.length === 0) {
    return repondre({
      body: erreur('empty_cart', 'Votre panier est vide.'),
      status: 422,
    });
  }

  // ── Transport ─────────────────────────────────────────────────────────
  const session = lireSessionPortail(request);
  const demandeCliente = valide.data;

  if (!session && !demandeCliente.customer) {
    return repondre({
      body: erreur('customer_required', 'Merci d’indiquer vos coordonnées.'),
      status: 422,
    });
  }

  const passerelle = new ShopCheckoutGateway();
  let commande: ShopOrder;
  try {
    if (session) {
      // Client connecté. Le bloc `customer` est ignoré ici et **refusé** par
      // Odoo : c'est là que la règle est appliquée, pas dans une politesse du BFF.
      commande = await passerelle.placeCustomerOrder(
        {
          cartId: panier.cartId,
          deliveryMode: demandeCliente.deliveryMode,
          lines: panier.lines,
        },
        session,
        correlationId,
      );
    } else {
      commande = await passerelle.placeGuestOrder(
        {
          cartId: panier.cartId,
          deliveryMode: demandeCliente.deliveryMode,
          lines: panier.lines,
          customer: demandeCliente.customer!,
        },
        correlationId,
      );
    }
  } catch (echec) {
    return refus(echec, correlationId);
  }

  // ── Succès : rotation du panier ───────────────────────────────────────
  //
  // Un panier neuf, avec un identifiant neuf. Le précédent a produit sa commande
  // et ne doit plus pouvoir en produire une autre — ni, à l'inverse, empêcher la
  // suivante en restant reconnu comme déjà utilisé.
  logger.info('Shop order placed', {
    correlationId,
    replayed: commande.replayed,
    guest: !session,
    lines: commande.lines.length,
  });

  return repondre({
    body: { success: true, data: { order: commande } },
    status: 200,
    cart: newCart(),
  });
}

// ---------------------------------------------------------------------------
// Interne
// ---------------------------------------------------------------------------

interface Reponse {
  readonly body: unknown;
  readonly status: number;
  readonly cart?: Cart;
  readonly headers?: Record<string, string>;
}

/**
 * Traduit un échec de la passerelle en réponse client.
 *
 * Chaque code reçoit un message écrit pour la personne qui le lira, et pas la
 * reformulation d'une erreur technique. Deux cas méritent d'être distingués à
 * l'écran, parce qu'ils appellent deux gestes différents : un produit devenu
 * indisponible se corrige dans le panier, un compte existant se règle en se
 * connectant.
 */
function refus(echec: unknown, correlationId: string): NextResponse {
  if (!(echec instanceof CheckoutGatewayError)) {
    logger.error('Checkout failed unexpectedly', { correlationId });
    return repondre({
      body: erreur('unavailable', 'La commande n’a pas pu être enregistrée.'),
      status: 503,
    });
  }

  switch (echec.code) {
    case 'unavailable_products':
      return repondre({
        body: erreur(
          'unavailable_products',
          'Un ou plusieurs articles ne sont plus disponibles. Merci de revoir votre panier.',
        ),
        status: 409,
      });
    case 'portal_account_exists':
      return repondre({
        body: erreur(
          'portal_account_exists',
          'Un compte existe déjà avec cette adresse e-mail. Merci de vous connecter pour commander.',
        ),
        status: 409,
      });
    case 'empty_cart':
      return repondre({
        body: erreur('empty_cart', 'Votre panier est vide.'),
        status: 422,
      });
    case 'invalid_checkout':
    case 'forbidden_fields':
      return repondre({
        body: erreur('invalid_request', 'Merci de vérifier les informations saisies.'),
        status: 422,
      });
    case 'unauthenticated':
      return repondre({
        body: erreur('unauthenticated', 'Votre session a expiré. Merci de vous reconnecter.'),
        status: 401,
      });
    case 'rate_limited':
      return repondre({
        body: erreur('rate_limited', 'Trop de tentatives. Merci de patienter un instant.'),
        status: 429,
      });
    default:
      // `misconfigured`, `forbidden`, `shop_unavailable`, `timeout`,
      // `unavailable`, `invalid_response` : des pannes d'exploitation. Le client
      // n'y peut rien, et le détail cartographierait notre infrastructure.
      return repondre({
        body: erreur('unavailable', 'La commande n’a pas pu être enregistrée.'),
        status: 503,
      });
  }
}

/** Le panier du cookie, ou `null` si le cookie est absent ou illisible. */
function lireCookiePanier(request: Request): Cart | null {
  const brut = lireCookie(request.headers.get('cookie'), CART_COOKIE);
  if (!brut) return null;
  try {
    return unsealCart(brut, getServerEnv().SHOP_CART_SECRET);
  } catch {
    return null;
  }
}

/**
 * L'identifiant de session Odoo, ou `null`.
 *
 * Le plafond local d'ancienneté est appliqué ici comme partout ailleurs, mais il
 * ne prouve rien : Odoo reste seul juge, et une session révoquée de son côté sera
 * refusée même si ce contrôle passe. L'inverse serait dangereux.
 */
function lireSessionPortail(request: Request): string | null {
  const brut = lireCookie(request.headers.get('cookie'), PORTAL_COOKIE);
  if (!brut) return null;
  try {
    const session = unsealSession(brut, getServerEnv().PORTAL_SESSION_SECRET);
    if (isExpired(session)) return null;
    return session.odooSessionId;
  } catch {
    // Cookie de session illisible : on traite le visiteur comme anonyme plutôt
    // que de refuser. Il pourra commander en invité, ce qui est mieux que de le
    // bloquer sur une commande à cause d'un cookie périmé.
    return null;
  }
}

function lireCookie(entete: string | null, nom: string): string | null {
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

function erreur(code: string, message: string) {
  return { success: false, error: { code, message } };
}

function repondre(reponse: Reponse): NextResponse {
  const sortie = NextResponse.json(reponse.body, {
    status: reponse.status,
    headers: { ...NO_STORE, ...(reponse.headers ?? {}) },
  });
  if (reponse.cart) {
    const env = getServerEnv();
    sortie.cookies.set(
      CART_COOKIE,
      sealCart(reponse.cart, env.SHOP_CART_SECRET),
      cartCookieOptions(env.ENVIRONMENT === 'production'),
    );
  }
  return sortie;
}
