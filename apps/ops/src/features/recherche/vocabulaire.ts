/**
 * Le vocabulaire de la recherche, utilisable des deux côtés.
 *
 * Ce module n'importe rien : c'est ce qui lui permet de vivre dans un
 * composant client sans y entraîner la passerelle Odoo. Même raison que
 * `lib/ops/recu-vocabulaire.ts`.
 */

/** L'état opérationnel, dans les mots du comptoir. */
const ETATS: Readonly<Record<string, string>> = {
  draft: 'Brouillon',
  request_received: 'Annoncé',
  awaiting_goods: 'En attente',
  goods_received: 'Déposé',
  preparing: 'En préparation',
  ready: 'Prêt',
  departed: 'Parti',
  in_transit: 'En transit',
  arrived: 'Arrivé',
  customs: 'En douane',
  available: 'À retirer',
  out_for_delivery: 'En livraison',
  delivered: 'Retiré',
  cancelled: 'Annulé',
};

const MODES: Readonly<Record<string, string>> = { air: 'Aérien', sea: 'Maritime' };

export function libelleEtat(code: string): string {
  return ETATS[code] ?? code;
}

export function libelleMode(code: string): string {
  return MODES[code] ?? code;
}

/**
 * L'adresse de la fiche d'un dossier.
 *
 * Prend la référence **globale** et rien d'autre. Un appelant qui lui passerait
 * `A001` ouvrirait le dossier d'un autre départ ; la signature ne le dit pas,
 * mais l'unique appelant est testé pour cela.
 */
export function cheminFicheDossier(referenceGlobale: string): string {
  return `/reception/dossier/${encodeURIComponent(referenceGlobale)}`;
}
