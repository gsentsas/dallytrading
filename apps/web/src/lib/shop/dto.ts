/**
 * Le contrat de la boutique. Ce qui n'y figure pas ne franchit pas la frontière.
 *
 * ## `.strict()` partout, et ce que cela a déjà attrapé
 *
 * Un schéma permissif accepterait un champ que le BFF n'attend pas, et ce champ
 * se retrouverait dans la charge RSC envoyée au navigateur — donc lisible, même
 * si aucun composant ne l'affiche. Avec `.strict()`, une clé de trop est une
 * erreur bruyante au lieu d'une fuite discrète.
 *
 * Le prix de cette rigueur est connu et assumé : lors du cycle véhicule, ajouter
 * une clé côté Odoo avant de déployer le frontend a produit un rejet en
 * production. C'est le comportement voulu — un contrat qui plie n'est pas un
 * contrat — et il impose l'ordre de déploiement : frontend d'abord.
 *
 * ## Ce que le contrat n'a pas
 *
 * Aucun identifiant de base. Aucun coût, aucune marge, aucun fournisseur, aucune
 * note interne, aucune quantité en stock. Ces champs ne sont pas « filtrés » :
 * ils n'ont pas de place où atterrir.
 */

import { z } from 'zod';

/**
 * La politique de stock, telle qu'Odoo la décide.
 *
 * Une énumération fermée et non une chaîne libre : le libellé affiché en dépend,
 * et une valeur inconnue doit faire échouer le contrat plutôt que produire une
 * étiquette vide sur la fiche produit.
 */
export const shopStockPolicySchema = z.enum(['on_order', 'managed']);
export type ShopStockPolicy = z.infer<typeof shopStockPolicySchema>;

/**
 * La disponibilité — qualitative, jamais un nombre.
 *
 * `on_order` n'est pas un doublon de la politique : la politique dit comment le
 * produit est approvisionné, la disponibilité ce que le client lit maintenant. Un
 * produit à stock suivi passe de `in_stock` à `out_of_stock` sans que sa
 * politique change.
 */
export const shopAvailabilitySchema = z.enum([
  'on_order',
  'in_stock',
  'out_of_stock',
]);
export type ShopAvailability = z.infer<typeof shopAvailabilitySchema>;

/**
 * Une catégorie, réduite à ce qui s'affiche.
 *
 * `nullable` sur le produit : une catégorie non publiée est absente de la
 * projection, parce que le nom d'une gamme en préparation est une information
 * commerciale.
 */
export const shopCategoryRefSchema = z
  .object({
    reference: z.string().min(1),
    name: z.string().min(1),
  })
  .strict();

export const shopCategorySchema = z
  .object({
    reference: z.string().min(1),
    name: z.string().min(1),
    productCount: z.number().int().nonnegative(),
  })
  .strict();

/** Un produit de la vitrine. Le prix vient d'Odoo, jamais du navigateur. */
export const shopProductSchema = z
  .object({
    reference: z.string().min(1),
    name: z.string().min(1),
    summary: z.string().nullable(),
    price: z.number().nonnegative(),
    currency: z.string().min(1),
    stockPolicy: shopStockPolicySchema,
    stockPolicyLabel: z.string(),
    availability: shopAvailabilitySchema,
    /**
     * L'empreinte de l'image du produit, ou `null` s'il n'en a pas.
     *
     * Jamais les octets : une image en base64 dans ce contrat ferait plusieurs
     * mégaoctets de charge RSC par affichage de catalogue, retransmis à chaque
     * navigation et jamais mis en cache par le navigateur. Ce jeton sert à
     * construire une URL, et c'est cette URL que le navigateur met en cache.
     *
     * `.default(null)` et non un champ requis : la valeur est *ajoutée* par une
     * version d'Odoo plus récente que ce frontend. Un champ requis imposerait de
     * déployer Odoo en premier, et la boutique tomberait pendant la fenêtre
     * inverse — c'est précisément l'incident décrit en tête de ce fichier, dans
     * l'autre sens. Avec un défaut, ce frontend fonctionne avant comme après la
     * montée de version d'Odoo, et l'ordre de déploiement reste libre.
     */
    imageVersion: z.string().min(1).nullable().default(null),
    category: shopCategoryRefSchema.nullable(),
  })
  .strict();
