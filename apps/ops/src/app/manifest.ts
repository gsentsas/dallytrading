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
    theme_color: '#0f172a',
    background_color: '#0f172a',
    icons: [
      { src: '/icones/ops-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icones/ops-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icones/ops-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
}
