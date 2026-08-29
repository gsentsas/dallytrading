/**
 * Le vocabulaire de la file hors connexion.
 *
 * ## Pourquoi les états sont si nombreux
 *
 * Quatre suffiraient à un tableau de bord. Il en faut sept pour ne pas mentir
 * à un opérateur debout dans un entrepôt sans réseau : « en attente » et
 * « bloqué par une opération précédente » appellent des gestes différents, et
 * « erreur métier » ne se répare pas comme « session expirée ».
 *
 * Le mensonge que cette liste existe pour empêcher est toujours le même :
 * afficher « synchronisé » parce que la requête est partie.
 */

/** Ce qu'une opération peut être, du point de vue de l'opérateur. */
export const ETATS = [
  /** Le formulaire n'existe que sur cet appareil, non confirmé. */
  'draft_local',
  /** Confirmé par l'opérateur : à envoyer au CRM dès que possible. */
  'pending',
  /** Une tentative est réellement en cours. */
  'syncing',
  /** Le serveur a répondu positivement. Et **seulement** dans ce cas. */
  'synced',
  /** Refus métier : l'opération ne partira pas telle quelle. */
  'error',
  /** La session a expiré : on attend que le propriétaire se reconnecte. */
  'auth_required',
  /** L'opération dont celle-ci dépend a échoué définitivement. */
  'blocked',
] as const;

export type EtatMutation = (typeof ETATS)[number];

/** Les états qui attendent encore quelque chose du réseau. */
export const ETATS_EN_ATTENTE: readonly EtatMutation[] = [
  'pending', 'syncing', 'auth_required',
];

/** Les états qu'un opérateur doit voir signalés. */
export const ETATS_A_SIGNALER: readonly EtatMutation[] = [
  'pending', 'syncing', 'error', 'auth_required', 'blocked',
];

/**
 * Les opérations que la file sait rejouer.
 *
 * Chacune a été vérifiée : son contrat porte un `request_uuid`, et le serveur
 * tient un registre d'idempotence assorti d'une contrainte d'unicité. Une
 * opération dont le serveur ne saurait pas absorber le rejeu n'a rien à faire
 * ici — la file la transformerait en doublon silencieux.
 *
 * `prepare-reception` en est volontairement absente : l'étape 12 a établi
 * qu'elle ne crée aucun objet métier et qu'Odoo n'en tient pas de registre.
 * Elle se refait en ligne, sans rien à dédupliquer.
 */
export const OPERATIONS = [
  'intake_create',
  'wave_payment',
  'expense_create',
  'cash_transfer_create',
  'appointment_create',
  'appointment_present',
  'appointment_absent',
  'appointment_reschedule',
] as const;

export type TypeOperation = (typeof OPERATIONS)[number];

/** Ce que l'opérateur lit à la place du code technique. */
export const LIBELLES_OPERATION: Readonly<Record<TypeOperation, string>> = {
  intake_create: 'Réception de colis',
  wave_payment: 'Paiement Wave',
  expense_create: 'Dépense de caisse',
  cash_transfer_create: 'Transfert de caisse',
  appointment_create: 'Rendez-vous',
  appointment_present: 'Client présent',
  appointment_absent: 'Client absent',
  appointment_reschedule: 'Report de rendez-vous',
};

export const LIBELLES_ETAT: Readonly<Record<EtatMutation, string>> = {
  draft_local: 'Brouillon sur cet appareil',
  pending: 'En attente de synchronisation',
  syncing: 'Synchronisation en cours',
  synced: 'Synchronisé avec le CRM',
  error: 'Erreur — action requise',
  auth_required: 'Session expirée — reconnectez-vous',
  blocked: 'Bloqué par une opération précédente',
};

/**
 * Une opération en file.
 *
 * `request_uuid` est tiré **avant la première tentative réseau** et ne change
 * jamais : c'est lui qui permet au serveur de reconnaître un rejeu plutôt que
 * de créer un second objet. Le renouveler à chaque tentative transformerait
 * une reprise réseau en nouvelle opération métier — le défaut exact que toute
 * cette mécanique existe pour empêcher.
 */
export interface MutationLocale {
  /** Identité locale, stable, jamais envoyée au serveur comme donnée métier. */
  readonly local_id: string;
  readonly request_uuid: string;
  readonly operation_type: TypeOperation;
  /**
   * À qui appartient l'opération.
   *
   * Une empreinte de l'identifiant de connexion, pas un identifiant Odoo :
   * il suffit de savoir si l'utilisateur courant est le même, et rien de plus
   * n'a à séjourner dans un navigateur d'entrepôt.
   */
  readonly owner_key: string;
  /** La cible, quand l'opération porte sur un objet existant (`Axxx`, référence). */
  readonly target_reference: string | null;
  /** L'opération dont celle-ci dépend, quand elle en a une. */
  readonly parent_local_id: string | null;
  /** Le corps exact que le BFF attend, à un détail près : voir `sync.ts`. */
  readonly payload: Record<string, unknown>;
  /** De quoi afficher la ligne sans rien deviner. */
  readonly resume: string;
  readonly status: EtatMutation;
  readonly created_at: number;
  readonly updated_at: number;
  readonly attempt_count: number;
  readonly next_retry_at: number;
  readonly last_attempt_at: number | null;
  readonly last_error_code: string | null;
  readonly last_error_message: string | null;
  /** La référence rendue par le serveur — le vrai `Axxx`, par exemple. */
  readonly server_reference: string | null;
}

/** Un brouillon : un formulaire à moitié rempli, propre à cet appareil. */
export interface BrouillonLocal {
  readonly local_id: string;
  readonly owner_key: string;
  readonly operation_type: TypeOperation;
  readonly payload: Record<string, unknown>;
  readonly resume: string;
  readonly created_at: number;
  readonly updated_at: number;
}
