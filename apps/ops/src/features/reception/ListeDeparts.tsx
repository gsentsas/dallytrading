import Link from 'next/link';

import type { Consolidation } from '@/lib/ops/consolidations';
import { LIBELLE_MODE, enJour, enRoute } from '@/features/reception/format';

export function ListeDeparts({ consolidations }: { consolidations: readonly Consolidation[] }) {
  return (
    <section className="ops-depart-list ops-reception-depart-list" aria-label="Départs ouverts">
      {consolidations.map((consolidation) => {
        const depart = enJour(consolidation.scheduled_departure);
        const cloture = enJour(consolidation.collection_close_on);
        return (
          <section className="carte ops-depart-card ops-reception-depart-card" key={consolidation.reference}>
            <div className="ops-depart-card-top">
              <span className="ops-depart-mode">
                {LIBELLE_MODE[consolidation.transport_mode] ?? consolidation.transport_mode}
              </span>
              <span className="ops-state-pill is-open"><span aria-hidden="true" />Collecte ouverte</span>
            </div>
            <p className="reference">{consolidation.reference}</p>
            <p className="ops-depart-route">
              <span className="route">{enRoute(consolidation.origin, consolidation.destination)}</span>
            </p>

            <div className="ops-reception-dates">
              {cloture ? <p className="attenue">Collecte jusqu’au : <strong>{cloture}</strong></p> : null}
              {depart ? <p className="attenue">Départ prévu : {depart}</p> : null}
            </div>

            <Link
              className="bouton-lien ops-depart-action"
              href={`/reception/client?consolidation=${encodeURIComponent(consolidation.reference)}`}
            >
              Sélectionner <span aria-hidden="true">→</span>
            </Link>
          </section>
        );
      })}
    </section>
  );
}
