/**
 * Le Service Worker de Dally Ops.
 *
 * ## Ce qu'il fait, et rien de plus
 *
 * Il met en cache la coquille de l'application — le JavaScript, les styles,
 * les icônes — pour que l'écran s'ouvre sans réseau. C'est tout.
 *
 * ## Ce qu'il ne fait jamais
 *
 * Il ne met en cache **aucune réponse d'API**. Un client retrouvé, un montant
 * encaissé, un rendez-vous : ces réponses appartiennent à une session, et les
 * conserver dans un cache partagé par tout le navigateur signifierait qu'un
 * opérateur suivant, sur le même téléphone d'entrepôt, pourrait les relire.
 *
 * Il n'est pas non plus un second backend. Les opérations hors connexion
 * vivent dans IndexedDB et sont envoyées par l'application elle-même, qui sait
 * distinguer un succès d'un silence. Un Service Worker qui rejouerait des
 * requêtes sans lire les réponses ne saurait pas faire cette différence.
 *
 * ## Pourquoi pas Background Sync
 *
 * L'API n'existe pas partout et son déclenchement n'est garanti nulle part.
 * La synchronisation est donc pilotée par l'application : au lancement, au
 * retour au premier plan, au retour du réseau, et à la demande. Ce sont quatre
 * occasions concrètes, qui ne dépendent d'aucun navigateur en particulier.
 */

const VERSION = 'dally-ops-shell-v1';

/** La coquille minimale : de quoi ouvrir l'application sans réseau. */
const COQUILLE = ['/synchronisation', '/manifest.webmanifest'];

/**
 * Les navigations qui peuvent être servies depuis le cache.
 *
 * Une seule : l'écran de synchronisation. Il ne contient aucune donnée du CRM
 * — ni client, ni montant, ni rendez-vous — et c'est justement la page dont un
 * opérateur a besoin quand le réseau manque. Les autres écrans affichent des
 * données de session : les servir depuis un cache partagé signifierait qu'un
 * opérateur suivant, sur le même téléphone d'entrepôt, pourrait les relire.
 */
const NAVIGATIONS_EN_CACHE = ['/synchronisation'];

self.addEventListener('install', (evenement) => {
  evenement.waitUntil(
    caches.open(VERSION)
      // `addAll` échoue en bloc si une seule ressource manque ; on préfère une
      // coquille partielle à une installation qui n'aboutit jamais.
      .then((cache) => Promise.allSettled(COQUILLE.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (evenement) => {
  evenement.waitUntil(
    caches.keys()
      .then((noms) => Promise.all(
        noms.filter((nom) => nom !== VERSION).map((nom) => caches.delete(nom)),
      ))
      .then(() => self.clients.claim()),
  );
});

/** Ce qui a le droit d'être conservé. */
function cacheable(url) {
  if (url.origin !== self.location.origin) return false;
  // Jamais d'API : ces réponses appartiennent à une session.
  if (url.pathname.startsWith('/api/')) return false;
  return url.pathname.startsWith('/_next/static/')
    || url.pathname.startsWith('/icones/')
    || url.pathname === '/manifest.webmanifest'
    || NAVIGATIONS_EN_CACHE.includes(url.pathname);
}

self.addEventListener('fetch', (evenement) => {
  const requete = evenement.request;
  if (requete.method !== 'GET') return;

  const url = new URL(requete.url);

  // Navigation vers l'écran de synchronisation : le réseau d'abord — il peut
  // avoir une version plus récente — et le cache s'il ne répond pas.
  if (requete.mode === 'navigate'
      && url.origin === self.location.origin
      && NAVIGATIONS_EN_CACHE.includes(url.pathname)) {
    evenement.respondWith(
      fetch(requete)
        .then((reponse) => {
          if (reponse && reponse.status === 200 && reponse.type === 'basic') {
            const copie = reponse.clone();
            caches.open(VERSION).then((cache) => cache.put(url.pathname, copie));
          }
          return reponse;
        })
        .catch(() => caches.match(url.pathname).then(
          (depuisCache) => depuisCache ?? Response.error())),
    );
    return;
  }

  if (!cacheable(url)) return;

  evenement.respondWith(
    caches.match(requete).then((depuisCache) => {
      if (depuisCache) return depuisCache;
      return fetch(requete).then((reponse) => {
        // Une réponse partielle ou opaque ne se met pas en cache : elle
        // reviendrait ensuite sans qu'on puisse savoir ce qu'elle vaut.
        if (!reponse || reponse.status !== 200 || reponse.type !== 'basic') {
          return reponse;
        }
        const copie = reponse.clone();
        caches.open(VERSION).then((cache) => cache.put(requete, copie));
        return reponse;
      });
    }),
  );
});

/** L'application demande explicitement une mise à jour du worker. */
self.addEventListener('message', (evenement) => {
  if (evenement.data === 'skip-waiting') self.skipWaiting();
});
