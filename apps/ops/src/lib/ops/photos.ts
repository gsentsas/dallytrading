/**
 * Le contrat des preuves photographiques d'un dossier.
 *
 * ## Ce que le navigateur ne reçoit jamais
 *
 * Ni identifiant de pièce jointe, ni `res_model`, ni chemin de stockage, ni
 * URL `/web/content`. Une photo se désigne par une clé opaque tirée par le
 * serveur, et se lit par une route qui refait tous les contrôles. `.strict()`
 * n'est pas une précaution de style : c'est ce qui fait tomber la lecture le
 * jour où un champ technique descendrait par inadvertance.
 *
 * ## Ce que le serveur décide seul
 *
 * `can_add`, `can_delete` et les limites. Les recalculer ici produirait une
 * seconde règle, et l'écran finirait par proposer une action que le serveur
 * refuse — ou par cacher une action qu'il autorise.
 */

import { z } from 'zod';

import { opsDelete, opsGet, opsGetBinaire, opsPostFichier } from '@/lib/auth/odoo-ops';

/** Les cinq natures. Fermé côté serveur, fermé ici. */
export const natureCliche = z.enum([
  'reception', 'package', 'damage', 'preparation', 'other',
]);

export type NatureCliche = z.infer<typeof natureCliche>;

/** Ce que l'opérateur lit à la place du code. */
export const LIBELLES_NATURE: Readonly<Record<NatureCliche, string>> = {
  reception: 'État à la réception',
  package: 'Emballage',
  damage: 'Dommage ou anomalie',
  preparation: 'Préparation avant expédition',
  other: 'Autre',
};

/**
 * La nature proposée par défaut selon l'état du dossier.
 *
 * Une proposition, jamais une contrainte : c'est le geste le plus probable à
 * ce moment-là, et l'opérateur reste libre d'en choisir un autre. Le serveur,
 * lui, valide la nature reçue quelle qu'elle soit.
 */
export function naturePardefaut(etat: string): NatureCliche {
  if (etat === 'goods_received') return 'reception';
  if (etat === 'preparing' || etat === 'ready') return 'preparation';
  return 'other';
}

export const cliche = z.object({
  photo_uuid: z.string().min(1).max(64),
  kind: natureCliche,
  mime_type: z.string().min(1).max(64),
  created_at: z.string().min(1).max(40),
  created_by: z.string().max(120),
  can_delete: z.boolean(),
}).strict();

export const clichesDossier = z.object({
  photos: z.array(cliche).max(64),
  can_add: z.boolean(),
  limits: z.object({
    max_file_bytes: z.number().int().positive(),
    max_active_photos: z.number().int().positive(),
  }).strict(),
}).strict();

export type Cliche = z.infer<typeof cliche>;
export type ClichesDossier = z.infer<typeof clichesDossier>;

const envoiAccepte = z.object({
  status: z.enum(['added', 'replayed']),
  photo: cliche,
}).strict();

const retraitAccepte = z.object({
  status: z.enum(['deleted', 'replayed']),
  photo: cliche,
}).strict();

/** Dix mébioctets, décidés par le serveur et redits ici pour refuser tôt. */
export const TAILLE_MAXIMALE_PHOTO = 10 * 1024 * 1024;

/** Ce qu'un appareil photo de téléphone produit. */
export const TYPES_PHOTO = [
  'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif',
] as const;

/** Ce que la route de lecture accepte de relayer. */
export const TYPES_RELAYABLES = [
  'image/jpeg', 'image/png', 'image/webp', 'image/heic',
] as const;

function ressource(reference: string, suffixe = ''): string {
  if (!/^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$/.test(reference)) {
    throw new Error('Référence de dossier invalide.');
  }
  return `intakes/${reference}/photos${suffixe}`;
}

function cle(photoUuid: string): string {
  if (!/^[0-9a-fA-F-]{8,64}$/.test(photoUuid)) {
    throw new Error('Référence de photo invalide.');
  }
  return photoUuid;
}

export async function fetchPhotos(
  reference: string, sessionId: string, correlationId: string,
): Promise<ClichesDossier> {
  return clichesDossier.parse(
    await opsGet(ressource(reference), sessionId, correlationId));
}

export async function addPhoto(
  reference: string,
  requestUuid: string,
  kind: NatureCliche,
  fichier: { readonly nom: string; readonly type: string; readonly contenu: Blob },
  sessionId: string,
  correlationId: string,
): Promise<z.infer<typeof envoiAccepte>> {
  return envoiAccepte.parse(await opsPostFichier(
    ressource(reference),
    fichier,
    { request_uuid: requestUuid, kind },
    sessionId,
    correlationId,
    'photo',
  ));
}

export async function deletePhoto(
  reference: string,
  photoUuid: string,
  requestUuid: string,
  sessionId: string,
  correlationId: string,
): Promise<z.infer<typeof retraitAccepte>> {
  return retraitAccepte.parse(await opsDelete(
    ressource(reference, `/${cle(photoUuid)}`),
    { request_uuid: requestUuid },
    sessionId,
    correlationId,
  ));
}

/**
 * Les octets d'une photo, en flux.
 *
 * Rien n'est tenu en mémoire : le corps traverse le BFF chunk par chunk. Une
 * image de dix mébioctets ne coûte donc pas dix mébioctets de mémoire par
 * lecteur simultané.
 */
export function readPhotoBinary(
  reference: string, photoUuid: string, sessionId: string, correlationId: string,
): Promise<{ readonly corps: ReadableStream<Uint8Array>; readonly type: string }> {
  return opsGetBinaire(
    ressource(reference, `/${cle(photoUuid)}`),
    sessionId,
    correlationId,
    TYPES_RELAYABLES,
  );
}
