import Link from 'next/link';

import { EcranSync } from '@/features/offline/EcranSync';

/**
 * L'état de ce que l'appareil doit encore au CRM.
 *
 * ## Pourquoi cette page est statique
 *
 * C'est la seule de l'application à devoir s'ouvrir **sans réseau** — c'est
 * même sa raison d'être. Lui faire demander l'identité au serveur la rendrait
 * inaccessible au moment exact où l'opérateur en a besoin.
 *
 * Elle n'affiche donc rien qui vienne du serveur : la file vit dans le
 * navigateur, et l'opérateur à qui elle appartient est identifié par une
 * empreinte écrite localement lors de sa dernière session. Aucun nom, aucune
 * donnée client, rien qui doive être protégé d'un opérateur suivant.
 */
export default function PageSynchronisation() {
  return (
    <main>
      <Link className="retour" href="/">← Accueil</Link>
      <h1>SYNCHRONISATION</h1>
      <p className="attenue">
        Les opérations enregistrées sur cet appareil et non encore confirmées
        par le CRM.
      </p>
      <EcranSync />
    </main>
  );
}
