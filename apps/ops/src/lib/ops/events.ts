/**
 * Le contrat des événements opérationnels d'un dossier.
 *
 * ## Ce que le navigateur n'envoie jamais
 *
 * Ni l'état, ni la description, ni la date métier, ni la visibilité client, ni
 * l'auteur. Trois champs partent : l'identifiant du geste, la nature choisie,
 * et la note de l'opérateur. Tout le reste est décidé par le serveur — et
 * `.strict()` fait tomber la demande si un champ de plus s'y glisse, plutôt
 * que de l'ignorer en silence.
 *
 * ## Ce que le navigateur ne reçoit jamais
 *
 * Aucune clé primaire, aucune société, aucun `res_model`, aucun identifiant
 * d'utilisateur. L'auteur se lit par son nom, le dossier par la référence que
 * l'appelant possède déjà.
 */

import { z } from 'zod';

import { opsGet, opsPost } from '@/lib/auth/odoo-ops';

/** Les sept natures. Fermé côté serveur, fermé ici. */
export const natureEvenement = z.enum([
  'anomaly', 'damage_noted', 'customer_contacted',
  'awaiting_customer', 'repacked', 'handover', 'other',
]);

export type NatureEvenement = z.infer<typeof natureEvenement>;

/** Ce que le serveur rend pour chaque événement saisi. */
export const evenement = z.object({
  kind: z.string().max(40),
  kind_label: z.string().max(120),
  // Sans borne, délibérément : côté Odoo `description` est un `Char` et
  // `internal_note` un `Text`, ni l'un ni l'autre dimensionné, et la liste
  // inclut les événements créés au back-office. Refuser ici une valeur
  // qu'Odoo accepte ferait tomber la lecture en 503 et effacerait toute la
  // frise du dossier. La borne de saisie, elle, reste au contrat d'écriture.
  description: z.string(),
  note: z.string(),
  status: z.string().max(40),
  status_label: z.string().max(120),
  event_date: z.string().max(40),
  recorded_by: z.string().max(120),
  source: z.enum(['ops', 'backoffice']),
}).strict();

/**
 * Les natures proposées viennent du serveur, avec leur règle de note.
 *
 * L'écran ne tient pas sa propre liste : le jour où une huitième nature
 * apparaît, elle descend sans qu'aucune ligne de navigateur ne change.
 */
export const natureProposee = z.object({
  kind: natureEvenement,
  label: z.string().min(1).max(120),
  note_required: z.boolean(),
}).strict();

export const evenementsDossier = z.object({
  events: z.array(evenement).max(50),
  can_add: z.boolean(),
  kinds: z.array(natureProposee).max(16),
}).strict();

export type Evenement = z.infer<typeof evenement>;
export type NatureProposee = z.infer<typeof natureProposee>;
export type EvenementsDossier = z.infer<typeof evenementsDossier>;

/** Exactement ce qu'un geste envoie. */
export const demandeEvenement = z.object({
  request_uuid: z.string().uuid(),
  kind: natureEvenement,
  note: z.string().max(1000).optional(),
}).strict();

export type DemandeEvenement = z.infer<typeof demandeEvenement>;

const evenementEnregistre = z.object({
  event: evenement,
  replayed: z.boolean(),
}).strict();

export type EvenementEnregistre = z.infer<typeof evenementEnregistre>;

/** La borne de la note, redite ici pour refuser avant le réseau. */
export const LONGUEUR_NOTE = 1000;

function ressource(reference: string): string {
  if (!/^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$/.test(reference)) {
    throw new Error('Référence de dossier invalide.');
  }
  return `intakes/${reference}/events`;
}

export async function fetchEvents(
  reference: string, sessionId: string, correlationId: string,
): Promise<EvenementsDossier> {
  return evenementsDossier.parse(
    await opsGet(ressource(reference), sessionId, correlationId));
}

export async function createEvent(
  reference: string,
  demande: DemandeEvenement,
  sessionId: string,
  correlationId: string,
): Promise<EvenementEnregistre> {
  return evenementEnregistre.parse(
    await opsPost(ressource(reference), demande, sessionId, correlationId));
}
