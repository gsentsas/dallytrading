'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import type { ActionChargement, ColisChargement, DetailChargement } from '@/lib/ops/loading';
import { LIBELLE_MODE, enJour, enRoute } from '@/features/reception/format';

import {
  creerSuiviDeGestes,
  determinerAffichage,
  gesteProposé,
  interpreterEnvoi,
  libelleGeste,
  libelleStatut,
  lireChargement,
  resteALire,
  resumeLisible,
} from './chargement-vocabulaire';

function nombre(value: number, maximumFractionDigits = 1): string {
  return new Intl.NumberFormat('fr-FR', { maximumFractionDigits }).format(value);
}

export function ChargementDepart({ reference }: { reference: string }) {
  const [detail, setDetail] = useState<DetailChargement | null>(null);
  const [chargement, setChargement] = useState(true);
  const [lectureEchouee, setLectureEchouee] = useState(false);
  const [enCours, setEnCours] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const gestes = useRef(creerSuiviDeGestes(() => crypto.randomUUID()));

  const recharger = useCallback(async () => {
    const resultat = await lireChargement(async () => {
      const reponse = await fetch(
        `/api/consolidations/${encodeURIComponent(reference)}/loading`,
        { cache: 'no-store' });
      return { ok: reponse.ok, corps: await reponse.json().catch(() => null) };
    });
    if (resultat.issue === 'ok') {
      setDetail(resultat.donnees);
      setLectureEchouee(false);
    } else {
      setLectureEchouee(true);
    }
    setChargement(false);
  }, [reference]);

  useEffect(() => {
    const initial = setTimeout(() => { void recharger(); }, 0);
    return () => clearTimeout(initial);
  }, [recharger]);

  async function appliquer(colis: ColisChargement, action: ActionChargement) {
    setMessage(null);
    setEnCours(colis.reference);
    try {
      const reponse = await fetch(
        `/api/consolidations/${encodeURIComponent(reference)}/loading`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            request_uuid: gestes.current.identifiant(colis.reference, action),
            action,
            package_reference: colis.reference,
          }),
        });
      const corps = await reponse.json().catch(() => null);
      const issue = interpreterEnvoi(reponse.ok, corps);
      if (issue.issue === 'ok') {
        gestes.current.terminer(colis.reference, action);
        setDetail(issue.donnees);
        setLectureEchouee(false);
        return;
      }
      setMessage(issue.message);
    } catch {
      setMessage('Connexion interrompue. Vous pouvez réessayer le même geste.');
    } finally {
      setEnCours(null);
    }
  }

  const affichage = determinerAffichage({ chargement, lectureEchouee, detail });

  return (
    <section className="ops-loading-workflow" aria-labelledby="chargement-titre" data-testid="chargement-depart">
      <h2 className="sr-only" id="chargement-titre">Pile du départ</h2>

      <div className="ops-stepper" aria-label="Étapes du chargement">
        <div className="is-current"><span>1</span><strong>Sélection</strong></div>
        <i aria-hidden="true" />
        <div><span>2</span><strong>Vérification</strong></div>
        <i aria-hidden="true" />
        <div><span>3</span><strong>Confirmation</strong></div>
      </div>

      {message ? <p className="erreur" role="alert">{message}</p> : null}
      {chargement ? <section className="ops-loading-skeleton"><p className="attenue">Chargement…</p></section> : null}

      {affichage.indisponible ? (
        <p className="erreur" role="alert" data-testid="chargement-indisponible">
          Départ momentanément indisponible.
        </p>
      ) : null}

      {detail && !affichage.indisponible ? (
        <>
          <section className="ops-loading-depart-card">
            <div className="ops-loading-card-header">
              <div>
                <small>Référence départ</small>
                <strong>{detail.reference}</strong>
              </div>
              <span className="ops-state-pill"><span aria-hidden="true" />{detail.state_label}</span>
            </div>
            <div className="ops-loading-route-row">
              <div><small>Trajet</small><strong>{enRoute(detail.origin, detail.destination)}</strong></div>
              <div><small>Type de départ</small><strong>{LIBELLE_MODE[detail.transport_mode] ?? detail.transport_mode}</strong></div>
              {detail.scheduled_departure ? (
                <div><small>Date de départ</small><strong>{enJour(detail.scheduled_departure)}</strong></div>
              ) : null}
            </div>
          </section>

          <section className="ops-loading-summary" aria-label="Résumé du départ">
            <div className="ops-loading-metric">
              <span className="tone-green" aria-hidden="true">◇</span>
              <strong>{detail.summary.packages_expected}</strong>
              <p>colis</p>
              <small>À vérifier sur le départ</small>
            </div>
            <div className="ops-loading-metric">
              <span className="tone-purple" aria-hidden="true">KG</span>
              <strong>{nombre(detail.summary.weight_expected_kg)}</strong>
              <p>kg au total</p>
              <small>Poids attendu des colis</small>
            </div>
            <div className="ops-loading-metric">
              <span className="tone-blue" aria-hidden="true">□</span>
              <strong>{nombre(detail.summary.volume_expected_cbm, 2)}</strong>
              <p>m³ au total</p>
              <small>Volume attendu</small>
            </div>
          </section>

          <section className="ops-loading-ready">
            <span aria-hidden="true">i</span>
            <div>
              <strong>{resumeLisible(detail.summary)}</strong>
              <p data-testid="chargement-compte">Vérifiez que chaque colis physique correspond à la pile attendue.</p>
              {resteALire(detail.summary) ? (
                <small data-testid="chargement-reste">{resteALire(detail.summary)}</small>
              ) : null}
            </div>
          </section>
        </>
      ) : null}

      {affichage.ferme ? (
        <p className="attenue" data-testid="chargement-ferme">
          La collecte de ce départ est close : la pile ne peut plus être modifiée.
        </p>
      ) : null}

      {affichage.aucunDossier ? (
        <p className="attenue" data-testid="aucun-dossier">
          Aucun dossier n’est attendu sur ce départ.
        </p>
      ) : null}

      {affichage.liste && detail ? (
        <section className="ops-loading-shipments" aria-label="Dossiers du départ">
          <div className="ops-section-heading"><h2>COLIS À CHARGER</h2><p>{detail.summary.packages_remaining} restant(s)</p></div>
          {detail.shipments.map((dossier) => (
            <section className="carte ops-loading-shipment" key={dossier.reference} data-testid="dossier-chargement">
              <div className="ops-loading-shipment-title">
                <div>
                  <p className="reference" data-testid="dossier-reference">
                    {dossier.reference}{dossier.local_reference ? ` · ${dossier.local_reference}` : ''}
                  </p>
                  <strong>{dossier.customer.name}</strong>
                </div>
                {dossier.complete ? <span className="ops-complete-pill" data-testid="dossier-complet">Dossier complet</span> : null}
              </div>

              {dossier.packages.map((colis) => {
                const geste = gesteProposé(colis);
                return (
                  <div className="ops-loading-package" key={colis.reference} data-testid="colis-chargement">
                    <div>
                      <p>
                        <strong data-testid="colis-statut">{libelleStatut(colis.status)}</strong>
                        <span data-testid="colis-description"> · {colis.description || colis.goods_category || 'Colis'}</span>
                      </p>
                      <small data-testid="colis-compte">{colis.loaded_quantity} / {colis.expected_quantity}</small>
                      {colis.blocker ? <small data-testid="colis-blocage">{colis.blocker}</small> : null}
                    </div>
                    {geste ? (
                      <button
                        type="button"
                        className={geste === 'unload' ? 'secondaire ops-loading-package-action' : 'ops-loading-package-action'}
                        disabled={enCours !== null}
                        onClick={() => { void appliquer(colis, geste); }}
                        data-testid={geste === 'load' ? 'charger-colis' : 'retirer-colis'}
                      >
                        {enCours === colis.reference ? 'Enregistrement…' : libelleGeste(geste)}
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </section>
          ))}
        </section>
      ) : null}
    </section>
  );
}
