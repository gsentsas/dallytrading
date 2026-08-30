/**
 * Les départs ouverts à la réception, côté serveur Next.
 *
 * Ce module ne décide de rien : le périmètre — société, état, mode, tri — est
 * imposé par Odoo, qui est la seule autorité sur la question. Ce qu'il fait,
 * c'est **refuser ce qu'il ne reconnaît pas**.
 *
 * ## Pourquoi valider une réponse qui vient de notre propre serveur
 *
 * Parce que le contrat doit casser du bon côté. Le jour où quelqu'un ajoutera
 * un champ au DTO Odoo — un identifiant, un poids, un nom d'expéditeur — la
 * validation ici le laissera au vestiaire au lieu de le transmettre au
 * navigateur. Un champ qui n'arrive jamais jusqu'à la page ne peut pas fuiter
 * dans une capture d'écran, un journal de navigateur ou un rapport de bogue.
 */

import { z } from 'zod';

import { opsGet } from '@/lib/auth/odoo-ops';

const lieu = z.object({
  country_code: z.string(),
  city: z.string(),
  location: z.string(),
});

/**
 * Le contrat, figé.
 *
 * Les textes absents valent `""`, les dates absentes valent `null`. Cette
 * asymétrie est celle d'Odoo et elle est délibérée : une ville vide ne
 * s'affiche pas, tandis qu'une date inventée serait un mensonge.
 */
const consolidation = z.object({
  reference: z.string().min(1),
  transport_mode: z.enum(['air', 'sea']),
  direction: z.string(),
  origin: lieu,
  destination: lieu,
  collection_close_on: z.string().nullable(),
  scheduled_departure: z.string().nullable(),
});

const charge = z.object({
  consolidations: z.array(consolidation),
});

export type Lieu = z.infer<typeof lieu>;
export type Consolidation = z.infer<typeof consolidation>;

/**
 * Les départs sur lesquels l'opérateur peut encore déposer un colis.
 *
 * Aucun filtre n'est transmis : il n'y a rien à transmettre. Odoo répond en
 * fonction de la session, et de rien d'autre.
 */
export async function fetchConsolidations(
  sessionId: string,
  correlationId: string,
): Promise<Consolidation[]> {
  const brut = await opsGet<unknown>('consolidations', sessionId, correlationId);
  // `parse` retire les clés inconnues : c'est ici que le contrat se referme.
  return charge.parse(brut).consolidations;
}
