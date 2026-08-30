import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';

import {
  magasinCookies,
  reinitialiserCookies,
} from '@/test/faux-cookies';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<
    typeof import('@/lib/auth/odoo-ops')
  >();
  return {
    ...original,
    opsGet: vi.fn(),
    opsPost: vi.fn(),
  };
});

const { OPS_COOKIE, sealSession } = await import(
  '@/lib/auth/session'
);
const {
  opsGet,
  opsPost,
  OpsGatewayError,
} = await import('@/lib/auth/odoo-ops');
const { resetRateLimits } = await import(
  '@/lib/rate-limit'
);
const { POST } = await import(
  '@/app/api/intakes/route'
);
const { GET } = await import(
  '@/app/api/tariff-families/route'
);

const DEMANDE = {
  request_uuid: '11111111-2222-4333-8444-555555555555',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  customer_reference: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
  received_on: '2026-08-28',
  line: {
    line_uuid: '99999999-8888-4777-8666-555555555555',
    package_type: 'parcel',
    goods_category: 'Non alimentaire',
    description: 'Savon',
    quantity: 1,
    announced_weight_kg: 13,
    exact_weight_kg: 13.5,
    length_cm: null,
    width_cm: null,
    height_cm: null,
    billing_method: 'real',
    tariff_family_code: 'non_food',
    customs_value_xof: 25000,
  },
};

const RESULTAT = {
  status: 'created',
  intake: {
    reference: 'AIR-DSS-CDG-2026-002-A001',
    local_reference: 'A001',
    consolidation_reference: 'AIR-DSS-CDG-2026-002',
    state: 'goods_received',
    received_on: '2026-08-28',
    line: {
      reference: DEMANDE.line.line_uuid,
      description: 'Savon',
      goods_category: 'Non alimentaire',
      quantity: 1,
      exact_weight_kg: 13.5,
      volume_cbm: 0,
      billing_method: 'real',
      tariff_family_code: 'non_food',
      customs_value_xof: 25000,
      pricing_status: 'automatic',
      billable_weight_kg: 13.5,
      applied_unit_price_eur: 5,
      transport_amount_eur: 67.5,
    },
    totals: {
      weight_kg: 13.5,
      volume_cbm: 0,
      transport_amount_eur: 67.5,
    },
  },
};

function avecSession() {
  magasinCookies.set(
    OPS_COOKIE,
    sealSession({
      odooSessionId: 'sX',
      issuedAt: Date.now(),
    }),
  );
}

function requete(
  corps: unknown,
  headers: Record<string, string> = {},
): Request {
  return new Request(
    'https://ops.example.test/api/intakes',
    {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-forwarded-for': '203.0.113.9',
        ...headers,
      },
      body: (
        typeof corps === 'string'
          ? corps
          : JSON.stringify(corps)
      ),
    },
  );
}

beforeEach(() => {
  reinitialiserCookies();
  resetRateLimits();
  vi.mocked(opsPost).mockReset();
  vi.mocked(opsGet).mockReset();
});

describe('POST /api/intakes', () => {
  it('relaie la demande stricte avec la session seule', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue(RESULTAT);
    const reponse = await POST(requete(DEMANDE));
    expect(reponse.status).toBe(200);
    expect(opsPost).toHaveBeenCalledWith(
      'intakes',
      expect.objectContaining({
        request_uuid: DEMANDE.request_uuid,
      }),
      'sX',
      expect.any(String),
    );
  });

  it.each([
    'partner_id',
    'shipment_id',
    'collection_local_ref',
    'transport_mode',
    'manual_unit_price_eur',
    'state',
  ])('refuse %s avant Odoo', async (cle) => {
    avecSession();
    const reponse = await POST(
      requete({ ...DEMANDE, [cle]: 1 }),
    );
    expect(reponse.status).toBe(400);
    expect(opsPost).not.toHaveBeenCalled();
  });

  it('refuse origine, type et absence de session', async () => {
    avecSession();
    expect(
      (await POST(requete(
        DEMANDE,
        { origin: 'https://ailleurs.test' },
      ))).status,
    ).toBe(403);
    expect(
      (await POST(requete(
        DEMANDE,
        { 'content-type': 'text/plain' },
      ))).status,
    ).toBe(415);
    reinitialiserCookies();
    expect(
      (await POST(requete(DEMANDE))).status,
    ).toBe(401);
  });

  it('rend les erreurs métier stables', async () => {
    avecSession();
    for (const [erreur, statut] of [
      [
        new OpsGatewayError(
          'not_found', '', 'customer_not_found',
        ),
        404,
      ],
      [
        new OpsGatewayError(
          'conflict', '', 'consolidation_not_open',
        ),
        409,
      ],
      [
        new OpsGatewayError(
          'conflict', '', 'idempotency_conflict',
        ),
        409,
      ],
    ] as const) {
      vi.mocked(opsPost).mockRejectedValueOnce(erreur);
      expect(
        (await POST(requete(DEMANDE))).status,
      ).toBe(statut);
    }
  });

  it('ne compte pas un rejeu UUID comme une nouvelle réception', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue(RESULTAT);
    for (let index = 0; index < 100; index += 1) {
      expect(
        (await POST(requete(DEMANDE))).status,
      ).toBe(200);
    }
  });

  it('refuse un DTO enrichi d’un ID Odoo', async () => {
    avecSession();
    vi.mocked(opsPost).mockResolvedValue({
      ...RESULTAT,
      shipment_id: 42,
    });
    expect(
      (await POST(requete(DEMANDE))).status,
    ).toBe(503);
  });

  it('n’expose ni clé API ni calcul A001', () => {
    const source = POST.toString();
    expect(source).not.toContain('API_KEY');
    expect(source).not.toContain('collection_local_ref');
    expect(source).not.toContain('A001');
  });
});

describe('GET /api/tariff-families', () => {
  const getRequest = () => new Request(
    'https://ops.example.test/api/tariff-families',
    {
      headers: {
        'x-forwarded-for': '203.0.113.9',
      },
    },
  );

  it('relaie seulement code et nom', async () => {
    avecSession();
    vi.mocked(opsGet).mockResolvedValue({
      tariff_families: [{
        code: 'non_food',
        name: 'Non alimentaire',
      }],
    });
    const reponse = await GET(getRequest());
    expect(reponse.status).toBe(200);
    expect(opsGet).toHaveBeenCalledWith(
      'tariff-families', 'sX', expect.any(String),
    );
  });

  it('refuse sans session et ne met jamais en cache', async () => {
    expect((await GET(getRequest())).status).toBe(401);
    avecSession();
    vi.mocked(opsGet).mockResolvedValue({
      tariff_families: [],
    });
    expect(
      (await GET(getRequest())).headers.get('cache-control'),
    ).toBe('no-store');
  });
});

