import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Le contrat des photos, dans les deux sens.
 *
 * À l'aller : ce que le navigateur a le droit d'envoyer. Au retour : ce qu'il
 * a le droit de recevoir. `.strict()` fait tomber la lecture le jour où un
 * champ technique descendrait — c'est la seule garde qui n'attend pas qu'on
 * pense à la vérifier.
 */

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return {
    ...original,
    opsGet: vi.fn(), opsDelete: vi.fn(),
    opsPostFichier: vi.fn(), opsGetBinaire: vi.fn(),
  };
});

const { opsGet, opsDelete, opsPostFichier, opsGetBinaire } = await import(
  '@/lib/auth/odoo-ops');
const {
  addPhoto, deletePhoto, fetchPhotos, readPhotoBinary,
  LIBELLES_NATURE, naturePardefaut, TYPES_RELAYABLES,
} = await import('@/lib/ops/photos');

const REFERENCE = 'AIR-DSS-CDG-2026-902-A001';
const PHOTO = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const UUID = '11111111-1111-4111-8111-111111111111';

const CLICHE = {
  photo_uuid: PHOTO, kind: 'reception', mime_type: 'image/jpeg',
  created_at: '2026-08-31T09:00:00Z', created_by: 'Gilles', can_delete: true,
};

const LISTE = {
  photos: [CLICHE],
  can_add: true,
  limits: { max_file_bytes: 10485760, max_active_photos: 20 },
};

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsDelete).mockReset();
  vi.mocked(opsPostFichier).mockReset();
  vi.mocked(opsGetBinaire).mockReset();
});

describe('F14–F15 · le contrat de retour refuse tout identifiant technique', () => {
  it('accepte exactement les six champs prévus', async () => {
    vi.mocked(opsGet).mockResolvedValue(LISTE);
    const lu = await fetchPhotos(REFERENCE, 'sX', 'corr');
    expect(lu.photos[0]).toEqual(CLICHE);
  });

  it.each([
    ['attachment_id', { ...CLICHE, attachment_id: 91 }],
    ['res_id', { ...CLICHE, res_id: 91 }],
    ['res_model', { ...CLICHE, res_model: 'dally.ops.photo' }],
    ['user_id', { ...CLICHE, user_id: 7 }],
    ['company_id', { ...CLICHE, company_id: 1 }],
    ['store_fname', { ...CLICHE, store_fname: 'ab/cdef' }],
    ['checksum', { ...CLICHE, checksum: 'deadbeef' }],
    ['datas', { ...CLICHE, datas: 'iVBORw0KGgo=' }],
    ['filename', { ...CLICHE, filename: 'colis.jpg' }],
    ['url', { ...CLICHE, url: '/web/content/9182' }],
  ])('F14/F15 · refuse une réponse enrichie de « %s »', async (_nom, photo) => {
    vi.mocked(opsGet).mockResolvedValue({ ...LISTE, photos: [photo] });
    await expect(fetchPhotos(REFERENCE, 'sX', 'corr')).rejects.toThrow();
  });

  it('refuse une nature inconnue au retour', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      ...LISTE, photos: [{ ...CLICHE, kind: 'selfie' }] });
    await expect(fetchPhotos(REFERENCE, 'sX', 'corr')).rejects.toThrow();
  });

  it('refuse une enveloppe enrichie', async () => {
    vi.mocked(opsGet).mockResolvedValue({ ...LISTE, total: 1 });
    await expect(fetchPhotos(REFERENCE, 'sX', 'corr')).rejects.toThrow();
  });
});

describe('l’aller', () => {
  it('pose le champ multipart « photo » et les deux champs de texte', async () => {
    vi.mocked(opsPostFichier).mockResolvedValue({ status: 'added', photo: CLICHE });
    await addPhoto(
      REFERENCE, UUID, 'damage',
      { nom: 'p.jpg', type: 'image/jpeg', contenu: new Blob(['x']) },
      'sX', 'corr');
    expect(opsPostFichier).toHaveBeenCalledWith(
      `intakes/${REFERENCE}/photos`,
      expect.objectContaining({ nom: 'p.jpg' }),
      { request_uuid: UUID, kind: 'damage' },
      'sX', 'corr', 'photo');
  });

  it('transmet l’identifiant du geste au retrait', async () => {
    vi.mocked(opsDelete).mockResolvedValue({ status: 'deleted', photo: CLICHE });
    await deletePhoto(REFERENCE, PHOTO, UUID, 'sX', 'corr');
    expect(opsDelete).toHaveBeenCalledWith(
      `intakes/${REFERENCE}/photos/${PHOTO}`,
      { request_uuid: UUID }, 'sX', 'corr');
  });

  it('refuse une référence ou une clé qui composeraient un chemin', async () => {
    for (const reference of ['../web', 'A 1', 'A/B', '']) {
      await expect(fetchPhotos(reference, 'sX', 'corr')).rejects.toThrow();
    }
    for (const clef of ['../x', 'a b', '/web/content/9']) {
      await expect(deletePhoto(REFERENCE, clef, UUID, 'sX', 'corr')).rejects.toThrow();
    }
    expect(opsGet).not.toHaveBeenCalled();
    expect(opsDelete).not.toHaveBeenCalled();
  });
});

describe('la lecture binaire', () => {
  it('n’accepte de relayer que des images', async () => {
    vi.mocked(opsGetBinaire).mockResolvedValue({
      corps: new ReadableStream(), type: 'image/jpeg' });
    await readPhotoBinary(REFERENCE, PHOTO, 'sX', 'corr');
    expect(opsGetBinaire).toHaveBeenCalledWith(
      `intakes/${REFERENCE}/photos/${PHOTO}`, 'sX', 'corr', TYPES_RELAYABLES);
    expect([...TYPES_RELAYABLES]).toEqual([
      'image/jpeg', 'image/png', 'image/webp', 'image/heic']);
    // Ni PDF, ni SVG, ni HTML : ce que le serveur stocke est déjà borné, et le
    // relais ne rouvre pas la liste.
    for (const interdit of ['application/pdf', 'image/svg+xml', 'text/html']) {
      expect(TYPES_RELAYABLES as readonly string[]).not.toContain(interdit);
    }
  });
});

describe('le vocabulaire serveur reste aligné sur celui de l’écran', () => {
  it('couvre les cinq natures et présélectionne la bonne', () => {
    expect(Object.keys(LIBELLES_NATURE).sort()).toEqual(
      ['damage', 'other', 'package', 'preparation', 'reception']);
    expect(naturePardefaut('goods_received')).toBe('reception');
    expect(naturePardefaut('ready')).toBe('preparation');
  });
});
