import Link from 'next/link';

import type { DepartDepense } from '@/lib/ops/expenses';
import { LIBELLE_MODE, enRoute } from '@/features/reception/format';
import { LIBELLE_ETAT_DEPART } from '@/features/depenses/format';

/**
 * Les départs sur lesquels une dépense peut être imputée.
 *
 * La liste est plus longue que celle des réceptions, et c'est voulu : on paie
 * une manutention pendant la collecte, un dédouanement après le départ et un
 * stockage à l'arrivée. L'état est donc affiché sur chaque carte — sans lui,
 * deux départs de même route seraient impossibles à distinguer.
 */
export function ListeDepartsDepense({ departs }: { departs: readonly DepartDepense[] }) {
  return (
    <>
      {departs.map((depart) => (
        <section className="carte" key={depart.reference}>
          <span className="mode">
            {LIBELLE_MODE[depart.transport_mode] ?? depart.transport_mode}
          </span>
          <p className="reference">{depart.reference}</p>
          <p className="route">{enRoute(depart.origin, depart.destination)}</p>
          <p className="attenue" style={{ margin: 0 }}>
            {LIBELLE_ETAT_DEPART[depart.state] ?? depart.state}
          </p>

          <Link
            className="bouton-lien"
            href={`/depenses/${encodeURIComponent(depart.reference)}`}
          >
            Sélectionner
          </Link>
        </section>
      ))}
    </>
  );
}
