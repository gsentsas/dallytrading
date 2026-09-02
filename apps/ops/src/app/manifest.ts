import type { MetadataRoute } from 'next';

/**
 * Le manifeste de l'application installée.
 *
 * `display: standalone` retire la barre d'adresse : sur un téléphone
 * d'entrepôt tenu d'une main, chaque pixel gagné est une ligne de formulaire
 * de plus, et l'absence de barre évite qu'un opérateur quitte l'application
 * par un geste de trop.
 *
 * `scope` et `start_url` restent à la racine : Dally Ops est une application
 * entière, pas un écran greffé sur le site public. Une PWA dont le périmètre
 * déborderait ouvrirait le site marketing dans la fenêtre de l'outil de
 * travail.
 *
 * Les icônes sont dérivées du logo DallyTrading officiel fourni par le
 * propriétaire de la marque. La variante maskable conserve une marge sûre
 * pour les formes d'icônes Android.
 *
 * `orientation: portrait` parce que la saisie se fait debout, d'une main.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Dally Ops — DallyTrading',
    short_name: 'Dally Ops',
    description:
      'Réception de colis, caisse et rendez-vous pour les logisticiens DallyTrading.',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    orientation: 'portrait',
    lang: 'fr',
    theme_color: '#16365B',
    background_color: '#ffffff',
    icons: [
      {
        src: '/icones/dallytrading-ops-192.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'any',
      },
      {
        src: '/icones/dallytrading-ops-512.jpg',
        sizes: '512x512',
        type: 'image/jpeg',
        purpose: 'any',
      },
      {
        src: '/icones/dallytrading-ops-maskable-512.jpg',
        sizes: '512x512',
        type: 'image/jpeg',
        purpose: 'maskable',
      },
    ],
  };
}
