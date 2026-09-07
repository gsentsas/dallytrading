import Link from 'next/link';

import type { DepartChargement } from '@/lib/ops/loading';
import { LIBELLE_MODE, enJour, enRoute } from '@/features/reception/format';

import { departComplet, resteALire, resumeLisible } from './chargement-vocabulaire';

export function ListeChargements(
  { consolidations }: { consolidations: readonly DepartChargement[] },
) {
  return (
    <section className="ops-depart-list" aria-label="Départs à charger">
      {consolidations.map((depart) => {
        const complet = departComplet(depart.summary);
        const reste = resteALire(depart.summary);
        const prevu = enJour(depart.scheduled_departure || null);
        return (
          <section className="carte ops-depart-card" key={depart.reference} data-testid="depart-chargement">
            <div className="ops-depart-card-top">
              <span className="ops-depart-mode">
                {LIBELLE_MODE[depart.transport_mode] ?? depart.transport_mode}
              </span>
              <span className={`ops-state-pill${complet ? ' is-complete' : ''}`}>
                <span aria-hidden="true" />
                {depart.state_label}
              </span>
            </div>

            <p className="reference">{depart.reference}</p>
            <p className="route ops-depart-route">{enRoute(depart.origin, depart.destination)}</p>

            <div className="ops-depart-metrics">
              <div>
                <small>Colis</small>
                <strong>{depart.summary.packages_loaded}/{depart.summary.packages_expected}</strong>
              </div>
              <div>
                <small>Poids attendu</small>
                <strong>{new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(depart.summary.weight_expected_kg)} kg</strong>
              </div>
              <div>
                <small>Volume</small>
                <strong>{new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(depart.summary.volume_expected_cbm)} m³</strong>
              </div>
            </div>

            <p className="ops-depart-summary" data-testid="depart-compte">
              <strong>{resumeLisible(depart.summary)}</strong>{complet ? ' — complet' : ''}
            </p>
            {reste ? <p className="attenue" data-testid="depart-reste">{reste}</p> : null}
            {prevu ? <p className="attenue">Départ prévu : {prevu}</p> : null}

            <Link
              className="bouton-lien ops-depart-action"
              href={`/chargement/${encodeURIComponent(depart.reference)}`}
            >
              {depart.can_load ? 'Préparer' : 'Consulter'} <span aria-hidden="true">→</span>
            </Link>
          </section>
        );
      })}
    </section>
  );
}
