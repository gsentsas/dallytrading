/**
 * Comment une date se lit sur un quai.
 *
 * ## Le fuseau, et pourquoi c'est UTC
 *
 * Odoo renvoie les horodatages en UTC, suffixés `Z`. Les afficher dans le
 * fuseau du navigateur donnerait un résultat juste à Paris et faux ailleurs —
 * or l'entrepôt est à Dakar, qui vit à UTC toute l'année. Formater en UTC,
 * c'est donc afficher l'heure locale de ceux qui lisent l'écran, et non celle
 * du téléphone d'un collègue en déplacement.
 */

const JOUR = new Intl.DateTimeFormat('fr-FR', {
  day: '2-digit',
  month: 'long',
  year: 'numeric',
  timeZone: 'UTC',
});

/** `2026-09-05T10:00:00Z` ou `2026-09-03` → « 05 septembre 2026 ». */
export function enJour(valeur: string | null): string | null {
  if (!valeur) return null;
  const instant = new Date(valeur.length === 10 ? `${valeur}T00:00:00Z` : valeur);
  if (Number.isNaN(instant.getTime())) return null;
  return JOUR.format(instant);
}

export const LIBELLE_MODE: Readonly<Record<string, string>> = {
  air: 'Aérien',
  sea: 'Maritime',
};

/**
 * « Dakar → Paris ».
 *
 * La ville prime sur le code d'escale : un logisticien connaît Paris, pas
 * forcément CDG. Le code sert de repli quand la ville manque, et la référence
 * complète reste affichée juste au-dessus.
 */
export function enRoute(origine: Lieu, destination: Lieu): string {
  const nom = (lieu: Lieu) => lieu.city || lieu.location || lieu.country_code || '—';
  return `${nom(origine)} → ${nom(destination)}`;
}

/**
 * Un lieu, tel que les écrans le reçoivent.
 *
 * Le code pays est facultatif : la liste des réceptions le demande à Odoo, la
 * liste des dépenses non — elle n'en a pas besoin pour reconnaître un départ,
 * et ce qui n'est pas demandé ne voyage pas.
 */
interface Lieu {
  readonly city: string;
  readonly location: string;
  readonly country_code?: string;
}
