import Link from 'next/link';

import type { Consolidation } from '@/lib/ops/consolidations';
import { LIBELLE_MODE, enJour, enRoute } from '@/features/reception/format';

/**
 * Les départs, en cartes.
 *
 * Aucun tableau : sur un téléphone tenu d'une main, une ligne de tableau est
 * illisible et sa case à cocher intouchable. Chaque départ occupe donc une
 * carte entière, avec un bouton pleine largeur.
 *
 * L'ordre vient du serveur et n'est pas retouché ici — les collectes qui
 * ferment bientôt d'abord. Retrier côté navigateur ferait diverger ce que
 * l'opérateur voit de ce que le serveur a décidé.
 */
export function ListeDeparts({ consolidations }: { consolidations: readonly Consolidation[] }) {
  return (
    <>
      {consolidations.map((consolidation) => {
        const depart = enJour(consolidation.scheduled_departure);
        const cloture = enJour(consolidation.collection_close_on);
        return (
          <section className="carte" key={consolidation.reference}>
            <span className="mode">
              {LIBELLE_MODE[consolidation.transport_mode] ?? consolidation.transport_mode}
            </span>
            <p className="reference">{consolidation.reference}</p>
            <p className="route">{enRoute(consolidation.origin, consolidation.destination)}</p>

            <p className="attenue" style={{ margin: 0 }}>Collecte ouverte</p>
            {cloture ? (
              <p className="attenue" style={{ margin: 0 }}>Collecte jusqu’au : {cloture}</p>
            ) : null}
            {/* Pas de date prévue : on n'en invente pas, on n'affiche rien. */}
            {depart ? (
              <p className="attenue" style={{ margin: 0 }}>Départ prévu : {depart}</p>
            ) : null}

            <Link
              className="bouton-lien"
              href={`/reception/client?consolidation=${encodeURIComponent(consolidation.reference)}`}
            >
              Sélectionner
            </Link>
          </section>
        );
      })}
    </>
  );
}
