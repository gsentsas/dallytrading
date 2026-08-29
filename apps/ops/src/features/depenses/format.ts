/**
 * Comment un montant de caisse se lit sur le terrain.
 *
 * Le franc CFA ne se divise pas : afficher « 15 000,00 FCFA » suggère une
 * précision qui n'existe pas dans la monnaie. L'euro, lui, garde ses
 * centimes — une dépense de 4,50 € arrondie à 5 € serait une erreur de caisse.
 */
export function montant(valeur: number, devise: string): string {
  try {
    return new Intl.NumberFormat('fr-FR', {
      style: 'currency',
      currency: devise,
      maximumFractionDigits: devise === 'XOF' ? 0 : 2,
    }).format(valeur);
  } catch {
    // Une devise inconnue du navigateur ne doit pas casser l'écran : on écrit
    // le nombre et le code, ce qui reste juste.
    return `${new Intl.NumberFormat('fr-FR').format(valeur)} ${devise}`;
  }
}

export const LIBELLE_ETAT: Readonly<Record<string, string>> = {
  review: 'À vérifier',
  validated: 'Validée',
  cancelled: 'Annulée',
};

/** Où en est le départ, dit en mots de quai. */
export const LIBELLE_ETAT_DEPART: Readonly<Record<string, string>> = {
  collecting: 'Collecte ouverte',
  collection_closed: 'Collecte fermée',
  ready: 'Prêt au départ',
  departed: 'Parti',
  arrived: 'Arrivé',
};
