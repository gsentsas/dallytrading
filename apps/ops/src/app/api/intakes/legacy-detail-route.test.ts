import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * La fiche en lecture seule, vue du BFF.
 *
 * Ce qui lui est propre : son budget de débit, distinct de celui de la
 * recherche, et le fait qu'aucun verbe d'écriture n'existe sur ce chemin.
 */

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/ops/legacy-intake', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/ops/legacy-intake')>();
  return { ...original, fetchLegacyIntake: vi.fn() };
});

const { readOpsSession } = await import('@/lib/auth/auth');
const { fetchLegacyIntake } = await import('@/lib/ops/legacy-intake');
const { OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const {
  OPS_LEGACY_DETAIL_SESSION, cleLegacyDetailSession, cleRechercheSession,
  peekRateLimit, resetRateLimits,
} = await import('@/lib/rate-limit');
const routeModule = await import(
  '@/app/api/intakes/[reference]/legacy-detail/route');

const REFERENCE = 'AIR-DSS-CDG-2026-002-A015';

const FICHE = {
  readonly: true as const,
  reference: REFERENCE, local_reference: 'A015',
  state: 'goods_received', state_label: 'Goods received',
  transport_mode: 'air', direction: 'export',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  received_on: '2026-08-20',
  customer: { name: 'Awa Legacy', phone: '+221 77 400 11 22' },
  lines: [], totals: { lines_count: 0, weight_kg: 0, volume_cbm: 0 },
  payments: [], payment_summary: [],
};

function appel(reference = REFERENCE, requete = ''): Promise<Response> {
  return routeModule.GET(
    new Request(
      `https://ops.test/api/intakes/${encodeURIComponent(reference)}/legacy-detail${requete}`),
    { params: Promise.resolve({ reference: encodeURIComponent(reference) }) },
  ) as unknown as Promise<Response>;
}

beforeEach(() => {
  resetRateLimits();
  vi.mocked(readOpsSession).mockReset();
  vi.mocked(fetchLegacyIntake).mockReset();
  vi.mocked(readOpsSession).mockResolvedValue({ odooSessionId: 'session', issuedAt: 1 });
  vi.mocked(fetchLegacyIntake).mockResolvedValue(FICHE);
});

describe('les gardes d’entrée', () => {
  it('B01 · refuse l’absence de session avant d’interroger Odoo', async () => {
    vi.mocked(readOpsSession).mockResolvedValue(null);
    const reponse = await appel();
    expect(reponse.status).toBe(401);
    expect(vi.mocked(fetchLegacyIntake)).not.toHaveBeenCalled();
  });

  it('B02 · rend la fiche, jamais mise en cache', async () => {
    const reponse = await appel();
    expect(reponse.status).toBe(200);
    expect(reponse.headers.get('Cache-Control')).toBe('private, no-store, max-age=0');
    expect((await reponse.json()).data.reference).toBe(REFERENCE);
  });

  it('B05 · refuse tout paramètre de requête', async () => {
    expect((await appel(REFERENCE, '?view=readonly')).status).toBe(400);
    expect(vi.mocked(fetchLegacyIntake)).not.toHaveBeenCalled();
  });
});

describe('R3 · une référence malformée vaut 400, jamais 500 ni 503', () => {
  /**
   * App Router livre le segment **déjà décodé** : ces tests passent donc la
   * valeur telle que Next la remettrait, sans fabriquer un encodage qui
   * n'existe pas en production. Mesuré avant correction — `A%252DB` arrivait
   * en `A%2DB`, la route redécodait, et `A-B` atteignait Odoo.
   */
  const MALFORMEES = [
    ['vide', ''],
    ['espaces seuls', '   '],
    ['trop longue', 'A'.repeat(121)],
    ['caractère interdit', 'A B'],
    ['séquence % invalide', 'A%ZZ'],
    ['pourcent résiduel', 'A%2DB'],
    ['barre oblique', 'A/B'],
    ['remontée de chemin', '../autre'],
    ['requête greffée', 'A001?x=1'],
  ] as const;

  for (const [nom, mauvaise] of MALFORMEES) {
    it(`refuse en 400 : ${nom}`, async () => {
      const reponse = await routeModule.GET(
        new Request('https://ops.test/api/intakes/x/legacy-detail'),
        { params: Promise.resolve({ reference: mauvaise }) },
      ) as unknown as Response;
      expect(reponse.status, nom).toBe(400);
      expect((await reponse.json()).error).toBe('Référence de dossier invalide.');
      // Le refus ne coûte pas un aller-retour à Odoo.
      expect(vi.mocked(fetchLegacyIntake), nom).not.toHaveBeenCalled();
    });
  }

  it('ne redécode pas ce que Next a déjà décodé', () => {
    const SOURCE = readFileSync(fileURLToPath(new URL(
      '../../../app/api/intakes/[reference]/legacy-detail/route.ts',
      import.meta.url)), 'utf8');
    const code = SOURCE.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(code).not.toContain('decodeURIComponent');
    expect(code).toContain('normaliserReference');
  });

  it('laisse passer les formes réelles, souligné compris', async () => {
    for (const bonne of ['AIR-DSS-CDG-2026-002-A015', 'SN-DK_FR-PA_004',
                         'LEGACY-E2E-001']) {
      vi.mocked(fetchLegacyIntake).mockClear();
      const reponse = await routeModule.GET(
        new Request('https://ops.test/api/intakes/x/legacy-detail'),
        { params: Promise.resolve({ reference: bonne }) },
      ) as unknown as Response;
      expect(reponse.status, bonne).toBe(200);
      expect(vi.mocked(fetchLegacyIntake).mock.calls[0]?.[0], bonne).toBe(bonne);
    }
  });
});

describe('les refus d’Odoo sont traduits', () => {
  it('B03/B04 · un dossier inconnu et un dossier natif répondent pareil', async () => {
    // Le service legacy refuse un dossier natif avec le même code : distinguer
    // les deux renseignerait sur l'existence d'un dossier qu'on n'ouvre pas ici.
    vi.mocked(fetchLegacyIntake).mockRejectedValue(
      new OpsGatewayError('not_found'));
    const reponse = await appel();
    expect(reponse.status).toBe(404);
    expect((await reponse.json()).error).toBe('Dossier introuvable.');
  });

  it('B06 · une panne ne laisse fuir aucun détail', async () => {
    vi.mocked(fetchLegacyIntake).mockRejectedValue(new Error('psycopg2 timeout'));
    const reponse = await appel();
    expect(reponse.status).toBe(503);
    const corps = await reponse.text();
    expect(corps).not.toContain('psycopg2');
    expect(corps).toContain('Service momentanément indisponible.');
  });
});

describe('le débit propre à la consultation', () => {
  it('B09 · refuse au-delà du budget de session', async () => {
    for (let i = 0; i < OPS_LEGACY_DETAIL_SESSION.limite; i += 1) {
      expect((await appel()).status, `consultation ${i + 1}`).toBe(200);
    }
    const refuse = await appel();
    expect(refuse.status).toBe(429);
    expect(Number(refuse.headers.get('Retry-After'))).toBeGreaterThan(0);
  });

  it('B10 · ne partage pas son compteur avec la recherche', async () => {
    const avantRecherche = peekRateLimit(cleRechercheSession('session'), 60).remaining;
    await appel();
    expect(peekRateLimit(cleRechercheSession('session'), 60).remaining)
      .toBe(avantRecherche);
    expect(peekRateLimit(cleLegacyDetailSession('session'),
                         OPS_LEGACY_DETAIL_SESSION.limite).remaining)
      .toBe(OPS_LEGACY_DETAIL_SESSION.limite - 1);
  });

  it('B11 · la clé ne porte ni la session en clair ni la référence', () => {
    const cle = cleLegacyDetailSession('session-en-clair');
    expect(cle).not.toContain('session-en-clair');
    expect(cle).not.toContain(REFERENCE);
    expect(cle.startsWith('ops:legacy-detail:session:')).toBe(true);
  });
});

describe('ce que cette route n’est pas', () => {
  const SOURCE = readFileSync(fileURLToPath(new URL(
    '../../../app/api/intakes/[reference]/legacy-detail/route.ts',
    import.meta.url)), 'utf8');

  it('B13 · n’exporte aucun verbe d’écriture', () => {
    expect(routeModule).not.toHaveProperty('POST');
    expect(routeModule).not.toHaveProperty('PUT');
    expect(routeModule).not.toHaveProperty('PATCH');
    expect(routeModule).not.toHaveProperty('DELETE');
    expect(Object.keys(routeModule).filter((cle) => cle === 'GET')).toEqual(['GET']);
  });

  it('B12 · ne journalise ni référence, ni identité, ni contenu', () => {
    // Seuls les arguments passés au journal sont examinés : chercher un mot
    // dans tout le fichier attraperait un argument de fonction, et le test
    // tomberait pour une raison qui n'est pas celle qu'il défend.
    const appels = [...SOURCE.matchAll(/logger\.\w+\(([\s\S]*?)\);/g)]
      .map((trouve) => trouve[1] ?? '');
    expect(appels.length).toBeGreaterThan(0);
    for (const appel of appels) {
      for (const interdit of ['reference', 'customer', 'phone', 'name',
                              'data', 'session']) {
        expect(appel, interdit).not.toContain(interdit);
      }
      expect(appel).toContain('correlationId');
      expect(appel).toContain('durationMs');
    }
  });
});
