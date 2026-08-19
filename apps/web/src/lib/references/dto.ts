/**
 * Les référentiels publics, tels que le navigateur a le droit de les voir.
 *
 * ## Pourquoi un schéma alors qu'Odoo projette déjà
 *
 * Odoo décide ce qu'il publie ; ce fichier décide ce que la vitrine accepte.
 * Les deux barrières ne protègent pas de la même chose. Celle d'Odoo empêche
 * une fuite de conception. Celle-ci empêche qu'un champ ajouté un jour côté
 * serveur — par nous ou par une mise à jour du fournisseur — traverse
 * silencieusement jusqu'à la page.
 *
 * `.strict()` n'est donc pas de la coquetterie : une clé inattendue fait
 * échouer la lecture, et l'échec est visible tout de suite plutôt que six mois
 * plus tard dans un rendu.
 *
 * ## Ce qui ne peut pas arriver ici
 *
 * Aucun transporteur, aucune compagnie, aucun navire, aucun itinéraire, aucun
 * prix. Ces champs n'existent dans aucun de ces schémas : s'ils apparaissaient
 * dans une réponse, elle serait rejetée.
 */

import { z } from 'zod';

const code = z.string().trim().min(1).max(20);
const nom = z.string().trim().min(1).max(200);

/** Un pays : ce qu'il faut pour une liste déroulante, rien de plus. */
export const referenceCountrySchema = z
  .object({ code, name: nom })
  .strict();

/** Une subdivision administrative, toujours lue dans le contexte d'un pays. */
export const referenceStateSchema = z
  .object({ code, name: nom })
  .strict();

/** Un incoterm de la CCI, tel qu'Odoo le livre. */
export const referenceIncotermSchema = z
  .object({ code, name: nom })
  .strict();

/**
 * Un lieu desservi — port, aéroport ou point terrestre.
 *
 * Les trois drapeaux sont nommés dans le vocabulaire du client (`sea`, `air`,
 * `road`) et non dans celui du fournisseur : la page n'a pas à connaître le
 * mot « ocean ».
 */
export const referenceLocationSchema = z
  .object({
    code,
    name: nom,
    city: z.string().trim().max(100).nullable(),
    country_code: z.string().trim().length(2).nullable(),
    state_code: z.string().trim().max(10).nullable(),
    sea: z.boolean(),
    air: z.boolean(),
    road: z.boolean(),
  })
  .strict();

export type ReferenceCountry = z.output<typeof referenceCountrySchema>;
export type ReferenceState = z.output<typeof referenceStateSchema>;
export type ReferenceIncoterm = z.output<typeof referenceIncotermSchema>;
export type ReferenceLocation = z.output<typeof referenceLocationSchema>;

/** Les quatre référentiels publiés, et le schéma de chacun. */
export const REFERENCE_KINDS = {
  countries: referenceCountrySchema,
  states: referenceStateSchema,
  locations: referenceLocationSchema,
  incoterms: referenceIncotermSchema,
} as const;

export type ReferenceKind = keyof typeof REFERENCE_KINDS;

export function isReferenceKind(value: string): value is ReferenceKind {
  return Object.prototype.hasOwnProperty.call(REFERENCE_KINDS, value);
}

/**
 * Les modes proposés au public.
 *
 * `road` figure ici alors que le référentiel des points terrestres est encore
 * vide : le domaine doit être juste avant d'être peuplé, sans quoi le jour où
 * le premier point sera saisi, personne ne saura si le filtre marche.
 */
export const PUBLIC_MODES = ['sea', 'air', 'road'] as const;
export type PublicMode = (typeof PUBLIC_MODES)[number];

export function isPublicMode(value: string): value is PublicMode {
  return (PUBLIC_MODES as readonly string[]).includes(value);
}

/** Les lieux compatibles avec un mode. Sans mode, la liste entière. */
export function locationsForMode(
  locations: ReadonlyArray<ReferenceLocation>,
  mode: PublicMode | undefined,
): ReadonlyArray<ReferenceLocation> {
  if (!mode) return locations;
  return locations.filter((location) => location[mode]);
}

/**
 * Le mode physique d'une demande.
 *
 * Le service donne le mode, sauf le groupage qui le porte à part. Le transport
 * de véhicule est absent volontairement : son mode se lit sur la cargaison, et
 * son formulaire ne change pas dans ce cycle.
 */
export function modeForService(
  serviceCode: string | undefined,
  groupageMode: 'sea' | 'air' | undefined,
): PublicMode | undefined {
  if (serviceCode === 'freight_sea') return 'sea';
  if (serviceCode === 'freight_air') return 'air';
  if (serviceCode === 'freight_groupage') return groupageMode;
  return undefined;
}
