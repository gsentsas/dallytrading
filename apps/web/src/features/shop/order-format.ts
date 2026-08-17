/**
 * Mise en forme des commandes, partagée par la liste et le détail.
 *
 * Rien ici ne calcule : ni total, ni taxe, ni conversion de devise. Le seul
 * travail est l'affichage — séparateurs de milliers, code devise, date lisible —
 * et il est fait avec la locale plutôt qu'à la main.
 */

/**
 * Un montant, tel qu'il s'affiche.
 *
 * La devise vient d'Odoo et lui est passée comme code ISO, avec repli en suffixe
 * quand ce n'en est pas un : le tarif de la boutique est libre de porter n'importe
 * quel nom, et une exception au milieu d'un rendu ferait tomber la page entière
 * pour un problème de mise en forme.
 */
export function formatOrderAmount(amount: number, currency: string): string {
  if (/^[A-Z]{3}$/.test(currency)) {
    try {
      return new Intl.NumberFormat('fr-FR', {
        style: 'currency',
        currency,
        maximumFractionDigits: 0,
      }).format(amount);
    } catch {
      // Code à trois lettres qu'Intl ne connaît pas : repli plus bas.
    }
  }
  const nombre = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 })
    .format(amount);
  return currency ? `${nombre} ${currency}` : nombre;
}

/**
 * Une date ISO, rendue lisible — ou un tiret.
 *
 * `null` est une valeur normale : `date_order` peut être vide sur une commande
 * fraîchement créée. Afficher « Invalid Date » serait pire que de ne rien dire.
 */
export function formatOrderDate(iso: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date);
}

/** Quantité affichée sans décimale inutile : Odoo stocke un flottant. */
export function formatQuantity(quantity: number): string {
  return Number.isInteger(quantity) ? String(quantity) : String(quantity);
}
