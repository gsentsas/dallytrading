'use client';

import { useCallback, useEffect, useState } from 'react';

import type { FicheLegacy } from '@/lib/ops/legacy-intake';

import { FicheLectureSeule } from './FicheLectureSeule';
import {
  lireFicheLegacy, messageDeLecture, type IssueLecture,
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
 * ## Pourquoi distinguer les issues
 *
 * Un dossier introuvable, un débit atteint et une panne appellent trois
 * gestes différents. Les confondre derrière « une erreur est survenue »
 * laisserait l'opérateur réessayer là où il devrait appeler un responsable,
 * ou attendre là où il n'y a rien à attendre.
 */
export function ChargeurFicheLectureSeule({ reference }: { reference: string }) {
  const [fiche, setFiche] = useState<FicheLegacy | null>(null);
  const [issue, setIssue] = useState<IssueLecture | null>(null);

  const charger = useCallback(async () => {
    const resultat = await lireFicheLegacy(async () => {
      const reponse = await fetch(
        `/api/intakes/${encodeURIComponent(reference)}/legacy-detail`,
        { cache: 'no-store' });
      return {
        ok: reponse.ok,
        statut: reponse.status,
        corps: await reponse.json().catch(() => null),
      };
    });
    if (resultat.issue === 'ok') {
      setFiche(resultat.fiche as FicheLegacy);
      setIssue(null);
      return;
    }
    // Une coupure réseau n'est pas un dossier absent, et un débit atteint
    // n'est pas une panne : chaque issue garde son mot.
    setIssue(resultat.issue);
  }, [reference]);

  useEffect(() => {
    // Différé d'un tour de boucle, comme ailleurs dans l'application : poser
    // l'état depuis le corps d'un effet enchaîne des rendus que React
    // déconseille, et la règle `react-hooks/set-state-in-effect` le refuse.
    const chargementInitial = setTimeout(() => { void charger(); }, 0);
    return () => clearTimeout(chargementInitial);
  }, [charger]);

  if (fiche) return <FicheLectureSeule fiche={fiche} />;

  if (issue) {
    return (
      <p className="erreur" role="alert" data-testid={`lecture-${issue}`}>
        {messageDeLecture(issue)}
      </p>
    );
  }

  return <p className="attenue" data-testid="lecture-chargement">Chargement…</p>;
}
