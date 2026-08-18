/**
 * L'ordre des photos d'un produit, et la navigation entre elles.
 *
 * Logique pure, séparée du composant. Deux raisons, et la seconde est la vraie :
 *
 * * les tests de ce dépôt tournent en environnement Node avec
 *   `renderToStaticMarkup` — pas de navigateur, donc pas de clic. Une logique
 *   enfermée dans un composant client ne serait vérifiable qu'en Playwright,
 *   c'est-à-dire tard et lentement ;
 * * l'ordre des photos est une **décision produit** — la principale d'abord —
 *   et non un détail de rendu. Écrite ici, elle a un nom, un test et une seule
 *   implémentation ; répartie dans le JSX, elle se serait dupliquée entre la
 *   grande image, les vignettes et les indicateurs.
 */

import {
  shopGalleryImageUrl,
  shopImageUrl,
  type ShopImageSize,
} from '@/lib/shop/image';
import type { ShopProductDetail } from '@/lib/shop/dto';

/** Une photo prête à afficher : deux tailles, et une clé stable. */
export interface PhotoProduit {
  /** Le jeton de contenu. Stable tant que la photo ne change pas. */
  readonly token: string;
  /** `true` pour `image_1920` du produit, `false` pour une photo de galerie. */
  readonly principale: boolean;
  readonly detail: string;
  readonly card: string;
}

function url(
  reference: string,
  photo: { token: string; principale: boolean },
  size: ShopImageSize,
): string | null {
  return photo.principale
    ? shopImageUrl(reference, photo.token, size)
    : shopGalleryImageUrl(reference, photo.token, size);
}

/**
 * Les photos du produit, dans l'ordre d'affichage.
 *
 * La photo principale vient toujours en premier, quelle que soit la `sequence`
 * des photos de galerie : c'est celle que le vendeur a choisie comme visage du
 * produit, et la laisser dépendre d'un numéro d'ordre saisi ailleurs ferait
 * changer la vitrine sans qu'on ait touché à la vitrine.
 *
 * Les suivantes sont triées par `sequence`, `reference` départageant les
 * ex æquo pour que deux affichages successifs donnent le même ordre — Odoo trie
 * déjà ainsi, et un tri instable ici le contredirait à chaque rendu.
 *
 * Un produit sans aucune photo rend un tableau vide : c'est le signal du
 * substitut, et il ne coûte aucune requête.
 */
export function photosDuProduit(
  produit: Pick<ShopProductDetail, 'reference' | 'imageVersion' | 'gallery'>,
): PhotoProduit[] {
  const brut: Array<{ token: string; principale: boolean }> = [];

  if (produit.imageVersion) {
    brut.push({ token: produit.imageVersion, principale: true });
  }

  const galerie = [...(produit.gallery ?? [])].sort(
    (a, b) => a.sequence - b.sequence || a.reference.localeCompare(b.reference),
  );
  for (const photo of galerie) {
    brut.push({ token: photo.reference, principale: false });
  }

  const photos: PhotoProduit[] = [];
  for (const photo of brut) {
    const detail = url(produit.reference, photo, 'detail');
    const card = url(produit.reference, photo, 'card');
    // `null` signifie qu'on ne sait pas construire l'adresse — jeton vide,
    // référence vide. Une photo sans adresse est une vignette morte : elle est
    // écartée plutôt qu'affichée cassée.
    if (detail && card) {
      photos.push({ ...photo, detail, card });
    }
  }
  return photos;
}

/**
 * L'index suivant, en boucle.
 *
 * La boucle est délibérée : sur une galerie de quatre photos, buter sur la
 * dernière oblige à revenir en arrière quatre fois pour revoir la première.
 * `total` nul rend 0 plutôt que `NaN` — le composant appelle ces fonctions
 * avant de savoir s'il a des photos.
 */
export function photoSuivante(index: number, total: number): number {
  if (total <= 0) return 0;
  return (index + 1) % total;
}

export function photoPrecedente(index: number, total: number): number {
  if (total <= 0) return 0;
  return (index - 1 + total) % total;
}

/** Borne un index reçu de l'extérieur dans l'intervalle utilisable. */
export function indexValide(index: number, total: number): number {
  if (total <= 0 || !Number.isInteger(index)) return 0;
  return Math.min(Math.max(index, 0), total - 1);
}
