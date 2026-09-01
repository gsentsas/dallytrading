import { beforeEach, describe, expect, it, vi } from 'vitest';

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/**
 * Lire une preuve, et la retirer.
 *
 * Deux verbes sur la même adresse, deux exigences différentes : la lecture ne
 * doit rien tenir en mémoire et ne rien relayer d'inutile ; le retrait est une
 * mutation JSON ordinaire, et emprunte donc le squelette commun plutôt que de
 * réécrire ses cinq contrôles.
 */

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/http/origine', () => ({ origineAcceptable: vi.fn(() => true) }));
vi.mock('@/lib/ops/photos', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/ops/photos')>();
  return { ...original, readPhotoBinary: vi.fn(), deletePhoto: vi.fn() };
});

const { readOpsSession } = await import('@/lib/auth/auth');
const { readPhotoBinary, deletePhoto } = await import('@/lib/ops/photos');
const { OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const { resetRateLimits } = await import('@/lib/rate-limit');
const { GET, DELETE } = await import(
  '@/app/api/intakes/[reference]/photos/[photoUuid]/route');

const SOURCE = readFileSync(fileURLToPath(new URL(
  './[reference]/photos/[photoUuid]/route.ts', import.meta.url)), 'utf8');

const REFERENCE = 'AIR-DSS-CDG-2026-902-A001';
const PHOTO = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const UUID = '11111111-1111-4111-8111-111111111111';
const OCTETS = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]);

const CLICHE = {
  photo_uuid: PHOTO, kind: 'reception' as const, mime_type: 'image/jpeg',
  created_at: '2026-08-31T09:00:00Z', created_by: 'Gilles', can_delete: true,
};

function fluxDe(morceaux: Uint8Array[]) {
  const mesure = { annule: false };
  const flux = new ReadableStream<Uint8Array>({
    start(sortie) {
      for (const morceau of morceaux) sortie.enqueue(morceau);
      sortie.close();
    },
    cancel() { mesure.annule = true; },
  });
  return { flux, mesure };
}

function contexte() {
  return { params: Promise.resolve({ reference: REFERENCE, photoUuid: PHOTO }) };
}

function requeteRetrait(corps: unknown): Request {
  return new Request(
    `https://ops.test/api/intakes/${REFERENCE}/photos/${PHOTO}`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corps),
    });
}

beforeEach(() => {
  resetRateLimits();
  vi.mocked(readOpsSession).mockReset();
  vi.mocked(readPhotoBinary).mockReset();
  vi.mocked(deletePhoto).mockReset();
  vi.mocked(readOpsSession).mockResolvedValue({ odooSessionId: 'session', issuedAt: 1 });
  vi.mocked(deletePhoto).mockResolvedValue({ status: 'deleted', photo: CLICHE });
});

