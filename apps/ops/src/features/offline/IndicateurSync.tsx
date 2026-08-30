'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import {
  brancherSynchronisation, etatCourant, installerServiceWorker,
} from '@/lib/offline/client';
import type { EtatFile } from '@/lib/offline/queue';

/**
 * Ce que l'accueil dit de la file, en une ligne.
 *
 * ## Pourquoi il n'affiche jamais « en ligne »
 *
 * `navigator.onLine` répond « oui » dès qu'une carte réseau est associée à
 * quelque chose — un portail Wi-Fi captif d'aéroport compris. Il ne dit rien
 * de la joignabilité d'Odoo. La seule information honnête est le nombre
 * d'opérations que le CRM n'a pas encore confirmées.
 *
 * C'est aussi cet écran qui installe le Service Worker et branche les
 * occasions de synchroniser : il est présent sur l'accueil, donc à chaque
 * ouverture de l'application.
 */
export function IndicateurSync({ login }: { login: string }) {
  const [etat, setEtat] = useState<EtatFile | null>(null);

  useEffect(() => {
    installerServiceWorker();
    let vivant = true;
    const rafraichir = () => {
      void etatCourant(login)
        .then((valeur) => { if (vivant) setEtat(valeur); })
        .catch(() => undefined);
    };
    const debrancher = brancherSynchronisation(login, rafraichir);
    rafraichir();
    return () => { vivant = false; debrancher(); };
  }, [login]);

  if (!etat) return null;

  const enAttente = etat.en_attente;
  const enErreur = etat.en_erreur;

  if (enAttente === 0 && enErreur === 0 && etat.etrangeres === 0) {
    return (
      <p className="attenue" data-testid="indicateur-sync">
        ✓ Tout est synchronisé
      </p>
    );
  }

  return (
    <Link className="carte carte-lien" href="/synchronisation" data-testid="indicateur-sync">
      {enErreur > 0 ? (
        <strong className="alerte">
          {enErreur === 1 ? '1 erreur de synchronisation'
            : `${enErreur} erreurs de synchronisation`}
        </strong>
      ) : (
        <strong>
          {enAttente === 1 ? '1 opération en attente'
            : `${enAttente} opérations en attente`}
        </strong>
      )}
      {etat.etrangeres > 0 ? (
        <p className="attenue" style={{ margin: '0.25rem 0 0' }}>
          {/* Sans nommer personne : la file d'un collègue ne le concerne pas. */}
          {etat.etrangeres === 1
            ? '1 opération d’un autre opérateur attend sa reconnexion.'
            : `${etat.etrangeres} opérations d’un autre opérateur attendent sa reconnexion.`}
        </p>
      ) : null}
    </Link>
  );
}
