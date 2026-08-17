/**
 * Le contrat du formulaire de commande, et la commande rendue.
 *
 * ## Ce que le navigateur peut envoyer
 *
 * Un mode de remise, et pour un invité son identité. **Rien d'autre.** Ni prix,
 * ni identifiant de panier, ni identifiant de client, ni lignes.
 *
 * Les lignes n'y sont pas, et c'est délibéré : elles vivent dans le cookie scellé,
 * et le BFF les lit là. Un formulaire qui enverrait ses propres lignes permettrait
 * de commander un contenu différent de celui du panier affiché — le client
 * validerait un total qu'il a vu pour un contenu qu'il n'a pas choisi.
 *
 * L'identifiant de panier n'y est pas non plus : il vient du cookie. L'accepter du
 * navigateur laisserait choisir sa propre clé d'idempotence, donc rejouer la
 * commande de quelqu'un d'autre si on devinait son identifiant.
 *
 * ## `.strict()` partout
 *
 * Une clé inconnue est une erreur bruyante, pas un champ ignoré. C'est ce qui
 * transforme « quelque chose essaie d'envoyer un prix » en refus visible.
 */

import { z } from 'zod';

/**
 * Les deux modes de remise.
 *
 * `delivery_to_confirm` est verbeux exprès : un simple `delivery` laisserait
 * croire qu'un tarif existe quelque part. Il n'en existe aucun au MVP, et
 * inventer un montant « à titre indicatif » serait pire que ne rien afficher.
 */
export const deliveryModeSchema = z.enum(['pickup', 'delivery_to_confirm']);
export type DeliveryMode = z.infer<typeof deliveryModeSchema>;

/** Texte obligatoire, borné, débarrassé de ses espaces de bord. */
const texte = (max: number) =>
  z
    .string()
    .transform((valeur) => valeur.trim())
    .refine((valeur) => valeur.length > 0, { message: 'Ce champ est requis.' })
    .refine((valeur) => valeur.length <= max, {
      message: `Ce champ ne peut pas dépasser ${max} caractères.`,
    });

/** Texte facultatif : une chaîne vide devient `undefined`, jamais `''`. */
const texteFacultatif = (max: number) =>
  z
    .string()
    .transform((valeur) => valeur.trim())
    .refine((valeur) => valeur.length <= max, {
      message: `Ce champ ne peut pas dépasser ${max} caractères.`,
    })
    .transform((valeur) => (valeur.length === 0 ? undefined : valeur))
    .optional();

/**
 * Contrôle d'adresse volontairement permissif, aligné sur celui d'Odoo.
 *
 * Il écarte l'absurde sans prétendre valider une adresse : une expression stricte
 * refuse des adresses valides, et la seule preuve qu'une adresse existe est qu'un
 * message y arrive. Le même motif des deux côtés, pour qu'un formulaire ne soit
 * jamais accepté ici et refusé là.
 */
const EMAIL = /^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$/;

/**
 * L'identité d'un invité.
 *
 * Les longueurs reprennent exactement celles du contrôleur Odoo. Deux jeux de
 * bornes divergents produiraient des formulaires acceptés par le navigateur et
 * refusés par le serveur, ce qui est la pire des deux situations : le client a
 * saisi, et on lui dit non sans lui dire quoi corriger.
 */
export const guestCustomerSchema = z
  .object({
    name: texte(128),
    email: texte(254).refine((valeur) => EMAIL.test(valeur), {
      message: 'Merci d’indiquer une adresse e-mail valide.',
    }),
    phone: texteFacultatif(32),
    street: texteFacultatif(200),
    city: texteFacultatif(100),
    zip: texteFacultatif(20),
    /** Code ISO à deux lettres. Odoo résout le pays lui-même. */
    country_code: z
      .string()
      .trim()
      .toUpperCase()
      .refine((valeur) => valeur === '' || /^[A-Z]{2}$/.test(valeur), {
        message: 'Le code pays doit comporter deux lettres.',
      })
      .transform((valeur) => (valeur === '' ? undefined : valeur))
      .optional(),
  })
  .strict();
export type GuestCustomer = z.infer<typeof guestCustomerSchema>;

/**
 * Ce que le formulaire envoie au BFF.
 *
 * `customer` est absent pour un client connecté. Ce n'est pas une commodité :
 * la route connectée le **refuse**, parce qu'un client connecté qui enverrait une
 * identité essaierait de commander au nom d'un autre.
 */
export const checkoutRequestSchema = z
  .object({
    deliveryMode: deliveryModeSchema,
    customer: guestCustomerSchema.optional(),
  })
  .strict();
export type CheckoutRequest = z.infer<typeof checkoutRequestSchema>;

/** Une ligne de la commande créée. */
export const orderLineSchema = z
  .object({
    reference: z.string().min(1),
    name: z.string().min(1),
    quantity: z.number().positive(),
    unitPrice: z.number().nonnegative(),
    subtotal: z.number().nonnegative(),
  })
  .strict();

/**
 * La commande, telle qu'Odoo la rend.
 *
 * `status` est une énumération fermée sur les quatre états de `sale.order`. Au
 * MVP seul `draft` peut sortir d'ici — rien ne confirme automatiquement — mais
 * fermer l'énumération fait échouer le contrat le jour où quelque chose
 * commencerait à confirmer, plutôt que d'afficher un état inconnu.
 */
export const shopOrderSchema = z
  .object({
    reference: z.string().min(1),
    status: z.enum(['draft', 'sent', 'sale', 'cancel']),
    deliveryMode: deliveryModeSchema,
    deliveryModeLabel: z.string(),
    currency: z.string().min(1),
    amountUntaxed: z.number().nonnegative(),
    amountTax: z.number().nonnegative(),
    amountTotal: z.number().nonnegative(),
    lines: z.array(orderLineSchema),
    /** Vrai si Odoo a rendu une commande existante au lieu d'en créer une. */
    replayed: z.boolean(),
  })
  .strict();
export type ShopOrder = z.infer<typeof shopOrderSchema>;
