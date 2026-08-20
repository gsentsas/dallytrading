import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetServerEnvCache } from '@/lib/env';
import { ShopDeliveryGateway, ShopDeliveryGatewayError } from './odoo-delivery';

const SITE = 'https://dallytrading.com';
const READ_KEY = 'cle-de-lecture-boutique-0123456789abcd';
const DEFAULT_KEY = 'cle-par-defaut-jamais-utilisee-ici-01234';
let fetchMock: ReturnType<typeof vi.fn>;

function success(data: unknown) {
  return new Response(JSON.stringify({ success: true, data }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = SITE;
  process.env.ODOO_URL = 'https://crm.essai.invalid';
  process.env.ODOO_DATABASE = 'essai';
  process.env.ODOO_API_KEY = DEFAULT_KEY;
  process.env.ODOO_API_KEY_SHOP_READ = READ_KEY;
  process.env.ODOO_API_KEY_SHOP_CHECKOUT = 'cle-checkout-0123456789abcdefghijkl';
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

async function methods() {
  return new ShopDeliveryGateway().getMethods('correlation-livraison');
}

describe('passerelle des méthodes de remise', () => {
  it('utilise uniquement la clé shop:read', async () => {
    fetchMock.mockResolvedValueOnce(success({ methods: [] }));

    await methods();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://crm.essai.invalid/api/v1/shop/delivery-methods');
    const headers = init.headers as Record<string, string>;
    expect(headers['X-API-Key']).toBe(READ_KEY);
    expect(headers['X-API-Key']).not.toBe(DEFAULT_KEY);
    expect(headers['X-Correlation-Id']).toBe('correlation-livraison');
  });

  it('refuse explicitement de fonctionner sans clé dédiée', async () => {
    process.env.NEXT_PUBLIC_SITE_URL = 'http://127.0.0.1:3000';
    delete process.env.ODOO_API_KEY_SHOP_READ;
    resetServerEnvCache();

    await expect(methods()).rejects.toBeInstanceOf(ShopDeliveryGatewayError);
    await expect(methods()).rejects.toMatchObject({ code: 'misconfigured' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('accepte la projection publique attendue', async () => {
    fetchMock.mockResolvedValueOnce(success({
      methods: [{
        code: 'pickup',
        name: 'Retrait sur place',
        kind: 'pickup',
        requiresAddress: false,
        feePolicy: 'free',
        feeAmount: 0,
        currency: 'XOF',
        help: 'Retrait dans nos locaux.',
      }],
    }));

    const result = await methods();
    expect(result).toHaveLength(1);
    expect(result[0]?.code).toBe('pickup');
  });

  it('refuse un identifiant ORM ou un champ interne dans la réponse', async () => {
    fetchMock.mockResolvedValueOnce(success({
      methods: [{
        code: 'pickup',
        name: 'Retrait',
        kind: 'pickup',
        requiresAddress: false,
        feePolicy: 'free',
        feeAmount: 0,
        currency: 'XOF',
        help: '',
        id: 42,
      }],
    }));

    await expect(methods()).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('traduit une réponse non JSON en invalid_response', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>erreur</html>', { status: 200 }));
    await expect(methods()).rejects.toMatchObject({ code: 'invalid_response' });
  });

  it('traduit une panne réseau en unavailable', async () => {
    fetchMock.mockRejectedValueOnce(new Error('ECONNREFUSED'));
    await expect(methods()).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('traduit un timeout en timeout', async () => {
    const error = new Error('aborted');
    error.name = 'AbortError';
    fetchMock.mockRejectedValueOnce(error);
    await expect(methods()).rejects.toMatchObject({ code: 'timeout' });
  });
});
