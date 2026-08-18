/**
 * La route qui sert les images, vue du navigateur.
 *
 * Deux propriétés dominent ce fichier et justifient sa longueur :
 *
 * * **l'indiscernabilité** — inconnu, non publié, sans image et boutique fermée
 *   doivent produire une réponse identique au dernier en-tête près, sans quoi la
 *   comparaison de deux réponses suffirait à énumérer un catalogue ;
 * * **le cache asymétrique** — une image publiée se garde un an, un refus ne se
 *   garde jamais, faute de quoi la non-publication d'aujourd'hui survivrait à la
 *   publication de demain dans un cache intermédiaire.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetServerEnvCache } from '@/lib/env';

const SITE = 'https://dallytrading.com';
const SHOP_READ_KEY = 'shop-read-key-must-stay-server-side-0123';
const SHOP_CHECKOUT_KEY = 'shop-checkout-key-must-stay-server-side-01';

/** Les huit premiers octets d'un PNG. `guess_mimetype` d'Odoo les reconnaît. */
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x01]);

let fetchMock: ReturnType<typeof vi.fn>;

/** Les octets exacts de la vue, sans la mémoire tampon qui peut la dépasser. */
function octets(vue: Uint8Array): ArrayBuffer {
  return vue.buffer.slice(vue.byteOffset, vue.byteOffset + vue.byteLength) as ArrayBuffer;
}

function odooImage(contentType = 'image/png', corps: Uint8Array = PNG) {
  return new Response(octets(corps), {
    status: 200,
    headers: { 'Content-Type': contentType },
  });
}

