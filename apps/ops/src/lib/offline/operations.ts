/**
 * Ce que chaque opération de la file sait faire d'elle-même.
 *
 * Un seul endroit décrit, pour chaque type : à quelle route du BFF elle
 * s'adresse, ce qu'elle envoie, et ce qu'elle retient de la réponse. Disperser
 * cela dans le moteur de synchronisation obligerait ce dernier à connaître le
 * métier, et rendrait l'ajout d'un type risqué.
 *
 * ## Le `request_uuid` n'est pas une donnée de formulaire
 *
 * Il vit sur l'entrée de file, pas dans la charge saisie. Le moteur l'y injecte
 * au moment de l'envoi, et la même valeur repart à chaque tentative — c'est ce
 * qui distingue une reprise réseau d'une seconde opération métier.
 */

import type { MutationLocale, TypeOperation } from '@/lib/offline/types';

export interface Descripteur {
  /** La route du BFF, construite à partir de la cible quand il en faut une. */
  readonly chemin: (mutation: MutationLocale) => string;
  /** Vrai si l'opération a besoin d'une cible avant de pouvoir partir. */
  readonly exigeCible: boolean;
  /** Ce que le serveur a rendu et qui identifie l'objet créé. */
  readonly reference: (donnees: unknown) => string | null;
}

function segment(valeur: string | null): string {
  return encodeURIComponent(valeur ?? '');
}

/** Lit un chemin dans une réponse sans supposer sa forme. */
function lire(donnees: unknown, ...chemins: string[][]): string | null {
  for (const chemin of chemins) {
    let courant: unknown = donnees;
    for (const cle of chemin) {
      if (typeof courant !== 'object' || courant === null) { courant = null; break; }
      courant = (courant as Record<string, unknown>)[cle];
    }
    if (typeof courant === 'string' && courant) return courant;
  }
  return null;
}

export const DESCRIPTEURS: Readonly<Record<TypeOperation, Descripteur>> = {
  intake_create: {
    chemin: () => '/api/intakes',
    exigeCible: false,
    // Le vrai `Axxx`, alloué par Odoo. Le navigateur ne le connaissait pas.
    reference: (donnees) => lire(donnees, ['intake', 'reference']),
  },
  wave_payment: {
    chemin: (m) => `/api/shipments/${segment(m.target_reference)}/payments`,
    exigeCible: true,
    reference: (donnees) => lire(donnees, ['payment', 'reference']),
  },
  expense_create: {
    chemin: () => '/api/expenses',
    exigeCible: false,
    reference: (donnees) => lire(donnees, ['expense', 'reference']),
  },
  cash_transfer_create: {
    chemin: () => '/api/cash-transfers',
    exigeCible: false,
    reference: (donnees) => lire(donnees, ['transfer', 'reference']),
  },
  appointment_create: {
    chemin: () => '/api/appointments',
    exigeCible: false,
    reference: (donnees) => lire(donnees, ['appointment', 'reference']),
  },
  appointment_present: {
    chemin: (m) => `/api/appointments/${segment(m.target_reference)}/present`,
    exigeCible: true,
    reference: (donnees) => lire(donnees, ['appointment', 'reference']),
  },
  appointment_absent: {
    chemin: (m) => `/api/appointments/${segment(m.target_reference)}/absent`,
    exigeCible: true,
    reference: (donnees) => lire(donnees, ['appointment', 'reference']),
  },
  appointment_reschedule: {
    chemin: (m) => `/api/appointments/${segment(m.target_reference)}/reschedule`,
    exigeCible: true,
    reference: (donnees) => lire(donnees, ['appointment', 'reference']),
  },
};

/** Le corps exact envoyé au BFF, identifiant de demande compris. */
export function corpsDeLaMutation(mutation: MutationLocale): Record<string, unknown> {
  return { ...mutation.payload, request_uuid: mutation.request_uuid };
}