describe('F17–F20 · GET des octets', () => {
  it('F17 · relaie l’image sans publier le moindre identifiant technique',
    async () => {
      const { flux } = fluxDe([OCTETS]);
      vi.mocked(readPhotoBinary).mockResolvedValue({ corps: flux, type: 'image/jpeg' });
      const reponse = await GET(new Request('https://ops.test/x'), contexte());
      expect(reponse.status).toBe(200);
      expect(reponse.headers.get('content-type')).toBe('image/jpeg');
      expect(await reponse.arrayBuffer()).toEqual(OCTETS.buffer.slice(0));
      expect(vi.mocked(readPhotoBinary)).toHaveBeenCalledWith(
        REFERENCE, PHOTO, 'session', expect.any(String));
      // Rien d'Odoo n'est relayé : ni cookie, ni empreinte, ni signature.
      for (const interdit of ['set-cookie', 'etag', 'server', 'x-powered-by',
                              'content-location']) {
        expect(reponse.headers.get(interdit), interdit).toBeNull();
      }
    });

  it('F18/F19 · repose les en-têtes d’affichage sûrs', async () => {
    const { flux } = fluxDe([OCTETS]);
    vi.mocked(readPhotoBinary).mockResolvedValue({ corps: flux, type: 'image/png' });
    const reponse = await GET(new Request('https://ops.test/x'), contexte());
    expect(reponse.headers.get('cache-control')).toBe('private, no-store');
    expect(reponse.headers.get('x-content-type-options')).toBe('nosniff');
    expect(reponse.headers.get('content-disposition')).toBe('inline');
    expect(reponse.headers.get('content-security-policy')).toContain("default-src 'none'");
    expect(reponse.headers.get('content-security-policy')).toContain('sandbox');
  });

  it('F20 · la route ne bufferise jamais l’image', () => {
    // Une seule de ces lignes ramènerait dix mébioctets en mémoire par
    // lecteur simultané. La preuve est dans le source, faute de pouvoir
    // mesurer une absence d'allocation.
    for (const interdit of ['arrayBuffer(', '.blob(', 'Buffer.from', 'text()']) {
      expect(SOURCE, interdit).not.toContain(interdit);
    }
    expect(SOURCE).toContain('new Response(image.corps');
  });

  it('l’aval qui abandonne annule bien la source', async () => {
    const { flux, mesure } = fluxDe([OCTETS]);
    vi.mocked(readPhotoBinary).mockResolvedValue({ corps: flux, type: 'image/jpeg' });
    const reponse = await GET(new Request('https://ops.test/x'), contexte());
    await reponse.body?.cancel('écran fermé');
    expect(mesure.annule).toBe(true);
  });

  it('refuse sans session, et traduit une photo introuvable', async () => {
    vi.mocked(readOpsSession).mockResolvedValue(null);
    expect((await GET(new Request('https://ops.test/x'), contexte())).status).toBe(401);

    vi.mocked(readOpsSession).mockResolvedValue({
      odooSessionId: 'session', issuedAt: 1 });
    vi.mocked(readPhotoBinary).mockRejectedValue(
      new OpsGatewayError('not_found', 'introuvable', 'photo_not_found'));
    const introuvable = await GET(new Request('https://ops.test/x'), contexte());
    expect(introuvable.status).toBe(404);
    expect(introuvable.headers.get('cache-control')).toContain('no-store');
  });

  it('ne laisse fuir aucun détail de panne', async () => {
    vi.mocked(readPhotoBinary).mockRejectedValue(
      new Error('ECONNREFUSED 127.0.0.1:18169 store_fname=ab/cd'));
    const reponse = await GET(new Request('https://ops.test/x'), contexte());
    expect(reponse.status).toBe(503);
    const corps = JSON.stringify(await reponse.json());
    for (const interdit of ['ECONNREFUSED', '18169', 'store_fname']) {
      expect(corps).not.toContain(interdit);
    }
  });
});

describe('F21 · DELETE', () => {
  it('exige un identifiant de geste et le transmet tel quel', async () => {
    const reponse = await DELETE(requeteRetrait({ request_uuid: UUID }), contexte());
    expect(reponse.status).toBe(200);
    expect(vi.mocked(deletePhoto)).toHaveBeenCalledWith(
      REFERENCE, PHOTO, UUID, 'session', expect.any(String));
    expect(reponse.headers.get('cache-control')).toContain('no-store');
  });

  it('refuse un corps sans identifiant, mal formé, ou enrichi', async () => {
    for (const corps of [{}, { request_uuid: 'pas-un-uuid' },
                         { request_uuid: UUID, force: true }]) {
      const reponse = await DELETE(requeteRetrait(corps), contexte());
      expect(reponse.status, JSON.stringify(corps)).toBe(400);
    }
    expect(deletePhoto).not.toHaveBeenCalled();
  });

  it('traduit les deux refus métier du retrait', async () => {
    for (const [refus, extrait] of [
      ['photo_already_deleted', 'déjà été retirée'],
      ['photo_delete_not_allowed', 'responsable'],
    ] as const) {
      vi.mocked(deletePhoto).mockRejectedValueOnce(
        new OpsGatewayError('conflict', 'conflit', refus));
      const reponse = await DELETE(requeteRetrait({ request_uuid: UUID }), contexte());
      expect(reponse.status).toBe(409);
      const corps = await reponse.json();
      expect(corps.code).toBe(refus);
      expect(corps.error).toContain(extrait);
    }
  });

  it('emprunte le squelette commun plutôt que de réécrire ses contrôles', () => {
    expect(SOURCE).toContain('reponseMutation');
    // Aucune seconde implémentation d'origine, de session ou de débit.
    expect(SOURCE).not.toContain('peekRateLimit');
    expect(SOURCE).not.toContain('checkRateLimit');
  });
});
