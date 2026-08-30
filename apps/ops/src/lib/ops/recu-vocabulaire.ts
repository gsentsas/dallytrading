/**
 * Le vocabulaire du reçu, utilisable des deux côtés.
 *
 * Ce module n'importe rien. C'est ce qui lui permet de vivre dans un composant
 * client sans y entraîner la passerelle Odoo et la configuration serveur —
 * l'erreur qui avait fait planter l'écran des dépenses, et que
 * `features/frontiere-client.test.ts` surveille depuis.
 */

/**
 * Le nom du fichier téléchargé.
 *
 * Ne porte que la référence du dossier. Un téléphone de terrain passe de main
 * en main, et un nom de client dans une liste de téléchargements en dirait
 * trop — sur qui expédie, et sur quoi.
 *
 * Tout ce qui n'est ni lettre, ni chiffre, ni tiret bas, ni tiret devient un
 * tiret : une référence forgée ne peut pas fabriquer un chemin.
 */
export function nomFichierRecu(reference: string): string {
  const propre = reference.replace(/[^A-Za-z0-9_-]/g, '-').replace(/^-+|-+$/g, '');
  return `Recu_DallyTrading_${propre.slice(0, 60) || 'recu'}.pdf`;
}
