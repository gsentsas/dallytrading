/**
 * Le contrat de l'avancement d'état d'un dossier.
 *
 * ## Ce que le navigateur ne décide pas
 *
 * La machine à états vit dans Odoo. Ce module ne connaît ni la matrice, ni les
 * portes métier, ni l'ordre des étapes : il transmet ce que l'écran a demandé
 * et refuse ce qu'il ne reconnaît pas au retour.
 *
 * `expected_state` accompagne chaque geste. L'écran agit sur un état qu'il a lu
 * il y a peut-être une minute ; le serveur compare avant d'écrire, et répond
 * `state_changed` plutôt que d'écraser une décision plus récente.
 */

import { z } from 'zod';

import { opsPost } from '@/lib/auth/odoo-ops';

/** Les deux seules étapes qu'un opérateur de terrain peut demander. */
export const cibleTransition = z.enum(['preparing', 'ready']);

export const etatDossier = z.object({
  status: z.enum(['updated', 'replayed']),
  reference: z.string().min(1).max(120),
  state: z.string().min(1).max(40),
  allowed_transitions: z.array(cibleTransition).max(2),
}).strict();

export type CibleTransition = z.infer<typeof cibleTransition>;
export type EtatDossier = z.infer<typeof etatDossier>;

export const demandeTransition = z.object({
  request_uuid: z.string().uuid(),
  expected_state: z.string().min(1).max(40),
  target_state: cibleTransition,
}).strict();

export type DemandeTransition = z.infer<typeof demandeTransition>;

/**
 * Demande l'étape suivante.
 *
 * Aucune borne n'est appliquée ici : le rôle, le périmètre, l'état attendu et
 * la cible sont vérifiés par Odoo. Les répéter donnerait l'illusion que le
 * navigateur y participe.
 */
export async function advanceIntakeState(
  reference: string,
  demande: DemandeTransition,
  sessionId: string,
  correlationId: string,
): Promise<EtatDossier> {
  if (!/^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$/.test(reference)) {
    throw new Error('Référence de dossier invalide.');
  }
  return etatDossier.parse(
    await opsPost(`intakes/${reference}/state`, demande, sessionId, correlationId),
  );
}
