import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetServerEnvCache } from '@/lib/env';
import { ShopGatewayError, ShopOdooGateway } from './odoo-shop';

/**
 * La traduction des échecs d'Odoo en codes de passerelle.
 *
 * Le seul but de ces tests : qu'une boutique volontairement fermée ne se remette
 * jamais à ressembler à une panne. Les deux étaient confondus, et la vitrine de
 * production annonçait un incident le jour de sa mise en service.
 */

const SITE = 'https://dallytrading.com';
let fetchMock: ReturnType<typeof vi.fn>;

function odooErreur(status: number, code: string) {
  return new Response(JSON.stringify({ success: false, error: { code } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = SITE;
  process.env.ODOO_URL = 'https://crm.essai.invalid';
  process.env.ODOO_DATABASE = 'essai';
  process.env.ODOO_API_KEY = 'cle-par-defaut-jamais-utilisee-ici-01234';
  process.env.ODOO_API_KEY_SHOP_READ = 'cle-de-lecture-boutique-0123456789abcd';
  process.env.ODOO_API_KEY_SHOP_CHECKOUT = 'cle-de-commande-boutique-0123456789ab';
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

async function catalogue() {
  return new ShopOdooGateway().getCatalogue('correlation-essai');
}

describe('boutique fermée volontairement', () => {
  it('shop_pricelist_missing devient not_open, jamais unavailable', async () => {
    fetchMock.mockResolvedValueOnce(odooErreur(503, 'shop_pricelist_missing'));
    await expect(catalogue()).rejects.toMatchObject({ code: 'not_open' });
  });

  it('reconnu au code, pas au statut HTTP', async () => {
    // Le statut est 503 dans les deux cas : c'est bien un état du serveur. Se
    // fier au statut remettrait les deux situations dans le même sac.
    const echec = async (code: string): Promise<ShopGatewayError> => {
      fetchMock.mockResolvedValueOnce(odooErreur(503, code));
      try {
        await catalogue();
      } catch (erreur) {
        if (erreur instanceof ShopGatewayError) return erreur;
        throw erreur;
      }
      throw new Error(`la passerelle aurait dû échouer pour ${code}`);
    };

    const ferme = await echec('shop_pricelist_missing');
    const casse = await echec('shop_unavailable');

    expect(ferme.status).toBe(503);
    expect(casse.status).toBe(503);
    expect(ferme.code).toBe('not_open');
    expect(casse.code).toBe('unavailable');
  });
});

describe('pannes réelles : l’état technique est conservé', () => {
  it('un tarif configuré mais introuvable reste unavailable', async () => {
    // Quelqu'un a décidé d'ouvrir et la configuration est cassée. L'annoncer
    // comme « en préparation » garantirait que personne ne la répare jamais.
    fetchMock.mockResolvedValueOnce(odooErreur(503, 'shop_unavailable'));
    await expect(catalogue()).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('Odoo injoignable → unavailable', async () => {
    fetchMock.mockRejectedValueOnce(new Error('ECONNREFUSED'));
    await expect(catalogue()).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('délai dépassé → timeout', async () => {
    const abort = new Error('aborted');
    abort.name = 'AbortError';
    fetchMock.mockRejectedValueOnce(abort);
    await expect(catalogue()).rejects.toMatchObject({ code: 'timeout' });
  });

  it('clé rejetée → forbidden', async () => {
    fetchMock.mockResolvedValueOnce(odooErreur(403, 'insufficient_scope'));
    await expect(catalogue()).rejects.toMatchObject({ code: 'forbidden' });
  });

  it('réponse hors contrat → invalid_response', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ success: true, data: { products: [{ cost: 12000 }] } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    await expect(catalogue()).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('réponse illisible → invalid_response', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('<html>pas du json</html>', { status: 200 }),
    );
    await expect(catalogue()).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('404 reste not_found, sans se transformer en boutique fermée', async () => {
    fetchMock.mockResolvedValueOnce(odooErreur(404, 'not_found'));
    await expect(
      new ShopOdooGateway().getProduct('un-slug', 'correlation-essai'),
    ).rejects.toMatchObject({ code: 'not_found' });
  });
});

describe('aucun repli sur la clé large', () => {
  it('la passerelle refuse de se construire sans sa propre clé', async () => {
    delete process.env.ODOO_API_KEY_SHOP_READ;
    process.env.NEXT_PUBLIC_SITE_URL = 'http://127.0.0.1:3000';
    resetServerEnvCache();
    expect(() => new ShopOdooGateway()).toThrow(ShopGatewayError);
  });

  it('part avec la clé de lecture, jamais la clé par défaut', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ success: true, data: { products: [], categories: [] } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    await catalogue();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const entetes = init.headers as Record<string, string>;
    expect(entetes['X-API-Key']).toBe(process.env.ODOO_API_KEY_SHOP_READ);
    expect(entetes['X-API-Key']).not.toBe(process.env.ODOO_API_KEY);
  });
});
