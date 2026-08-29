/**
 * Ce que l'interface sait faire, indexé par capacité.
 *
 * L'interface ne connaît pas les rôles. Elle ne teste jamais
 * `role === 'supervisor'` : elle demande `capabilities.intake_create`. Le jour
 * où un troisième rôle apparaîtra, ou bien où une capacité changera de rôle,
 * rien ici ne bougera — c'est Odoo qui décide, et lui seul.
 */

export interface EntreeAccueil {
  readonly capacite: string;
  readonly titre: string;
  readonly description: string;
  /** Écran ouvert par l'entrée. Absent tant qu'elle n'en a pas. */
  readonly href?: string;
}

export const ENTREES_ACCUEIL: readonly EntreeAccueil[] = [
  {
    capacite: 'intake_create',
    titre: 'Réceptionner un colis',
    description: 'Enregistrer un colis sur un départ ouvert.',
    href: '/reception',
  },
  {
    capacite: 'payment_create',
    titre: 'Encaissement',
    description: 'Saisir un paiement reçu d’un client.',
  },
  {
    capacite: 'expense_create',
    titre: 'Dépense de caisse',
    description: 'Déclarer une dépense engagée sur le terrain.',
    href: '/depenses',
  },
  {
    capacite: 'transfer_create',
    titre: 'Transfert de caisse',
    description: 'Transmettre des espèces à un autre opérateur.',
  },
  {
    capacite: 'appointment_manage',
    titre: 'Rendez-vous',
    description: 'Organiser les passages de la journée.',
  },
  {
    capacite: 'supervise',
    titre: 'Supervision',
    description: 'Suivre l’activité de l’équipe.',
  },
];

export function entreesAutorisees(
  capacites: Readonly<Record<string, boolean>>,
): readonly EntreeAccueil[] {
  return ENTREES_ACCUEIL.filter((entree) => capacites[entree.capacite] === true);
}
