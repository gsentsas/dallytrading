/** `POST /api/shop/checkout` — mutation BFF unique du checkout. */

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
import { siteIsHttps } from '@/lib/shop/deployment';
import { CheckoutGatewayError, ShopCheckoutGateway } from '@/lib/shop/odoo-checkout';

const NO_STORE = {
  'Cache-Control': 'no-store, private, max-age=0',
  Pragma: 'no-cache',
} as const;

const MAX_BODY_BYTES = 8 * 1024;
const CHECKOUT_LIMIT = 10;
const CHECKOUT_WINDOW_MS = 60_000;

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const env = getServerEnv();

  const origine = checkOrigin(request.headers, env.NEXT_PUBLIC_SITE_URL);
  if (!origine.ok) {
    return repondre({ body: erreur('forbidden_origin', 'Requête refusée.'), status: 403 });
  }

  const ip = getClientIp(request.headers);
  const debit = checkRateLimit(`shop-checkout:${ip}`, CHECKOUT_LIMIT, CHECKOUT_WINDOW_MS);
  if (!debit.allowed) {
    return repondre({
      body: erreur('rate_limited', 'Trop de tentatives. Merci de patienter un instant.'),
      status: 429,
      headers: { 'Retry-After': String(debit.retryAfterSeconds) },
    });
  }

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
    return repondre({ body: erreur('invalid_body', 'Requête illisible.'), status: 400 });
  }

  const valide = checkoutRequestSchema.safeParse(charge);
  if (!valide.success) {
    return repondre({
      body: erreur('invalid_request', 'Merci de vérifier les informations saisies.'),
      status: 422,
    });
  }

  const panier = lireCookiePanier(request);
  if (!panier) {
    logger.warn('Checkout refused: unusable cart cookie', { correlationId });
    return repondre({
      body: erreur('cart_invalid', 'Votre panier n’a pas pu être lu. Merci de le reconstituer.'),
      status: 400,
    });
  }
  if (panier.lines.length === 0) {
    return repondre({ body: erreur('empty_cart', 'Votre panier est vide.'), status: 422 });
  }

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
      commande = await passerelle.placeCustomerOrder(
        {
          cartId: panier.cartId,
          deliveryMode: demandeCliente.deliveryMode,
          lines: panier.lines,
          ...(demandeCliente.shipping ? { shipping: demandeCliente.shipping } : {}),
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
          ...(demandeCliente.shipping ? { shipping: demandeCliente.shipping } : {}),
        },
        correlationId,
      );
    }
  } catch (echec) {
    return refus(echec, correlationId);
  }

  logger.info('Shop order placed', {
    correlationId,
    replayed: commande.replayed,
    guest: !session,
    lines: commande.lines.length,
    deliveryMethod: commande.delivery.method.code,
  });

  return repondre({
    body: { success: true, data: { order: commande } },
    status: 200,
    cart: newCart(),
  });
}

interface Reponse {
  readonly body: unknown;
  readonly status: number;
  readonly cart?: Cart;
  readonly headers?: Record<string, string>;
}

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
      return repondre({ body: erreur('empty_cart', 'Votre panier est vide.'), status: 422 });
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
      return repondre({
        body: erreur('unavailable', 'La commande n’a pas pu être enregistrée.'),
        status: 503,
      });
  }
}

function lireCookiePanier(request: Request): Cart | null {
  const brut = lireCookie(request.headers.get('cookie'), CART_COOKIE);
  if (!brut) return null;
  try {
    return unsealCart(brut, getServerEnv().SHOP_CART_SECRET);
  } catch {
    return null;
  }
}

function lireSessionPortail(request: Request): string | null {
  const brut = lireCookie(request.headers.get('cookie'), PORTAL_COOKIE);
  if (!brut) return null;
  try {
    const session = unsealSession(brut, getServerEnv().PORTAL_SESSION_SECRET);
    if (isExpired(session)) return null;
    return session.odooSessionId;
  } catch {
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
      cartCookieOptions(siteIsHttps()),
    );
  }
  return sortie;
}
