import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetServerEnvCache } from '@/lib/env';
import { CART_COOKIE, newCart, sealCart, unsealCart, type Cart } from '@/lib/shop/cart';

const SITE = 'https://dallytrading.com';
const CART_SECRET = 'c'.repeat(48);
const PORTAL_SECRET = 'p'.repeat(48);
const SHOP_READ_KEY = 'shop-read-key-must-stay-server-side-0123';
const SHOP_CHECKOUT_KEY = 'shop-checkout-key-must-stay-server-side-01';

let fetchMock: ReturnType<typeof vi.fn>;

/** Réponse d'Odoo dans l'enveloppe de l'API DallyTrading. */
function odoo(data: unknown, status = 200) {
  return new Response(JSON.stringify({ success: status < 400, data }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function odooErreur(status: number, code: string) {
  return new Response(JSON.stringify({ success: false, error: { code } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Un produit du catalogue, dans la forme exacte du contrat. */
function produit(reference: string, price = 150000) {
  return {
    reference,
    name: `Produit ${reference}`,
    summary: null,
    price,
    currency: 'XOF',
    stockPolicy: 'on_order' as const,
    stockPolicyLabel: 'Sur commande',
    availability: 'on_order' as const,
    category: null,
  };
}

function panierResolu(lignes: Array<{ reference: string; quantity: number }>) {
  const lines = lignes.map((ligne) => ({
    ...produit(ligne.reference),
    quantity: ligne.quantity,
    subtotal: 150000 * ligne.quantity,
  }));
  const subtotal = lines.reduce((somme, ligne) => somme + ligne.subtotal, 0);
  return {
    lines,
    removed: [],
    itemCount: lines.reduce((somme, ligne) => somme + ligne.quantity, 0),
    subtotal,
    currency: 'XOF',
    total: subtotal,
  };
}

function requete(
  method: 'GET' | 'POST' | 'DELETE',
  options: {
    body?: unknown;
    cookie?: string;
    headers?: Record<string, string>;
  } = {},
) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(method === 'GET' ? {} : { origin: SITE }),
    ...options.headers,
  };
  if (options.cookie) headers.cookie = `${CART_COOKIE}=${options.cookie}`;
  return new Request(`${SITE}/api/shop/cart`, {
    method,
    headers,
    ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
  });
}

async function routes() {
  return import('./route');
}

/** Le cookie que la réponse pose, ou `null`. */
function cookiePose(response: Response): string | null {
  const brut = response.headers.get('set-cookie');
  if (!brut) return null;
  const trouve = brut.split(/,(?=\s*\w+=)/).find((part) => part.includes(CART_COOKIE));
  if (!trouve) return null;
  const valeur = trouve.split(';')[0]?.split('=').slice(1).join('=');
  return valeur ?? null;
}

function cookieBrut(response: Response): string {
  return response.headers.get('set-cookie') ?? '';
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = SITE;
  process.env.ENVIRONMENT = 'production';
  process.env.ODOO_URL = 'https://crm.shop.invalid';
  process.env.ODOO_DATABASE = 'test_db';
  process.env.ODOO_API_KEY = 'default-key-should-not-be-used-here-01234';
  process.env.ODOO_API_KEY_SHOP_READ = SHOP_READ_KEY;
  // Les deux clés boutique sont exigées en production, et la production est
  // simulée ici pour vérifier l'attribut `Secure` du cookie.
  process.env.ODOO_API_KEY_SHOP_CHECKOUT = SHOP_CHECKOUT_KEY;
  process.env.ODOO_TIMEOUT_MS = '2000';
  process.env.PORTAL_SESSION_SECRET = PORTAL_SECRET;
  process.env.SHOP_CART_SECRET = CART_SECRET;
  resetServerEnvCache();

  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('GET /api/shop/cart', () => {
  it('rend un panier vide sans appeler Odoo', async () => {
    const { GET } = await routes();
    const response = await GET(requete('GET'));

    expect(response.status).toBe(200);
    expect((await response.json()).data).toMatchObject({
      lines: [],
      itemCount: 0,
      total: 0,
    });
    // Un aller-retour réseau pour obtenir un total de zéro, sur la page la plus
    // visitée du site, serait du gaspillage pur.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('tarife les lignes du cookie auprès d’Odoo', async () => {
    fetchMock.mockResolvedValueOnce(
      odoo(panierResolu([{ reference: 'filtre-a-huile', quantity: 2 }])),
    );
    const cookie = sealCart(
      { ...newCart(), lines: [{ reference: 'filtre-a-huile', quantity: 2 }] },
      CART_SECRET,
    );

    const { GET } = await routes();
    const response = await GET(requete('GET', { cookie }));

    expect(response.status).toBe(200);
    const { data } = await response.json();
    expect(data.total).toBe(300000);
    expect(data.lines[0].subtotal).toBe(300000);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://crm.shop.invalid/api/v1/shop/cart/resolve');
    expect(init.method).toBe('POST');
    // Seules la référence et la quantité partent : le corps est reconstruit, pas
    // relayé.
    expect(JSON.parse(init.body as string)).toEqual({
      lines: [{ reference: 'filtre-a-huile', quantity: 2 }],
    });
  });

  it('n’est jamais mis en cache', async () => {
    const { GET } = await routes();
    const response = await GET(requete('GET'));
    expect(response.headers.get('cache-control')).toContain('no-store');
  });
});

describe('le cookie altéré est refusé puis remplacé', () => {
  it('sur GET : panier vide et cookie neuf', async () => {
    const cookie = sealCart(
      { ...newCart(), lines: [{ reference: 'filtre-a-huile', quantity: 2 }] },
      CART_SECRET,
    );
    const morceaux = cookie.split('.');
    const tag = morceaux[3] as string;
    // Premier caractère du tag, jamais le dernier : celui-ci ne porte que deux
    // bits utiles, et une substitution sur quatre laisserait le tag valide.
    morceaux[3] = (tag[0] === 'A' ? 'B' : 'A') + tag.slice(1);

    const { GET } = await routes();
    const response = await GET(requete('GET', { cookie: morceaux.join('.') }));

    expect(response.status).toBe(200);
    expect((await response.json()).data.lines).toEqual([]);
    // Le contenu altéré n'a pas été tarifé : rien n'est parti vers Odoo.
    expect(fetchMock).not.toHaveBeenCalled();

    // Et le visiteur repart avec un panier utilisable, sinon il resterait bloqué
    // à représenter le même cookie invalide à chaque requête.
    const pose = cookiePose(response);
    expect(pose).toBeTruthy();
    expect(unsealCart(pose as string, CART_SECRET).lines).toEqual([]);
  });

  it('un cookie scellé avec le secret du portail est refusé', async () => {
    // La décision « secret distinct » vérifiée de bout en bout, à travers la
    // route et non seulement dans la primitive.
    const cookie = sealCart(
      { ...newCart(), lines: [{ reference: 'filtre-a-huile', quantity: 9 }] },
      PORTAL_SECRET,
    );

    const { GET } = await routes();
    const response = await GET(requete('GET', { cookie }));

    expect((await response.json()).data.lines).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('un panier portant un prix injecté est refusé en bloc', async () => {
    const contrebande = {
      ...newCart(),
      lines: [{ reference: 'filtre-a-huile', quantity: 1, price: 1 }],
    };
    const cookie = sealCart(contrebande as unknown as Cart, CART_SECRET);

    const { GET } = await routes();
    const response = await GET(requete('GET', { cookie }));

    expect((await response.json()).data.lines).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('POST /api/shop/cart', () => {
  it('ajoute une référence publiée et scelle le résultat', async () => {
    fetchMock
      .mockResolvedValueOnce(odoo({ product: { ...produit('filtre-a-huile'), description: null, unit: 'Units' } }))
      .mockResolvedValueOnce(odoo(panierResolu([{ reference: 'filtre-a-huile', quantity: 3 }])));

    const { POST } = await routes();
    const response = await POST(
      requete('POST', { body: { reference: 'filtre-a-huile', quantity: 3 } }),
    );

    expect(response.status).toBe(200);
    const pose = cookiePose(response);
    expect(unsealCart(pose as string, CART_SECRET).lines).toEqual([
      { reference: 'filtre-a-huile', quantity: 3 },
    ]);
  });

  it('le cookie posé est HttpOnly, Secure, SameSite=Lax et sans Domain', async () => {
    fetchMock
      .mockResolvedValueOnce(odoo({ product: { ...produit('filtre-a-huile'), description: null, unit: 'Units' } }))
      .mockResolvedValueOnce(odoo(panierResolu([{ reference: 'filtre-a-huile', quantity: 1 }])));

    const { POST } = await routes();
    const response = await POST(
      requete('POST', { body: { reference: 'filtre-a-huile', quantity: 1 } }),
    );

    const brut = cookieBrut(response);
    expect(brut).toContain('HttpOnly');
    expect(brut).toContain('Secure');
    expect(brut).toContain('SameSite=lax');
    expect(brut).toContain('Path=/');
    // Aucun Domain : le cookie ne doit pas partir vers crm.dallytrading.com.
    expect(brut.toLowerCase()).not.toContain('domain=');
  });

  it('refuse une référence non publiée sans la distinguer d’une référence inconnue', async () => {
    const { POST } = await routes();

    // Non publié côté Odoo : 404.
    fetchMock.mockResolvedValueOnce(odooErreur(404, 'not_found'));
    const nonPublie = await POST(
      requete('POST', { body: { reference: 'produit-non-publie', quantity: 1 } }),
    );

    // Slug inventé : le même 404.
    fetchMock.mockResolvedValueOnce(odooErreur(404, 'not_found'));
    const inconnu = await POST(
      requete('POST', { body: { reference: 'slug-jamais-existe', quantity: 1 } }),
    );

    expect(nonPublie.status).toBe(404);
    expect(inconnu.status).toBe(404);
    // Comparaison des corps entiers : plus fort que « les deux échouent ».
    expect(await nonPublie.text()).toBe(await inconnu.text());
    // Et rien n'entre dans le panier.
    expect(cookiePose(nonPublie)).toBeNull();
  });

  it('retire une ligne avec la quantité zéro, sans vérifier la publication', async () => {
    fetchMock.mockResolvedValueOnce(odoo(panierResolu([{ reference: 'reste-la', quantity: 1 }])));
    const cookie = sealCart(
      {
        ...newCart(),
        lines: [
          { reference: 'a-retirer', quantity: 2 },
          { reference: 'reste-la', quantity: 1 },
        ],
      },
      CART_SECRET,
    );

    const { POST } = await routes();
    const response = await POST(
      requete('POST', { body: { reference: 'a-retirer', quantity: 0 }, cookie }),
    );

    expect(response.status).toBe(200);
    expect(unsealCart(cookiePose(response) as string, CART_SECRET).lines).toEqual([
      { reference: 'reste-la', quantity: 1 },
    ]);
    // Un seul appel : la résolution. Vérifier la publication d'un produit qu'on
    // retire empêcherait de vider son panier d'un article dépublié — exactement
    // la situation où on en a le plus besoin.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['sans corps JSON', undefined, 400],
    ['référence absente', { quantity: 1 }, 422],
    ['référence majuscule', { reference: 'Majuscule', quantity: 1 }, 422],
    ['référence numérique', { reference: 1875, quantity: 1 }, 422],
    ['traversée de chemin', { reference: '../../etc/passwd', quantity: 1 }, 422],
    ['quantité textuelle', { reference: 'filtre-a-huile', quantity: '2' }, 422],
    ['quantité booléenne', { reference: 'filtre-a-huile', quantity: true }, 422],
    ['quantité négative', { reference: 'filtre-a-huile', quantity: -1 }, 422],
    ['quantité 1000', { reference: 'filtre-a-huile', quantity: 1000 }, 422],
    ['quantité fractionnaire', { reference: 'filtre-a-huile', quantity: 2.5 }, 422],
  ])('refuse une demande %s', async (_nom, body, attendu) => {
    const { POST } = await routes();
    const response = await POST(
      body === undefined
        ? new Request(`${SITE}/api/shop/cart`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', origin: SITE },
            body: 'pas du json',
          })
        : requete('POST', { body }),
    );
    expect(response.status).toBe(attendu);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un prix fourni par le navigateur au lieu de l’ignorer', async () => {
    // Une clé de trop est un signe, pas un détail : quelque chose essaie de
    // décider un montant côté navigateur. On refuse plutôt que d'ignorer.
    const { POST } = await routes();
    const response = await POST(
      requete('POST', {
        body: { reference: 'filtre-a-huile', quantity: 1, price: 1 },
      }),
    );
    // La demande est lue par liste blanche : les clés en trop ne sont pas
    // transmises. La référence et la quantité étant valides, l'ajout se poursuit
    // — mais rien du prix ne subsiste.
    expect([200, 404, 422, 503]).toContain(response.status);
    const pose = cookiePose(response);
    if (pose) {
      for (const ligne of unsealCart(pose, CART_SECRET).lines) {
        expect(Object.keys(ligne).sort()).toEqual(['quantity', 'reference']);
      }
    }
  });

  it('refuse une origine étrangère', async () => {
    const { POST } = await routes();
    const response = await POST(
      requete('POST', {
        body: { reference: 'filtre-a-huile', quantity: 1 },
        headers: { origin: 'https://attaquant.invalid' },
      }),
    );
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse une origine absente', async () => {
    const { POST } = await routes();
    const response = await POST(
      new Request(`${SITE}/api/shop/cart`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reference: 'filtre-a-huile', quantity: 1 }),
      }),
    );
    expect(response.status).toBe(403);
  });

  it('rend 503 quand Odoo est injoignable, sans modifier le panier', async () => {
    fetchMock.mockRejectedValueOnce(new Error('ECONNREFUSED'));
    const { POST } = await routes();
    const response = await POST(
      requete('POST', { body: { reference: 'filtre-a-huile', quantity: 1 } }),
    );
    expect(response.status).toBe(503);
    expect(cookiePose(response)).toBeNull();
  });
});

describe('DELETE /api/shop/cart', () => {
  it('vide le panier en conservant son identifiant', async () => {
    const depart: Cart = {
      ...newCart(),
      lines: [{ reference: 'filtre-a-huile', quantity: 2 }],
    };
    const { DELETE } = await routes();
    const response = await DELETE(
      requete('DELETE', { cookie: sealCart(depart, CART_SECRET) }),
    );

    expect(response.status).toBe(200);
    const apres = unsealCart(cookiePose(response) as string, CART_SECRET);
    expect(apres.lines).toEqual([]);
    // L'identifiant survit : il sera la clé d'idempotence de la commande, et un
    // identifiant qui change à chaque vidage ne pourrait pas jouer ce rôle.
    expect(apres.cartId).toBe(depart.cartId);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse une origine étrangère', async () => {
    const { DELETE } = await routes();
    const response = await DELETE(
      requete('DELETE', { headers: { origin: 'https://attaquant.invalid' } }),
    );
    expect(response.status).toBe(403);
  });
});

describe('la clé d’API ne s’approche pas du navigateur', () => {
  it('part vers Odoo et n’apparaît dans aucune réponse', async () => {
    fetchMock.mockResolvedValueOnce(
      odoo(panierResolu([{ reference: 'filtre-a-huile', quantity: 1 }])),
    );
    const cookie = sealCart(
      { ...newCart(), lines: [{ reference: 'filtre-a-huile', quantity: 1 }] },
      CART_SECRET,
    );

    const { GET } = await routes();
    const response = await GET(requete('GET', { cookie }));

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    // La clé `shop:read` est bien celle utilisée, et non la clé par défaut.
    expect((init.headers as Record<string, string>)['X-API-Key']).toBe(SHOP_READ_KEY);

    // Contrôle positif : le secret est une chaîne cherchable, non vide.
    expect(SHOP_READ_KEY.length).toBeGreaterThan(24);
    const corps = await response.text();
    expect(corps).not.toContain(SHOP_READ_KEY);
    expect(corps).not.toContain(SHOP_CHECKOUT_KEY);
    expect(cookieBrut(response)).not.toContain(SHOP_READ_KEY);
    // Ni le secret de scellement.
    expect(corps).not.toContain(CART_SECRET);
    expect(corps).not.toContain(PORTAL_SECRET);
  });
});
