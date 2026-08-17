import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetServerEnvCache } from '@/lib/env';
import { PORTAL_COOKIE, sealSession } from '@/lib/portal/session';
import { resetRateLimits } from '@/lib/rate-limit';
import { CART_COOKIE, newCart, sealCart, unsealCart, type Cart } from '@/lib/shop/cart';

const SITE = 'https://dallytrading.com';
const CART_SECRET = 'c'.repeat(48);
const PORTAL_SECRET = 'p'.repeat(48);
const CHECKOUT_KEY = 'shop-checkout-key-server-side-only-0123456';
const READ_KEY = 'shop-read-key-server-side-only-0123456789';
const DEFAULT_KEY = 'default-key-must-never-be-used-here-01234';
const ODOO_SESSION = 'checkoutodoosession123456';

const INVITE = {
  name: 'Invité Test',
  email: 'invite@essai.invalid',
  phone: '+221 77 000 00 00',
  street: '1 rue de Test',
  city: 'Dakar',
  zip: '11000',
  country_code: 'SN',
};

let fetchMock: ReturnType<typeof vi.fn>;

function commandeOdoo(surcharge: Record<string, unknown> = {}) {
  return new Response(
    JSON.stringify({
      success: true,
      data: {
        order: {
          reference: 'S00042',
          status: 'draft',
          deliveryMode: 'pickup',
          deliveryModeLabel: 'Retrait sur place',
          currency: 'XOF',
          amountUntaxed: 300000,
          amountTax: 0,
          amountTotal: 300000,
          lines: [
            {
              reference: 'filtre-a-huile',
              name: 'Filtre à huile',
              quantity: 2,
              unitPrice: 150000,
              subtotal: 300000,
            },
          ],
          replayed: false,
          ...surcharge,
        },
      },
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

function erreurOdoo(status: number, code: string) {
  return new Response(JSON.stringify({ success: false, error: { code } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function panierScelle(lignes = [{ reference: 'filtre-a-huile', quantity: 2 }]): {
  cookie: string;
  cart: Cart;
} {
  const cart: Cart = { ...newCart(), lines: lignes };
  return { cookie: sealCart(cart, CART_SECRET), cart };
}

function requete(options: {
  body?: unknown;
  cartCookie?: string;
  portalCookie?: string;
  origin?: string | null;
  brut?: string;
} = {}) {
  const entetes: Record<string, string> = { 'Content-Type': 'application/json' };
  if (options.origin !== null) entetes.origin = options.origin ?? SITE;
  const cookies: string[] = [];
  if (options.cartCookie) cookies.push(`${CART_COOKIE}=${options.cartCookie}`);
  if (options.portalCookie) cookies.push(`${PORTAL_COOKIE}=${options.portalCookie}`);
  if (cookies.length) entetes.cookie = cookies.join('; ');
  return new Request(`${SITE}/api/shop/checkout`, {
    method: 'POST',
    headers: entetes,
    body: options.brut ?? JSON.stringify(options.body ?? {
      deliveryMode: 'pickup', customer: INVITE,
    }),
  });
}

async function POST() {
  return (await import('./route')).POST;
}

function cookiePose(response: Response): string | null {
  const brut = response.headers.get('set-cookie');
  if (!brut) return null;
  const trouve = brut.split(/,(?=\s*\w+=)/).find((p) => p.includes(CART_COOKIE));
  if (!trouve) return null;
  return trouve.split(';')[0]?.split('=').slice(1).join('=') ?? null;
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = SITE;
  // Le site de test est en https : le cookie de panier posé par cette route doit
  // donc porter `Secure`, quelle que soit la valeur de `ENVIRONMENT`.
  process.env.ENVIRONMENT = 'development';
  process.env.ODOO_URL = 'https://crm.checkout.invalid';
  process.env.ODOO_DATABASE = 'test_db';
  process.env.ODOO_API_KEY = DEFAULT_KEY;
  process.env.ODOO_API_KEY_SHOP_READ = READ_KEY;
  process.env.ODOO_API_KEY_SHOP_CHECKOUT = CHECKOUT_KEY;
  process.env.ODOO_TIMEOUT_MS = '2000';
  process.env.PORTAL_SESSION_SECRET = PORTAL_SECRET;
  process.env.SHOP_CART_SECRET = CART_SECRET;
  resetServerEnvCache();
  resetRateLimits();

  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('commande invité', () => {
  it('envoie les lignes du cookie, jamais celles du corps', async () => {
    fetchMock.mockResolvedValueOnce(commandeOdoo());
    const { cookie, cart } = panierScelle();

    const response = await (await POST())(
      requete({ cartCookie: cookie, body: { deliveryMode: 'pickup', customer: INVITE } }),
    );

    expect(response.status).toBe(200);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://crm.checkout.invalid/api/v1/shop/checkout');
    const envoye = JSON.parse(init.body as string);
    // L'identifiant de panier vient du cookie : le navigateur ne choisit pas sa
    // propre clé d'idempotence.
    expect(envoye.cartId).toBe(cart.cartId);
    expect(envoye.lines).toEqual([{ reference: 'filtre-a-huile', quantity: 2 }]);
    expect(envoye.customer.email).toBe(INVITE.email);
  });

  it('part avec la clé shop:checkout, jamais la clé de lecture ni la clé par défaut', async () => {
    fetchMock.mockResolvedValueOnce(commandeOdoo());
    const { cookie } = panierScelle();

    const response = await (await POST())(requete({ cartCookie: cookie }));

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const entetes = init.headers as Record<string, string>;
    expect(entetes['X-API-Key']).toBe(CHECKOUT_KEY);
    expect(entetes['X-API-Key']).not.toBe(READ_KEY);
    expect(entetes['X-API-Key']).not.toBe(DEFAULT_KEY);
    // Et aucune clé ne revient au navigateur.
    const corps = await response.text();
    expect(corps).not.toContain(CHECKOUT_KEY);
    expect(corps).not.toContain(READ_KEY);
    expect(corps).not.toContain(DEFAULT_KEY);
  });

  it('exige un bloc client en l’absence de session', async () => {
    const { cookie } = panierScelle();
    const response = await (await POST())(
      requete({ cartCookie: cookie, body: { deliveryMode: 'pickup' } }),
    );
    expect(response.status).toBe(422);
    expect((await response.json()).error.code).toBe('customer_required');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('échoue explicitement si la clé de commande n’est pas configurée', async () => {
    // Aucun repli sur ODOO_API_KEY : la boutique ne doit pas se mettre à
    // fonctionner sous une identité capable d'écrire des prospects.
    //
    // Deux couches refusent, et ce test porte sur la seconde. Le schéma
    // d'environnement rejette dès le démarrage lorsque le site est en https —
    // c'est le filet de production, vérifié dans `env`. Ici on éprouve la garde
    // de la passerelle, qui est la seule à s'appliquer hors https : sur une
    // instance locale, le site démarre sans clé boutique, et la commande doit
    // alors échouer proprement plutôt que repartir avec une clé plus large.
    process.env.NEXT_PUBLIC_SITE_URL = 'http://127.0.0.1:3000';
    delete process.env.ODOO_API_KEY_SHOP_CHECKOUT;
    resetServerEnvCache();
    const { cookie } = panierScelle();

    const response = await (await POST())(
      requete({ cartCookie: cookie, origin: 'http://127.0.0.1:3000' }),
    );

    expect(response.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('le site en https exige les deux clés dès la validation d’environnement', async () => {
    // Le filet de production. `ENVIRONMENT` ne peut pas servir de déclencheur :
    // il est absent de `.env.production`, donc toujours `development` là où il
    // compte. Le schéma de l'URL, lui, est l'adresse à laquelle le site répond.
    const { resetServerEnvCache: reset, getServerEnv } = await import('@/lib/env');
    for (const clef of ['ODOO_API_KEY_SHOP_READ', 'ODOO_API_KEY_SHOP_CHECKOUT'] as const) {
      const sauve = process.env[clef];
      delete process.env[clef];
      reset();
      expect(() => getServerEnv(), `${clef} manquante doit refuser`).toThrow(clef);
      process.env[clef] = sauve;
      reset();
    }
  });
});

describe('commande d’un client connecté', () => {
  function sessionValide() {
    return sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) },
      PORTAL_SECRET,
    );
  }

  it('passe par la route portail, avec la session et sans clé d’API', async () => {
    fetchMock.mockResolvedValueOnce(commandeOdoo());
    const { cookie } = panierScelle();

    const response = await (await POST())(
      requete({
        cartCookie: cookie,
        portalCookie: sessionValide(),
        body: { deliveryMode: 'delivery_to_confirm' },
      }),
    );

    expect(response.status).toBe(200);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://crm.checkout.invalid/api/v1/portal/shop/checkout');
    const entetes = init.headers as Record<string, string>;
    expect(entetes.Cookie).toBe(`session_id=${ODOO_SESSION}`);
    // Le point entier du dispositif : aucune clé ne part avec une session.
    expect(entetes['X-API-Key']).toBeUndefined();
  });

  it('n’envoie aucun bloc client, même si le navigateur en fournit un', async () => {
    fetchMock.mockResolvedValueOnce(commandeOdoo());
    const { cookie } = panierScelle();

    await (await POST())(
      requete({
        cartCookie: cookie,
        portalCookie: sessionValide(),
        body: { deliveryMode: 'pickup', customer: { ...INVITE, name: 'Quelqu’un d’Autre' } },
      }),
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const envoye = JSON.parse(init.body as string);
    expect(envoye.customer).toBeUndefined();
    expect(JSON.stringify(envoye)).not.toContain('Autre');
  });

  it('retombe en commande invité si la session est expirée', async () => {
    fetchMock.mockResolvedValueOnce(commandeOdoo());
    const { cookie } = panierScelle();
    const vieille = sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) - 60 * 60 * 24 },
      PORTAL_SECRET,
    );

    const response = await (await POST())(
      requete({ cartCookie: cookie, portalCookie: vieille }),
    );

    expect(response.status).toBe(200);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    // Un cookie périmé ne bloque pas la commande : le visiteur commande en invité
    // plutôt que d'être refusé pour une raison qu'il ne peut pas corriger.
    expect(url).toContain('/api/v1/shop/checkout');
  });
});

describe('panier', () => {
  it('refuse un cookie altéré sans créer de commande', async () => {
    const { cookie } = panierScelle();
    const morceaux = cookie.split('.');
    const tag = morceaux[3] as string;
    // Premier caractère du tag : le dernier ne porte que deux bits utiles.
    morceaux[3] = (tag[0] === 'A' ? 'B' : 'A') + tag.slice(1);

    const response = await (await POST())(
      requete({ cartCookie: morceaux.join('.') }),
    );

    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe('cart_invalid');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(cookiePose(response)).toBeNull();
  });

  it('refuse un panier scellé avec le secret du portail', async () => {
    const cart: Cart = { ...newCart(), lines: [{ reference: 'x-y', quantity: 1 }] };
    const response = await (await POST())(
      requete({ cartCookie: sealCart(cart, PORTAL_SECRET) }),
    );
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un panier portant un prix injecté', async () => {
    const contrebande = {
      ...newCart(),
      lines: [{ reference: 'filtre-a-huile', quantity: 1, price: 1 }],
    };
    const response = await (await POST())(
      requete({ cartCookie: sealCart(contrebande as unknown as Cart, CART_SECRET) }),
    );
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un panier absent', async () => {
    const response = await (await POST())(requete());
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un panier vide', async () => {
    const response = await (await POST())(
      requete({ cartCookie: sealCart(newCart(), CART_SECRET) }),
    );
    expect(response.status).toBe(422);
    expect((await response.json()).error.code).toBe('empty_cart');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('rotation du panier', () => {
  it('remplace le panier par un neuf, vide, après un succès', async () => {
    fetchMock.mockResolvedValueOnce(commandeOdoo());
    const { cookie, cart } = panierScelle();

    const response = await (await POST())(requete({ cartCookie: cookie }));

    const pose = cookiePose(response);
    expect(pose).toBeTruthy();
    const apres = unsealCart(pose as string, CART_SECRET);
    expect(apres.lines).toEqual([]);
    // Un identifiant neuf : l'ancien a produit sa commande et ne doit plus
    // pouvoir en produire une autre.
    expect(apres.cartId).not.toBe(cart.cartId);
  });

  it('tourne aussi quand Odoo a rendu une commande existante', async () => {
    // Rejeu : la commande existait déjà. Le panier tourne quand même, sinon le
    // client resterait bloqué avec un identifiant définitivement consommé.
    fetchMock.mockResolvedValueOnce(commandeOdoo({ replayed: true }));
    const { cookie, cart } = panierScelle();

    const response = await (await POST())(requete({ cartCookie: cookie }));

    expect(response.status).toBe(200);
    const apres = unsealCart(cookiePose(response) as string, CART_SECRET);
    expect(apres.cartId).not.toBe(cart.cartId);
  });

  it('ne touche pas au panier quand la commande échoue', async () => {
    fetchMock.mockResolvedValueOnce(erreurOdoo(409, 'unavailable_products'));
    const { cookie } = panierScelle();

    const response = await (await POST())(requete({ cartCookie: cookie }));

    expect(response.status).toBe(409);
    // Le panier survit : le client doit pouvoir le corriger.
    expect(cookiePose(response)).toBeNull();
  });

  it('un rejeu avec l’ancien identifiant retrouve la même commande', async () => {
    // Le cas où la réponse précédente n'a pas atteint le navigateur : il présente
    // encore l'ancien cookie. Odoo reconnaît l'identifiant et rend la même
    // commande — le BFF n'a rien de spécial à faire, et c'est le but.
    const { cookie, cart } = panierScelle();
    fetchMock
      .mockResolvedValueOnce(commandeOdoo())
      .mockResolvedValueOnce(commandeOdoo({ replayed: true }));

    const premiere = await (await POST())(requete({ cartCookie: cookie }));
    const seconde = await (await POST())(requete({ cartCookie: cookie }));

    expect((await premiere.json()).data.order.reference).toBe('S00042');
    expect((await seconde.json()).data.order.reference).toBe('S00042');
    // Les deux appels ont bien porté le même identifiant de panier.
    for (const appel of fetchMock.mock.calls) {
      const [, init] = appel as [string, RequestInit];
      expect(JSON.parse(init.body as string).cartId).toBe(cart.cartId);
    }
  });
});

describe('sécurité de la mutation', () => {
  it('refuse une origine étrangère', async () => {
    const { cookie } = panierScelle();
    const response = await (await POST())(
      requete({ cartCookie: cookie, origin: 'https://attaquant.invalid' }),
    );
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse une origine absente', async () => {
    const { cookie } = panierScelle();
    const response = await (await POST())(requete({ cartCookie: cookie, origin: null }));
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un corps trop volumineux avant de le désérialiser', async () => {
    const { cookie } = panierScelle();
    const response = await (await POST())(
      requete({ cartCookie: cookie, brut: JSON.stringify({ x: 'a'.repeat(9000) }) }),
    );
    expect(response.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un corps illisible', async () => {
    const { cookie } = panierScelle();
    const response = await (await POST())(
      requete({ cartCookie: cookie, brut: 'pas du json' }),
    );
    expect(response.status).toBe(400);
  });

  it('limite le débit par adresse', async () => {
    fetchMock.mockResolvedValue(commandeOdoo());
    let dernier: Response | null = null;
    // La onzième doit être refusée : la limite est de dix par minute.
    for (let i = 0; i < 11; i += 1) {
      const { cookie } = panierScelle();
      dernier = await (await POST())(requete({ cartCookie: cookie }));
    }
    expect(dernier?.status).toBe(429);
    expect(dernier?.headers.get('retry-after')).toBeTruthy();
  });

  it('n’est jamais mis en cache', async () => {
    fetchMock.mockResolvedValueOnce(commandeOdoo());
    const { cookie } = panierScelle();
    const response = await (await POST())(requete({ cartCookie: cookie }));
    expect(response.headers.get('cache-control')).toContain('no-store');
  });
});

describe('états d’erreur', () => {
  it.each([
    ['produits indisponibles', 409, 'unavailable_products', 409, 'unavailable_products'],
    ['compte portail existant', 409, 'portal_account_exists', 409, 'portal_account_exists'],
    ['panier vide côté Odoo', 422, 'empty_cart', 422, 'empty_cart'],
    ['champs interdits', 422, 'forbidden_fields', 422, 'invalid_request'],
    ['commande invalide', 422, 'invalid_checkout', 422, 'invalid_request'],
    ['boutique non configurée', 503, 'shop_unavailable', 503, 'unavailable'],
  ])('%s → HTTP %i', async (_nom, statutOdoo, codeOdoo, statutAttendu, codeAttendu) => {
    fetchMock.mockResolvedValueOnce(erreurOdoo(statutOdoo as number, codeOdoo as string));
    const { cookie } = panierScelle();

    const response = await (await POST())(requete({ cartCookie: cookie }));

    expect(response.status).toBe(statutAttendu);
    expect((await response.json()).error.code).toBe(codeAttendu);
  });

  it('traduit une réponse non-JSON en session refusée', async () => {
    // Mesuré : une route Odoo en `auth="user"` sans session répond par sa page de
    // connexion, en HTML et en 200. Le prendre pour une réponse d'API produirait
    // une erreur sans rapport avec la cause.
    fetchMock.mockResolvedValueOnce(
      new Response('<!DOCTYPE html><html><body>login</body></html>', { status: 200 }),
    );
    const { cookie } = panierScelle();
    const response = await (await POST())(
      requete({
        cartCookie: cookie,
        portalCookie: sealSession(
          { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) },
          PORTAL_SECRET,
        ),
        body: { deliveryMode: 'pickup' },
      }),
    );
    expect(response.status).toBe(401);
    expect((await response.json()).error.code).toBe('unauthenticated');
  });

  it('rend 503 quand Odoo est injoignable', async () => {
    fetchMock.mockRejectedValueOnce(new Error('ECONNREFUSED'));
    const { cookie } = panierScelle();
    const response = await (await POST())(requete({ cartCookie: cookie }));
    expect(response.status).toBe(503);
    expect(cookiePose(response)).toBeNull();
  });

  it('refuse une réponse d’Odoo qui ne respecte pas le contrat', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ success: true, data: { order: { reference: 'S1', cost: 12000 } } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const { cookie } = panierScelle();
    const response = await (await POST())(requete({ cartCookie: cookie }));
    expect(response.status).toBe(503);
  });
});

describe('aucun secret ne franchit la frontière', () => {
  it('ni clé, ni secret de scellement dans la réponse', async () => {
    fetchMock.mockResolvedValueOnce(commandeOdoo());
    const { cookie } = panierScelle();

    const response = await (await POST())(requete({ cartCookie: cookie }));
    const corps = await response.text();
    const entetes = JSON.stringify([...response.headers.entries()]);

    // Contrôle positif : ces chaînes sont bien cherchables.
    expect(CHECKOUT_KEY.length).toBeGreaterThan(24);
    expect(CART_SECRET.length).toBeGreaterThan(32);

    for (const secret of [CHECKOUT_KEY, READ_KEY, DEFAULT_KEY, CART_SECRET, PORTAL_SECRET]) {
      expect(corps).not.toContain(secret);
      expect(entetes).not.toContain(secret);
    }
  });
});
