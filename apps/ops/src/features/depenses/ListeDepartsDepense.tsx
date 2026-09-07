import Link from 'next/link';

import type { DepartDepense } from '@/lib/ops/expenses';
import { LIBELLE_MODE, enRoute } from '@/features/reception/format';
import { LIBELLE_ETAT_DEPART } from '@/features/depenses/format';

export function ListeDepartsDepense({ departs }: { departs: readonly DepartDepense[] }) {
  return (
    <section className="ops-depart-list ops-expense-depart-list" aria-label="Départs pour dépenses">
      {departs.map((depart) => (
        <section className="carte ops-depart-card ops-expense-depart-card" key={depart.reference}>
          <div className="ops-depart-card-top">
            <span className="ops-depart-mode">
              {LIBELLE_MODE[depart.transport_mode] ?? depart.transport_mode}
            </span>
            <span className="ops-state-pill"><span aria-hidden="true" />{LIBELLE_ETAT_DEPART[depart.state] ?? depart.state}</span>
          </div>
          <p className="reference">{depart.reference}</p>
          <p className="route ops-depart-route">{enRoute(depart.origin, depart.destination)}</p>

          <Link
            className="bouton-lien ops-expense-action"
            href={`/depenses/${encodeURIComponent(depart.reference)}`}
          >
            Sélectionner <span aria-hidden="true">→</span>
          </Link>
        </section>
      ))}
    </section>
  );
}
