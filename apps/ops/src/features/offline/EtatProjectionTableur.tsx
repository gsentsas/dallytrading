'use client';

import { useEffect, useState } from 'react';

import type { EtatProjection } from '@/lib/ops/supervision';

/**
 * L'autre moitié de la synchronisation : Odoo → tableur.
 *
 * ## Pourquoi ce composant est séparé, et client
 *
 * La page `/synchronisation` doit s'ouvrir **sans réseau** — c'est sa raison
 * d'être. Sa première moitié, la file de l'appareil, vit dans IndexedDB et se
 * lit hors ligne. Faire dépendre la page entière d'un appel serveur la rendrait
 * inaccessible au moment exact où l'opérateur en a besoin.
 *
 * Ce composant demande donc l'état au serveur **après** l'affichage, et
 * disparaît proprement quand il ne l'obtient pas. La page reste ouvrable, la
 * file locale reste lisible.
 *
 * ## Pourquoi les deux ne sont jamais additionnées
 *
 * « 3 en attente » sur l'appareil et « 3 en attente » vers le tableur ne sont
 * pas six choses en attente. Ce sont deux systèmes, deux pannes, deux
 * remèdes : l'un se règle en retrouvant du réseau, l'autre en réparant le
 * connecteur. Les mêler ferait chercher au mauvais endroit.
 */

const LIBELLE: Record<keyof EtatProjection['counts'], string> = {
  pending: 'En attente',
  retry: 'Nouvelle tentative prévue',
  failed: 'En échec',
  synced: 'Arrivés',
};

/** L'ordre de lecture : la mauvaise nouvelle d'abord. */
const ORDRE: (keyof EtatProjection['counts'])[] = [
  'failed', 'retry', 'pending', 'synced',
];

type Etat =
  | { nom: 'chargement' }
  | { nom: 'pret'; donnees: EtatProjection }
  | { nom: 'absent' };

export function EtatProjectionTableur() {
  const [etat, setEtat] = useState<Etat>({ nom: 'chargement' });

  useEffect(() => {
    let vivant = true;
    void (async () => {
      try {
        const reponse = await fetch('/api/sheet-sync', { cache: 'no-store' });
        const charge = (await reponse.json().catch(() => null)) as
          | { success?: boolean; data?: EtatProjection }
          | null;
        if (!vivant) return;
        // Un 403 — logisticien — comme une panne réseau : la section
        // disparaît. Afficher « accès refusé » sur un écran qu'on ouvre pour
        // savoir si le réseau marche n'apprendrait rien à personne.
        if (!reponse.ok || !charge?.success || !charge.data) {
          setEtat({ nom: 'absent' });
          return;
        }
        setEtat({ nom: 'pret', donnees: charge.data });
      } catch {
        if (vivant) setEtat({ nom: 'absent' });
      }
    })();
    return () => { vivant = false; };
  }, []);

  if (etat.nom === 'absent') return null;

  return (
    <section data-testid="projection-tableur" style={{ marginTop: '1.5rem' }}>
      <h2 style={{ fontSize: '1.1rem', margin: '0 0 0.25rem' }}>CRM → TABLEUR</h2>
      <p className="attenue" style={{ margin: '0 0 0.6rem' }}>
        Les dossiers que le CRM doit encore projeter dans le classeur. Cette
        file est distincte de celle de l’appareil.
      </p>

      {etat.nom === 'chargement' ? (
        <p className="attenue" data-testid="projection-chargement">Lecture…</p>
      ) : (
        <>
          <section className="carte">
            {ORDRE.map((cle) => (
              <p key={cle} style={{ margin: '0.15rem 0' }}>
                {LIBELLE[cle]} : <strong>{etat.donnees.counts[cle]}</strong>
              </p>
            ))}
          </section>
          {/* Le message du serveur, jamais une erreur de transport. */}
          <p
            className={etat.donnees.counts.failed > 0 ? 'alerte' : 'attenue'}
            data-testid="projection-message"
          >
            {etat.donnees.operator_message}
          </p>
        </>
      )}
    </section>
  );
}
