import Link from 'next/link';

import type { DepartChargement } from '@/lib/ops/loading';
import { LIBELLE_MODE, enJour, enRoute } from '@/features/reception/format';
import { OpsCardIcon } from '@/features/shell/OpsCardIcon';

import { departComplet, resteALire, resumeLisible } from './chargement-vocabulaire';

/**
 * Les départs qu'on peut charger, présentés comme la maquette les présente.
 *
 * Une carte par départ : sa référence et son état en tête, puis ce qui décrit
 * le voyage — trajet, type, date, clôture de collecte — et enfin ce qu'il
 * pèse : colis, kilos, mètres cubes.
 *
 * ## Ce qui n'est pas affiché
 *
 * La maquette montre une ligne « Opérateur ». Le serveur ne renvoie pas cette
 * information pour un départ, et l'inventer donnerait un nom qui n'engage
 * personne. La quatrième case dit donc la clôture de collecte, que le serveur
 * connaît et qui compte autant sur le terrain : après elle, plus rien n'entre.
 *
 * Les chiffres viennent tous de `summary`. Aucun n'est calculé ici.
 */

const nombre = (valeur: number, decimales: number) =>
  new Intl.NumberFormat('fr-FR', { maximumFractionDigits: decimales }).format(valeur);

export function ListeChargements(
  { consolidations }: { consolidations: readonly DepartChargement[] },
) {
  return (
    <section className="ops-depart-list" aria-label="Départs à charger">
      {consolidations.map((depart) => {
        const complet = departComplet(depart.summary);
        const reste = resteALire(depart.summary);
        const prevu = enJour(depart.scheduled_departure || null);
        const cloture = enJour(depart.collection_close_on || null);
        return (
          <section className="carte ops-depart-card" key={depart.reference} data-testid="depart-chargement">
            <div className="ops-depart-identite">
              <span className="ops-card-icon tone-blue" aria-hidden="true">
                <OpsCardIcon name="chargement" />
              </span>
              <div className="ops-depart-identite-copy">
                <small>Référence départ</small>
                <p className="reference">{depart.reference}</p>
              </div>
              <span className={`ops-state-pill${complet ? ' is-complete' : ''}`}>
                <span aria-hidden="true" />
                {depart.state_label}
              </span>
            </div>

            <div className="ops-depart-faits">
              <div>
                <small>Trajet</small>
                <p className="route ops-depart-route">{enRoute(depart.origin, depart.destination)}</p>
              </div>
              <div>
                <small>Type de départ</small>
                <p>{LIBELLE_MODE[depart.transport_mode] ?? depart.transport_mode}</p>
              </div>
              {prevu ? (
                <div>
                  <small>Date de départ</small>
                  <p>{prevu}</p>
                </div>
              ) : null}
              {cloture ? (
                <div>
                  <small>Clôture collecte</small>
                  <p>{cloture}</p>
                </div>
              ) : null}
            </div>

            <div className="ops-depart-metrics">
              <div>
                <span className="ops-card-icon tone-green" aria-hidden="true">
                  <OpsCardIcon name="reception" />
                </span>
                <strong>{depart.summary.packages_loaded}/{depart.summary.packages_expected}</strong>
                <small>colis</small>
                <p>Chargés sur ce départ</p>
              </div>
              <div>
                <span className="ops-card-icon tone-purple" aria-hidden="true">
                  <OpsCardIcon name="depenses" />
                </span>
                <strong>{nombre(depart.summary.weight_expected_kg, 1)}</strong>
                <small>kg attendus</small>
                <p>Poids brut des colis</p>
              </div>
              <div>
                <span className="ops-card-icon tone-blue" aria-hidden="true">
                  <OpsCardIcon name="reception" />
                </span>
                <strong>{nombre(depart.summary.volume_expected_cbm, 2)}</strong>
                <small>m³ attendus</small>
                <p>Volume occupé</p>
              </div>
            </div>

            <p className="ops-depart-summary" data-testid="depart-compte">
              <strong>{resumeLisible(depart.summary)}</strong>{complet ? ' — complet' : ''}
            </p>
            {reste ? <p className="attenue" data-testid="depart-reste">{reste}</p> : null}

            <p className="ops-depart-note">
              <span className="ops-depart-note-icon" aria-hidden="true">i</span>
              <span>
                <strong>Prêt pour le chargement</strong>
                Vérifiez que les colis physiques correspondent aux informations du départ.
              </span>
            </p>

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
