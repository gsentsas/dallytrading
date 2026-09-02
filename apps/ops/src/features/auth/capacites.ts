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
    capacite: 'intake_search',
    titre: 'Rechercher un dossier',
    description: 'Retrouver un dossier par nom, téléphone ou référence.',
    href: '/recherche',
  },
  {
    capacite: 'intake_create',
    titre: 'Réceptionner un colis',
    description: 'Enregistrer un colis sur un départ ouvert.',
    href: '/reception',
  },
  {
    capacite: 'consolidation_load',
    titre: 'Charger un départ',
    description: 'Vérifier ce qui part, et compléter la pile.',
    href: '/chargement',
  },
  {
    capacite: 'payment_create',
    titre: 'Encaissement',
    description: 'Saisir un paiement reçu d’un client.',
    // L'encaissement vit dans la fiche du dossier : il n'a pas d'écran à lui.
    // La carte mène donc là où l'opérateur retrouve le dossier, sans l'obliger
    // à commencer par une réception dont il n'a pas besoin.
    href: '/recherche',
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
    href: '/caisse/transferts',
  },
  {
    capacite: 'appointment_manage',
    titre: 'Agenda',
    description: 'Organiser les passages de la journée.',
    href: '/agenda',
  },
  {
    capacite: 'supervise',
    titre: 'Supervision',
    description: 'Suivre l’activité de l’équipe.',
    href: '/activite',
  },
];

export function entreesAutorisees(
  capacites: Readonly<Record<string, boolean>>,
): readonly EntreeAccueil[] {
  return ENTREES_ACCUEIL.filter((entree) => capacites[entree.capacite] === true);
}
