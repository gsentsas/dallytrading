import Link from 'next/link';

import { EcranSync } from '@/features/offline/EcranSync';
import { EtatProjectionTableur } from '@/features/offline/EtatProjectionTableur';

/**
 * L'état de ce que l'appareil doit encore au CRM.
 *
 * ## Pourquoi cette page est statique
 *
 * C'est la seule de l'application à devoir s'ouvrir **sans réseau** — c'est
 * même sa raison d'être. Lui faire demander l'identité au serveur la rendrait
 * inaccessible au moment exact où l'opérateur en a besoin.
 *
 * Sa première moitié n'affiche donc rien qui vienne du serveur : la file vit
 * dans le navigateur, et l'opérateur à qui elle appartient est identifié par
 * une empreinte écrite localement lors de sa dernière session. Aucun nom,
 * aucune donnée client, rien qui doive être protégé d'un opérateur suivant.
 *
 * ## Deux files, jamais mélangées
 *
 * La seconde moitié — ce que le CRM doit encore projeter dans le tableur —
 * vient bien du serveur, mais elle est demandée **après** l'affichage et
 * disparaît quand elle n'arrive pas. La page reste donc ouvrable hors ligne,
 * et la file locale reste lisible.
 *
 * Les deux ne sont jamais additionnées : « 3 en attente » sur l'appareil et
 * « 3 en attente » vers le tableur ne font pas six. L'un se règle en
 * retrouvant du réseau, l'autre en réparant le connecteur.
 */
export default function PageSynchronisation() {
  return (
    <main>
      <Link className="retour" href="/">← Accueil</Link>
      <h1>SYNCHRONISATION</h1>

      <h2 style={{ fontSize: '1.1rem', margin: '0 0 0.25rem' }}>APPAREIL → CRM</h2>
      <p className="attenue">
        Les opérations enregistrées sur cet appareil et non encore confirmées
        par le CRM.
      </p>
      <EcranSync />

      <EtatProjectionTableur />
    </main>
  );
}
