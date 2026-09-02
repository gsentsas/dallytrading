'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import type { ActionChargement, ColisChargement, DetailChargement } from '@/lib/ops/loading';

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

/**
 * La pile d'un départ, colis par colis.
 *
 * ## Ce que l'écran fait
 *
 * Il montre ce qui est **attendu** et ce qui est **là**, et propose un seul
 * geste par colis : le charger entier, ou le retirer. Aucune quantité au
 * clavier — dans un entrepôt, un chiffre tapé à la main ne se relit pas.
 *
 * ## Ce que l'écran ne propose pas
 *
 * Ni clore la collecte, ni mettre le départ « prêt », ni enregistrer le
 * départ. Ces gestes engagent le dossier maître et restent au back-office ;
 * les afficher grisés laisserait croire qu'ils viendront.
 *
 * ## Pourquoi la réponse du serveur remplace tout l'état
 *
 * Chaque geste renvoie le départ entier, recalculé. L'écran ne recompose donc
 * jamais un compte localement : après un chargement, ce qui s'affiche est ce
 * qu'Odoo vient de dire, pas ce que le navigateur a supposé.
 */
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
      // Ne pas confondre « je n'ai pas pu lire » avec « il n'y a rien ».
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
      // L'identifiant est conservé : un nouvel appui rejoue le même geste et
      // ne charge pas le colis une seconde fois.
      setMessage('Connexion interrompue. Vous pouvez réessayer le même geste.');
    } finally {
      setEnCours(null);
    }
  }

  const affichage = determinerAffichage({ chargement, lectureEchouee, detail });

  return (
    <section aria-labelledby="chargement-titre" data-testid="chargement-depart">
      <h2 id="chargement-titre">PILE DU DÉPART</h2>

      {message ? <p className="erreur" role="alert">{message}</p> : null}
      {chargement ? <p className="attenue">Chargement…</p> : null}

      {affichage.indisponible ? (
        <p className="erreur" role="alert" data-testid="chargement-indisponible">
          Départ momentanément indisponible.
        </p>
      ) : null}

      {detail && !affichage.indisponible ? (
        <>
          <p style={{ margin: '0 0 0.2rem' }} data-testid="chargement-compte">
            <strong>{resumeLisible(detail.summary)}</strong>
          </p>
          {resteALire(detail.summary) ? (
            <p className="attenue" style={{ margin: '0 0 1rem' }}
               data-testid="chargement-reste">
              {resteALire(detail.summary)}
            </p>
          ) : null}
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

      {affichage.liste && detail ? detail.shipments.map((dossier) => (
        <section className="carte" key={dossier.reference} data-testid="dossier-chargement">
          <p className="reference" data-testid="dossier-reference">
            {dossier.reference}
            {dossier.local_reference ? ` · ${dossier.local_reference}` : ''}
          </p>
          <p className="attenue" style={{ margin: 0 }}>{dossier.customer.name}</p>
          {dossier.complete ? (
            <p className="attenue" style={{ margin: '0.2rem 0 0' }}
               data-testid="dossier-complet">
              Dossier complet
            </p>
          ) : null}

          {dossier.packages.map((colis) => {
            const geste = gesteProposé(colis);
            return (
              <div key={colis.reference} style={{ marginTop: '0.8rem' }}
                   data-testid="colis-chargement">
                <p style={{ margin: 0 }}>
                  <strong data-testid="colis-statut">{libelleStatut(colis.status)}</strong>
                  {' — '}
                  <span data-testid="colis-description">
                    {colis.description || colis.goods_category || 'Colis'}
                  </span>
                </p>
                <p className="attenue" style={{ margin: 0 }} data-testid="colis-compte">
                  {colis.loaded_quantity} / {colis.expected_quantity}
                </p>
                {colis.blocker ? (
                  <p className="attenue" style={{ margin: 0 }} data-testid="colis-blocage">
                    {colis.blocker}
                  </p>
                ) : null}
                {geste ? (
                  <button
                    type="button"
                    className={geste === 'unload' ? 'secondaire' : undefined}
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
      )) : null}
    </section>
  );
}
