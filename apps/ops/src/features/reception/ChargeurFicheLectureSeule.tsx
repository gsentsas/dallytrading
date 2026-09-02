'use client';

import { useEffect, useState } from 'react';

import { FicheLectureSeule } from './FicheLectureSeule';
import {
  chargementDe, chargerFiche, etatApplicable, messageDeLecture,
  type EtatLecture,
} from './lecture-seule-vocabulaire';

/**
 * Ce qui va chercher la fiche, et ce qu'il dit quand il n'y arrive pas.
 *
 * ## Pourquoi le navigateur et non le serveur de rendu
 *
 * La page rendait la fiche depuis le Server Component, en appelant Odoo
 * directement. Le parcours réel ne traversait donc jamais
 * `/api/intakes/<ref>/legacy-detail` : son plafond de consultation ne
 * s'appliquait à personne, et le BFF n'était éprouvé que par ses propres
 * tests. Deux chemins de lecture existaient, dont un seul était gardé.
 *
 * Il n'en reste qu'un. Le navigateur ne joint jamais Odoo : la seule
 * frontière est ce BFF.
 *
 * ## Pourquoi l'état porte sa référence
 *
 * Parce que la prop change sans démonter le composant. Un état qui ne dirait
 * pas de quel dossier il parle laisserait la fiche du précédent à l'écran
 * pendant que le suivant charge — et, si le suivant échoue, l'y laisserait
 * tout court : le rendu voyait une fiche et s'arrêtait là. Montrer les
 * données d'un client sous l'adresse d'un autre est exactement ce que la
 * navigation par référence globale interdit par ailleurs.
 *
 * ## Pourquoi une annulation en plus
 *
 * Une réponse lente pour A peut revenir après celle de B. La garde
 * d'obsolescence est consultée après l'attente, et la requête précédente est
 * abandonnée au nettoyage : un résultat périmé ne pose rien.
 *
 * ## Pourquoi distinguer les issues
 *
 * Un dossier introuvable, un débit atteint et une panne appellent trois
 * gestes différents. Les confondre derrière « une erreur est survenue »
 * laisserait l'opérateur réessayer là où il devrait appeler un responsable,
 * ou attendre là où il n'y a rien à attendre.
 */
export function ChargeurFicheLectureSeule({ reference }: { reference: string }) {
  const [etat, setEtat] = useState<EtatLecture>(() => chargementDe(reference));
  const courant = etatApplicable(etat, reference);

  useEffect(() => {
    const controleur = new AbortController();
    // Différé d'un tour de boucle, comme ailleurs dans l'application : poser
    // l'état depuis le corps d'un effet enchaîne des rendus que React
    // déconseille, et la règle `react-hooks/set-state-in-effect` le refuse.
    const chargementInitial = setTimeout(() => {
      void chargerFiche(
        reference,
        async () => {
          const reponse = await fetch(
            `/api/intakes/${encodeURIComponent(reference)}/legacy-detail`,
            { cache: 'no-store', signal: controleur.signal });
          return {
            ok: reponse.ok,
            statut: reponse.status,
            corps: await reponse.json().catch(() => null),
          };
        },
        setEtat,
        () => controleur.signal.aborted,
      );
    }, 0);
    return () => {
      controleur.abort();
      clearTimeout(chargementInitial);
    };
  }, [reference]);

  if (courant.phase === 'fiche') return <FicheLectureSeule fiche={courant.fiche} />;

  if (courant.phase === 'issue') {
    return (
      <p className="erreur" role="alert" data-testid={`lecture-${courant.issue}`}>
        {messageDeLecture(courant.issue)}
      </p>
    );
  }

  return <p className="attenue" data-testid="lecture-chargement">Chargement…</p>;
}
