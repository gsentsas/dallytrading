/**
 * Le vocabulaire et les décisions de la carte d'état, hors de React.
 *
 * Ce module n'importe rien : il vit dans un composant client sans y entraîner
 * la passerelle Odoo, et il se teste sans navigateur. Les gestes de l'écran —
 * quoi proposer, quoi confirmer, quoi faire d'une réponse — sont des décisions,
 * pas du rendu : les sortir du composant les rend vérifiables une par une.
 */

/** Les deux seules étapes que le terrain peut demander. */
export type CibleEtat = 'preparing' | 'ready';

export const LIBELLES_ACTION: Readonly<Record<CibleEtat, string>> = {
  preparing: 'Mettre en préparation',
  ready: 'Marquer prêt à expédier',
};

/**
 * Les étapes dont la conséquence mérite qu'on s'arrête.
 *
 * Les deux, en réalité. `preparing` paraissait interne : il ne l'est pas. La
 * politique de publication `dally.freight.state.policy` lui donne un libellé
 * client et le rend visible au suivi comme au portail. Un geste qui parle au
 * client mérite un arrêt, même bref.
 *
 * `ready` y ajoute le gel des articles côté Dally Ops.
 *
 * On annonce ces faits — et rien de plus : aucun envoi de message n'est
 * démontré par le code, donc rien ne le promet.
 */
export const CONFIRMATION_ACTION: Readonly<Partial<Record<CibleEtat, string>>> = {
  preparing:
    'Le dossier sera marqué « En préparation ». Cette étape sera visible dans '
    + 'le suivi client. Continuer ?',
  ready:
    'Le dossier sera marqué « Prêt à expédier ». Cette étape sera visible dans '
    + 'le suivi client et les articles ne pourront plus être modifiés depuis '
    + 'Dally Ops.',
};

/** Ce que l'écran sait nommer. Un code inconnu ne se propose pas. */
export function actionsProposables(
  codes: readonly string[],
): readonly CibleEtat[] {
  return codes.filter((code): code is CibleEtat => code in LIBELLES_ACTION);
}

export function demandeConfirmation(cible: CibleEtat): string | undefined {
  return CONFIRMATION_ACTION[cible];
}

/**
 * Ce qu'un appui sur une action déclenche.
 *
 * Jamais l'envoi directement : c'est cette fonction qui décide, et les deux
 * étapes offertes au terrain passent aujourd'hui par une confirmation. Le
 * chemin vers le serveur ne s'ouvre donc que depuis « Confirmer » — ce qui
 * rend « Annuler » incapable d'écrire, par construction plutôt que par
 * vigilance.
 */
export type GesteDemande =
  | { readonly etape: 'confirmer'; readonly message: string }
  | { readonly etape: 'envoyer' };

export function gesteDemande(cible: CibleEtat): GesteDemande {
  const message = demandeConfirmation(cible);
  return message ? { etape: 'confirmer', message } : { etape: 'envoyer' };
}

export interface Geste {
  readonly cible: CibleEtat;
  readonly uuid: string;
}

/**
 * L'identifiant du geste en cours.
 *
 * Réessayer après une coupure doit renvoyer **le même** geste : un nouvel
 * identifiant ferait une seconde transition d'un doigt qui n'a appuyé qu'une
 * fois. On n'en tire un nouveau que lorsque la cible change.
 */
export function identifiantDeGeste(
  courant: Geste | null, cible: CibleEtat, nouveau: () => string,
): Geste {
  return courant && courant.cible === cible ? courant : { cible, uuid: nouveau() };
}

export interface CorpsTransition {
  readonly request_uuid: string;
  readonly expected_state: string;
  readonly target_state: CibleEtat;
}

/** Le corps envoyé — exactement trois champs, jamais un de plus. */
export function corpsTransition(
  requestUuid: string, expectedState: string, cible: CibleEtat,
): CorpsTransition {
  return {
    request_uuid: requestUuid,
    expected_state: expectedState,
    target_state: cible,
  };
}

export type IssueTransition =
  | { readonly issue: 'ok' }
  /** Le dossier a bougé : on recharge, on ne force jamais. */
  | { readonly issue: 'perime'; readonly message: string }
  /** Le réseau a lâché : la **même** tentative peut repartir. */
  | { readonly issue: 'reessayable'; readonly message: string }
  | { readonly issue: 'refus'; readonly message: string };

const MESSAGE_PERIME =
  'Le dossier a changé depuis son affichage. Son état vient d’être actualisé.';

/**
 * Ce que l'écran fait d'une réponse.
 *
 * Un `state_changed` n'est pas une erreur à réessayer : c'est une information
 * dont la seule suite correcte est de rafraîchir. Les confondre ferait boucler
 * l'opérateur sur un bouton qui ne peut plus aboutir.
 */
export function interpreterReponse(
  ok: boolean, corps: { success?: boolean; code?: string; error?: string } | null,
): IssueTransition {
  if (ok && corps?.success === true) return { issue: 'ok' };
  if (corps?.code === 'state_changed') {
    return { issue: 'perime', message: MESSAGE_PERIME };
  }
  return {
    issue: 'refus',
    message: typeof corps?.error === 'string'
      ? corps.error : 'Cette étape n’est pas possible pour l’instant.',
  };
}

/** Le type précis se conserve : l'appelant lit `message` sans le redéduire. */
export type IssueReessayable = Extract<IssueTransition, { issue: 'reessayable' }>;

export function issueReseau(): IssueReessayable {
  return {
    issue: 'reessayable',
    message: 'Connexion interrompue. Vous pouvez réessayer.',
  };
}

export function issueHorsLigne(): IssueReessayable {
  return {
    issue: 'reessayable',
    message: 'Connexion requise pour changer l’état du dossier.',
  };
}
