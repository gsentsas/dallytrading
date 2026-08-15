import { notFound } from 'next/navigation';

import { PortalGatewayError } from '@/lib/portal/odoo-portal';

/**
 * Charge une ressource, ou traduit l'échec en quelque chose d'affichable.
 *
 * ## La règle qui compte : `not_found` et `unauthenticated` mènent au même 404
 *
 * Quand Odoo refuse une référence, c'est indistinctement parce qu'elle n'existe
 * pas, parce qu'elle appartient à un autre client, ou parce que la proposition
 * n'a pas encore été envoyée. Le contrôleur renvoie déjà le même 404 dans les
 * trois cas ; la page doit conserver cette indistinction, sinon elle réintroduit
 * l'oracle que le contrôleur a supprimé.
 *
 * Le reste — ERP injoignable, réponse illisible, schéma inattendu — devient
 * `null`, et l'appelant affiche un état « indisponible ». Ne pas confondre les
 * deux importe : dire « introuvable » pendant une panne ferait croire au client
 * que son dossier a disparu.
 */
export async function loadPortal<T>(
  operation: () => Promise<T>,
): Promise<T | null> {
  try {
    return await operation();
  } catch (error) {
    if (error instanceof PortalGatewayError) {
      if (error.code === 'not_found') {
        notFound();
      }
      if (error.code === 'unauthenticated' || error.code === 'forbidden') {
        // Le layout a déjà vérifié la session ; si Odoo la refuse ici, elle
        // vient d'expirer. Le 404 évite de révéler que la référence existait.
        notFound();
      }
      return null;
    }
    throw error;
  }
}

/** Numéro de page issu de la query string, ramené dans le raisonnable. */
export function pageFromSearchParams(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const page = Number.parseInt(raw ?? '1', 10);
  return Number.isFinite(page) && page > 0 ? Math.min(page, 10_000) : 1;
}
