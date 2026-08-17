/**
 * Le contrat des commandes boutique dans l'espace client.
 *
 * ## Séparé de `checkout-schema.ts`, et pas par goût du rangement
 *
 * La commande rendue juste après un paiement de panier et la commande relue des
 * mois plus tard dans l'espace client ne portent pas la même chose. La première a
 * besoin de `replayed`, qui n'a de sens que dans la seconde qui suit l'envoi ; la
 * seconde a besoin d'une date et d'une adresse, qui n'ont rien à faire dans une
 * confirmation.
 *
 * Fusionner les deux imposerait des champs optionnels partout, et un champ
 * optionnel est un champ dont personne ne sait s'il doit être là.
 *
 * ## `.strict()` sans exception
 *
 * Une commande Odoo porte la marge, le vendeur, les conditions de paiement, la
 * position fiscale et l'historique de messagerie. Un schéma permissif laisserait
 * l'un d'eux atteindre la charge RSC envoyée au navigateur — donc lisible, même si
 * aucun composant ne l'affiche.
 */

import { z } from 'zod';

import { deliveryModeSchema } from './checkout-schema';

/**
 * Une ligne de commande, vue du client.
 *
 * `quantity` est un flottant : Odoo stocke `product_uom_qty` en `Float`, et la
 * mesure sur l'instance rend bien `2.0`. Le déclarer entier ferait échouer le
 * contrat sur une donnée parfaitement normale.
 */
export const shopOrderLineSchema = z
  .object({
    productName: z.string().min(1),
    quantity: z.number().positive(),
    unitPrice: z.number().nonnegative(),
    subtotal: z.number().nonnegative(),
  })
  .strict();
export type ShopOrderLine = z.infer<typeof shopOrderLineSchema>;

/**
 * Une commande dans la liste.
 *
 * `stateLabel` vient d'Odoo et n'est pas recalculé ici. Ce n'est pas de la
 * paresse : le libellé affirme quelque chose au client — « en attente de
 * validation » — et cette affirmation doit avoir une seule source. Deux tables de
 * correspondance finiraient par diverger, et la version qui mentirait serait
 * celle que le client lit.
 *
 * `state` brut n'y figure pas : la liste n'en a pas besoin, et l'exposer
 * inviterait un composant à s'en servir pour reconstruire un libellé.
 */
export const shopOrderListItemSchema = z
  .object({
    reference: z.string().min(1),
    date: z.string().nullable(),
    stateLabel: z.string().min(1),
    currency: z.string().min(1),
    amountUntaxed: z.number().nonnegative(),
    amountTax: z.number().nonnegative(),
    amountTotal: z.number().nonnegative(),
    deliveryMode: deliveryModeSchema.nullable(),
    deliveryModeLabel: z.string(),
    itemCount: z.number().int().nonnegative(),
  })
  .strict();
export type ShopOrderListItem = z.infer<typeof shopOrderListItemSchema>;

export const shopOrderListSchema = z
  .object({ orders: z.array(shopOrderListItemSchema) })
  .strict();
export type ShopOrderList = z.infer<typeof shopOrderListSchema>;

/**
 * L'adresse rappelée sur le détail.
 *
 * Uniquement ce que le client a lui-même fourni, pour qu'il vérifie ce que nous
 * avons enregistré. Aucun identifiant ne l'accompagne : le nom et l'adresse ne
 * désignent rien d'autre que lui.
 */
export const shopOrderAddressSchema = z
  .object({
    name: z.string().min(1),
    street: z.string().nullable(),
    city: z.string().nullable(),
    zip: z.string().nullable(),
    country: z.string().nullable(),
  })
  .strict();

/**
 * Le détail d'une commande.
 *
 * `state` y est, contrairement à la liste : la page peut avoir besoin de traiter
 * `cancel` différemment de `draft` — un encart, une couleur — et le faire depuis
 * un libellé traduit serait fragile. Le libellé reste néanmoins la seule chose
 * affichée.
 */
export const shopOrderDetailSchema = z
  .object({
    reference: z.string().min(1),
    date: z.string().nullable(),
    state: z.enum(['draft', 'sent', 'sale', 'cancel']),
    stateLabel: z.string().min(1),
    deliveryMode: deliveryModeSchema.nullable(),
    deliveryModeLabel: z.string(),
    currency: z.string().min(1),
    amountUntaxed: z.number().nonnegative(),
    amountTax: z.number().nonnegative(),
    amountTotal: z.number().nonnegative(),
    lines: z.array(shopOrderLineSchema),
    deliveryAddress: shopOrderAddressSchema,
  })
  .strict();
export type ShopOrderDetail = z.infer<typeof shopOrderDetailSchema>;

export const shopOrderDetailEnvelopeSchema = z
  .object({ order: shopOrderDetailSchema })
  .strict();
