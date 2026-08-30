'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

/**
 * Le bouton de nouvelle tentative.
 *
 * Il relance le rendu serveur plutôt que de recharger la page : la session
 * reste en place, et l'opérateur ne perd pas son fil. Une panne d'Odoo est
 * presque toujours passagère ; ce bouton évite de la transformer en
 * reconnexion.
 */
export function Reessayer() {
  const router = useRouter();
  const [enCours, setEnCours] = useState(false);

  return (
    <button
      type="button"
      disabled={enCours}
      onClick={() => {
        setEnCours(true);
        router.refresh();
        // Le rafraîchissement est asynchrone : on rouvre le bouton pour que
        // l'opérateur puisse réessayer si rien ne change.
        setTimeout(() => setEnCours(false), 1500);
      }}
    >
      {enCours ? 'Chargement…' : 'Réessayer'}
    </button>
  );
}