function odooErreur(status: number, code: string) {
  return new Response(JSON.stringify({ success: false, error: { code } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requete(reference: string, query = '') {
  return new Request(`${SITE}/api/shop/products/${reference}/image${query}`);
}

async function appeler(reference: string, query = '') {
  const { GET } = await import('./route');
  return GET(requete(reference, query), {
    params: Promise.resolve({ reference }),
  });
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = SITE;
  process.env.ENVIRONMENT = 'production';
  process.env.ODOO_URL = 'https://crm.shop.invalid';
  process.env.ODOO_DATABASE = 'test_db';
  process.env.ODOO_API_KEY = 'default-key-should-not-be-used-here-01234';
  process.env.ODOO_API_KEY_SHOP_READ = SHOP_READ_KEY;
  process.env.ODOO_API_KEY_SHOP_CHECKOUT = SHOP_CHECKOUT_KEY;
  process.env.ODOO_TIMEOUT_MS = '2000';
  process.env.PORTAL_SESSION_SECRET = 'p'.repeat(48);
  process.env.SHOP_CART_SECRET = 'c'.repeat(48);
  resetServerEnvCache();

  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('image d’un produit publié', () => {
  it('sert les octets avec le type déclaré par Odoo', async () => {
    fetchMock.mockResolvedValueOnce(odooImage());

    const response = await appeler('groupe-5kva', '?v=abcdef0123456789');

    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('image/png');
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(PNG);
  });

  it('garde l’image un an quand l’URL porte une version', async () => {
    fetchMock.mockResolvedValueOnce(odooImage());

    const response = await appeler('groupe-5kva', '?v=abcdef0123456789');

    // L'URL porte l'empreinte du contenu : elle change dès que l'image change,
    // donc la garder longtemps ne peut pas afficher une image périmée.
    const cache = response.headers.get('cache-control') ?? '';
    expect(cache).toContain('public');
    expect(cache).toContain('immutable');
    expect(cache).toContain('max-age=31536000');
  });

  it('raccourcit le cache quand l’URL n’a pas de version', async () => {
    fetchMock.mockResolvedValueOnce(odooImage());

    const response = await appeler('groupe-5kva');

    const cache = response.headers.get('cache-control') ?? '';
    expect(cache).toContain('public');
    expect(cache).not.toContain('immutable');
    // Sans jeton, l'URL ne suit plus le contenu : une image remplacée resterait
    // affichée pendant des mois.
    expect(cache).toContain('max-age=300');
  });

  it('interdit au navigateur de deviner un autre type', async () => {
    fetchMock.mockResolvedValueOnce(odooImage());

    const response = await appeler('groupe-5kva', '?v=abcdef0123456789');

    expect(response.headers.get('x-content-type-options')).toBe('nosniff');
    expect(response.headers.get('content-disposition')).toBe('inline');
  });

  it('demande à Odoo la taille validée, jamais celle reçue telle quelle', async () => {
    fetchMock.mockResolvedValueOnce(odooImage());

    await appeler('groupe-5kva', '?size=2048');

    // Une dimension hors liste retombe sur la taille par défaut : rien
    // d'arbitraire n'atteint Odoo, donc aucun redimensionnement à la demande.
    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toContain('size=card');
    expect(url).not.toContain('2048');
  });

  it('transmet la taille demandée quand elle est dans la liste', async () => {
    fetchMock.mockResolvedValueOnce(odooImage());

    await appeler('groupe-5kva', '?size=detail');

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('size=detail');
  });
});

describe('la clé reste côté serveur', () => {
  it('l’envoie à Odoo', async () => {
    fetchMock.mockResolvedValueOnce(odooImage());

    await appeler('groupe-5kva');

    // Contrôle positif : la clé circule bien vers Odoo. Sans lui, l'assertion
    // suivante serait satisfaite par une clé qui n'existe nulle part.
    const init = fetchMock.mock.calls[0]?.[1] as { headers: Record<string, string> };
    expect(init.headers['X-API-Key']).toBe(SHOP_READ_KEY);
  });

  it('ne la laisse dans aucun en-tête de la réponse', async () => {
    fetchMock.mockResolvedValueOnce(odooImage());

    const response = await appeler('groupe-5kva');

    const entetes = JSON.stringify([...response.headers.entries()]);
    expect(entetes).not.toContain(SHOP_READ_KEY);
    expect(entetes).not.toContain(SHOP_CHECKOUT_KEY);
    expect(entetes.toLowerCase()).not.toContain('x-api-key');
    // L'adresse interne d'Odoo ne doit pas non plus transparaître.
    expect(entetes).not.toContain('crm.shop.invalid');
  });
});

describe('le refus est unique', () => {
  const CAS: Array<[string, () => Response]> = [
    ['produit inconnu', () => odooErreur(404, 'not_found')],
    ['produit non publié', () => odooErreur(404, 'not_found')],
    ['boutique fermée', () => odooErreur(503, 'shop_pricelist_missing')],
  ];

  for (const [nom, reponse] of CAS) {
    it(`répond 404 sans corps — ${nom}`, async () => {
      fetchMock.mockResolvedValueOnce(reponse());

      const response = await appeler('peu-importe', '?v=abcdef0123456789');

      expect(response.status).toBe(404);
      expect(await response.text()).toBe('');
    });
  }

  it('produit des réponses identiques pour l’inconnu et le non publié', async () => {
    // La propriété que tout le reste sert : deux réponses comparées ne doivent
    // rien apprendre. Un statut identique ne suffirait pas — un en-tête de plus
    // d'un côté trahirait le cas.
    fetchMock.mockResolvedValueOnce(odooErreur(404, 'not_found'));
    const inconnu = await appeler('slug-jamais-existe');

    fetchMock.mockResolvedValueOnce(odooErreur(404, 'not_found'));
    const nonPublie = await appeler('produit-en-preparation');

    expect(inconnu.status).toBe(nonPublie.status);
    expect([...inconnu.headers.entries()].sort()).toEqual(
      [...nonPublie.headers.entries()].sort(),
    );
    expect(await inconnu.text()).toBe(await nonPublie.text());
  });

  it('ne met jamais un refus en cache', async () => {
    fetchMock.mockResolvedValueOnce(odooErreur(404, 'not_found'));

    const response = await appeler('produit-en-preparation');

    // Un produit non publié aujourd'hui peut l'être demain. Un 404 gardé par un
    // intermédiaire survivrait à la publication.
    expect(response.headers.get('cache-control')).toBe('no-store');
  });

  it('distingue une panne d’ERP d’une absence de produit', async () => {
    /*
     * Correction d'une décision antérieure, prise après mesure.
     *
     * Cette route rendait 404 pour tout, panne comprise. En E2E, sous charge,
     * l'Odoo de test refusait quelques appels : une photo bien présente
     * devenait alors introuvable, et la suite rougissait par intermittence sans
     * que rien ne désigne la cause.
     *
     * L'indiscernabilité qui compte est intacte — inconnu et non publié restent
     * deux 404 identiques. Seul l'état de l'ERP devient visible, et il ne dit
     * rien sur l'existence d'un produit.
     */
    fetchMock.mockResolvedValueOnce(odooErreur(500, 'internal_error'));

    const response = await appeler('groupe-5kva');

    expect(response.status).toBe(502);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.text()).toBe('');
  });

  it('ne dit pas pourquoi c’est absent', async () => {
    fetchMock.mockResolvedValueOnce(odooErreur(503, 'shop_pricelist_missing'));

    const response = await appeler('groupe-5kva');

    const tout = (await response.text()) + JSON.stringify([...response.headers]);
    expect(tout).not.toContain('pricelist');
    expect(tout).not.toContain('not_found');
    expect(tout).not.toContain('503');
  });
});

describe('le type de la réponse est contraint', () => {
  /*
   * Une image de mauvais type est un problème de contenu, pas de disponibilité.
   *
   * Elle rejoint donc le 404 indistinguable, avec « inconnu » et « non
   * publié » : du point de vue du visiteur, il n'y a pas d'image. Seule une
   * panne de transport vers l'ERP produit un 502 — voir le test dédié plus
   * haut. La distinction s'est imposée en corrigeant le masquage des pannes :
   * regrouper les deux aurait fait d'un SVG déposé par erreur une alerte
   * d'exploitation, et d'un ERP muet une photo inexistante.
   */
  it('refuse un contenu qui n’est pas une image', async () => {
    // Odoo contrôle déjà le type à partir des octets. Ce second contrôle protège
    // une autre frontière : rien de ce qui sort d'ici ne doit pouvoir devenir un
    // document exécutable servi depuis notre origine.
    fetchMock.mockResolvedValueOnce(
      new Response('<script>alert(1)</script>', {
        status: 200,
        headers: { 'Content-Type': 'text/html' },
      }),
    );

    const response = await appeler('groupe-5kva');

    expect(response.status).toBe(404);
    // Le refus ne pose aucun type : il n'y a pas de corps à typer, et le HTML
    // reçu d'Odoo n'est donc relayé ni en contenu ni en en-tête.
    expect(response.headers.get('content-type')).toBeNull();
    expect(await response.text()).toBe('');
  });

  it('refuse un SVG, même annoncé comme image', async () => {
    fetchMock.mockResolvedValueOnce(
      odooImage('image/svg+xml', new TextEncoder().encode('<svg onload="x()"/>')),
    );

    const response = await appeler('groupe-5kva');

    expect(response.status).toBe(404);
  });

  it('accepte les types de la liste blanche', async () => {
    for (const type of ['image/png', 'image/jpeg', 'image/webp', 'image/gif']) {
      fetchMock.mockResolvedValueOnce(odooImage(type));
      const response = await appeler('groupe-5kva');
      expect(response.status, type).toBe(200);
      expect(response.headers.get('content-type')).toBe(type);
    }
  });
});
