/**
 * L'adresse publique de l'image d'un produit.
 *
 * ## Une seule fonction, donc un seul mécanisme
 *
 * Le catalogue, la fiche et le panier affichent la même image du même produit.
 * S'ils construisaient chacun leur URL, ils divergeraient — une taille ici, un
 * paramètre de cache oublié là — et le navigateur téléchargerait trois fois ce
 * qui est une seule image. Tout passe donc par `shopImageUrl`.
 *
 * ## Ce que l'URL ne contient pas
 *
 * Ni nom de modèle, ni identifiant de base, ni clé d'API. Le slug est la seule
 * clé publique du produit, exactement comme dans `/boutique/<slug>` et dans le
 * panier scellé. `/web/image/product.template/42/image_1920` est l'adresse
 * qu'Odoo propose et que la boutique refuse d'utiliser : elle publie le modèle
 * et l'identifiant, et l'identifiant s'énumère.
 *
 * ## Le jeton de version fait tout le travail de cache
 *
 * Il est l'empreinte du contenu de l'image. Tant que l'image ne change pas,
 * l'URL ne change pas et le navigateur garde la sienne ; dès qu'elle change,
 * l'URL change et la nouvelle est chargée. Personne n'a de cache à vider, et la
 * réponse peut donc être déclarée cachable très longtemps.
 */

/**
 * Les tailles servies, en miroir exact de `TAILLES_IMAGE` côté Odoo.
 *
 * Fermée des deux côtés. Une dimension libre dans l'URL ferait redimensionner à
 * la demande depuis l'extérieur : chaque valeur inédite serait un calcul
 * d'image et une entrée de cache de plus.
 */
export const SHOP_IMAGE_SIZES = ['card', 'detail'] as const;
export type ShopImageSize = (typeof SHOP_IMAGE_SIZES)[number];

export const SHOP_IMAGE_SIZE_DEFAULT: ShopImageSize = 'card';

/** Dimensions d'affichage, pour réserver la place et éviter que la page saute. */
export const SHOP_IMAGE_DIMENSIONS: Record<
  ShopImageSize,
  { readonly width: number; readonly height: number }
> = {
  card: { width: 512, height: 512 },
  detail: { width: 1024, height: 1024 },
};

/**
 * Les types d'image acceptés en réponse, en miroir de `MIMETYPES_IMAGE`.
 *
 * Le BFF ne renvoie au navigateur que ces types-là, quoi qu'Odoo ait annoncé.
 * Sans cette liste, un `Content-Type` inattendu serait relayé tel quel depuis
 * notre origine — et `image/svg+xml`, absent de la liste à dessein, est un
 * document XML capable de porter du script.
 */
export const SHOP_IMAGE_MIME_TYPES = [
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
] as const;

/**
 * Le type normalisé s'il est dans la liste blanche, `null` sinon.
 *
 * Rend le type plutôt qu'un booléen : l'appelant qui accepte l'image doit
 * réémettre un `Content-Type`, et réémettre celui reçu tel quel relaierait
 * `image/png; charset=binary` — ou une casse inattendue — depuis notre origine.
 * La valeur validée et la valeur servie sont ainsi la même, par construction.
 */
export function shopImageMimeType(value: string | null): string | null {
  if (!value) return null;
  // Le type peut arriver suffixé d'un paramètre — `image/png; charset=binary`.
  const type = (value.split(';', 1)[0] ?? '').trim().toLowerCase();
  return (SHOP_IMAGE_MIME_TYPES as readonly string[]).includes(type) ? type : null;
}

export function isShopImageMimeType(value: string | null): boolean {
  return shopImageMimeType(value) !== null;
}

export function isShopImageSize(value: unknown): value is ShopImageSize {
  return (
    typeof value === 'string' &&
    (SHOP_IMAGE_SIZES as readonly string[]).includes(value)
  );
}

/**
 * L'URL de l'image, ou `null` quand le produit n'en a pas.
 *
 * `null` plutôt qu'une URL menant à un 404 : l'appelant affiche alors son
 * substitut sans requête réseau. Demander une image dont on sait déjà qu'elle
 * n'existe pas coûterait un aller-retour par tuile, et remplirait les journaux
 * de 404 qui ne signalent rien.
 */
export function shopImageUrl(
  reference: string,
  imageVersion: string | null,
  size: ShopImageSize = SHOP_IMAGE_SIZE_DEFAULT,
): string | null {
  if (!reference || !imageVersion) return null;
  const params = new URLSearchParams({ v: imageVersion, size });
  return `/api/shop/products/${encodeURIComponent(reference)}/image?${params.toString()}`;
}