export type ShopProduct = z.infer<typeof shopProductSchema>;

/**
 * La fiche produit : deux clés de plus, déclarées explicitement.
 *
 * `extend` et non un schéma séparé : les onze champs communs n'ont ainsi qu'une
 * seule définition, et une divergence entre liste et fiche est impossible.
 */
/**
 * Une photo de galerie : un jeton et un rang, rien d'autre.
 *
 * `reference` est l'empreinte du contenu de la photo, la même nature de valeur
 * qu'`imageVersion`. Ce n'est pas un identifiant de base : le serveur ne s'en
 * sert pas comme clé de recherche, il le compare aux empreintes qu'il calcule
 * pour le produit déjà autorisé. Un jeton valable pour un autre produit ne
 * désigne donc rien.
 */
export const shopGalleryImageSchema = z
  .object({
    reference: z.string().min(1),
    sequence: z.number().int(),
  })
  .strict();
export type ShopGalleryImage = z.infer<typeof shopGalleryImageSchema>;

export const shopProductDetailSchema = shopProductSchema
  .extend({
    description: z.string().nullable(),
    unit: z.string().min(1),
    /**
     * La galerie n'existe que sur la fiche.
     *
     * Elle est absente de `shopProductSchema`, donc des tuiles du catalogue et
     * des lignes de panier — non par discipline, mais par structure : trente
     * jetons de galerie voyageraient dans la charge d'une page qui n'affiche
     * qu'une image par produit, et `.strict()` refuserait le champ s'il
     * arrivait quand même.
     *
     * `.default([])` pour la même raison qu'`imageVersion` : ce frontend doit
     * fonctionner avant comme après la montée de version d'Odoo, sans imposer
     * d'ordre de déploiement.
     */
    gallery: z.array(shopGalleryImageSchema).default([]),
  })
  .strict();
export type ShopProductDetail = z.infer<typeof shopProductDetailSchema>;

export const shopCatalogueSchema = z
  .object({
    products: z.array(shopProductSchema),
    categories: z.array(shopCategorySchema),
  })
  .strict();
export type ShopCatalogue = z.infer<typeof shopCatalogueSchema>;

/** Une ligne de panier résolue : le produit, la quantité, le sous-total. */
export const resolvedCartLineSchema = shopProductSchema
  .extend({
    quantity: z.number().int().positive(),
    subtotal: z.number().nonnegative(),
  })
  .strict();
export type ResolvedCartLine = z.infer<typeof resolvedCartLineSchema>;

/**
 * Le panier résolu.
 *
 * `removed` porte les références qui ont disparu du catalogue depuis la mise au
 * panier. Le champ existe pour que la page puisse le dire au client : sans lui,
 * une ligne s'évaporerait sans explication, et le total ne correspondrait plus à
 * ce que le client se rappelle avoir choisi.
 *
 * `total` est égal à `subtotal` dans ce cycle, et c'est délibéré : ni livraison
 * ni taxes ne sont décidées, et un montant inventé serait pire qu'un montant
 * absent. Les deux clés existent parce que la page affiche un total, et qu'il
 * vaut mieux qu'elle lise un champ dont le sens ne changera pas quand la
 * livraison arrivera.
 */
export const resolvedCartSchema = z
  .object({
    lines: z.array(resolvedCartLineSchema),
    removed: z.array(z.string()),
    itemCount: z.number().int().nonnegative(),
    subtotal: z.number().nonnegative(),
    currency: z.string().min(1),
    total: z.number().nonnegative(),
  })
  .strict();
export type ResolvedCart = z.infer<typeof resolvedCartSchema>;

/**
 * Le panier tel que le navigateur le reçoit.
 *
 * `cartId` n'y est pas. Il sert de clé d'idempotence à la commande, il vit dans
 * le cookie scellé, et le navigateur n'a rien à en faire : l'exposer inviterait
 * à le renvoyer, donc à le choisir.
 */
export const cartViewSchema = resolvedCartSchema
  .extend({
    lineCount: z.number().int().nonnegative(),
    maxLines: z.number().int().positive(),
  })
  .strict();
export type CartView = z.infer<typeof cartViewSchema>;
