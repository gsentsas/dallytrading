'use client';

/**
 * Le point d'entrée de la file pour les écrans.
 *
 * Les composants n'ouvrent pas IndexedDB et n'appellent pas le moteur
 * directement : ils passent par ici. Un seul endroit sait donc calculer
 * l'empreinte du propriétaire et décider quand une synchronisation doit
 * partir — et c'est le seul endroit à corriger le jour où cette décision
 * change.
 */

import { CLE_PROPRIETAIRE_COURANT, ecrireMeta, lireMeta } from '@/lib/offline/db';
import { empreinteProprietaire, etatDeLaFile, mettreEnFile } from '@/lib/offline/queue';
import { synchroniser } from '@/lib/offline/sync';
import type { EntreeFile } from '@/lib/offline/queue';
import type { EtatFile } from '@/lib/offline/queue';

let empreinteCache: { login: string; cle: string } | null = null;

/** L'empreinte du propriétaire courant, calculée une fois par session. */
export async function cleProprietaire(login: string): Promise<string> {
  if (empreinteCache?.login === login) return empreinteCache.cle;
  const cle = await empreinteProprietaire(login);
  empreinteCache = { login, cle };
  // Écrite pour que l'écran de synchronisation existe encore sans réseau.
  await ecrireMeta(CLE_PROPRIETAIRE_COURANT, cle).catch(() => undefined);
  return cle;
}

/**
 * L'empreinte du dernier opérateur connu de cet appareil.
 *
 * Sert quand le serveur est injoignable : l'écran de synchronisation doit
 * pouvoir montrer ce qui attend, et c'est justement hors connexion qu'on a le
 * plus besoin de le voir.
 */
export async function cleProprietaireLocale(): Promise<string | null> {
  return lireMeta<string>(CLE_PROPRIETAIRE_COURANT).catch(() => null);
}

export function oublierProprietaire(): void {
  empreinteCache = null;
}

/** Met une opération en file et tente aussitôt de l'envoyer. */
export async function enfilerPuisSynchroniser(
  login: string,
  entree: Omit<EntreeFile, 'owner_key'>,
): Promise<void> {
  const owner_key = await cleProprietaire(login);
  await mettreEnFile({ ...entree, owner_key });
  // Sans attendre : si le réseau est là, l'écran verra le résultat au prochain
  // rafraîchissement ; s'il ne l'est pas, l'opération reste en file.
  void synchroniser(owner_key).catch(() => undefined);
}

export async function etatCourant(login: string): Promise<EtatFile> {
  return etatDeLaFile(await cleProprietaire(login));
}

/**
 * Lance une synchronisation demandée explicitement par l'opérateur.
 *
 * Le délai de reprise est ignoré : il existe pour espacer les tentatives
 * automatiques, pas pour faire taire un bouton sur lequel quelqu'un vient
 * d'appuyer.
 */
export async function synchroniserMaintenant(ownerKey: string) {
  return synchroniser(ownerKey, { ignorerDelai: true });
}

/** La reprise automatique, elle, respecte le délai. */
export async function synchroniserEnArrierePlan(ownerKey: string) {
  return synchroniser(ownerKey);
}

/**
 * Branche les quatre occasions concrètes de synchroniser.
 *
 * Ni Background Sync ni minuteur agressif : le lancement de l'application, le
 * retour au premier plan, le retour du réseau et un geste explicite couvrent
 * tout ce dont un opérateur d'entrepôt a besoin, et ne dépendent d'aucun
 * navigateur en particulier.
 */
export function brancherSynchronisation(
  login: string,
  apres: () => void,
): () => void {
  let arrete = false;
  const lancer = () => {
    if (arrete) return;
    void cleProprietaire(login)
      .then((cle) => synchroniserEnArrierePlan(cle))
      .then(apres)
      .catch(() => undefined);
  };

  const surVisibilite = () => {
    if (document.visibilityState === 'visible') lancer();
  };

  lancer();
  window.addEventListener('online', lancer);
  document.addEventListener('visibilitychange', surVisibilite);
  return () => {
    arrete = true;
    window.removeEventListener('online', lancer);
    document.removeEventListener('visibilitychange', surVisibilite);
  };
}

/**
 * Installe le Service Worker.
 *
 * Silencieux en cas d'échec : une PWA non installable reste une application
 * parfaitement utilisable, et rien ne justifie d'inquiéter un opérateur avec
 * un message qu'il ne peut pas traiter.
 */
export function installerServiceWorker(): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('/sw.js').catch(() => undefined);
}
