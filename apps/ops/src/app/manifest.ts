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
 * ## Les icônes
 *
 * Toutes dérivent du **logo complet** officiel, à l'échelle, jamais recadrées :
 * l'emblème, le wordmark et la signature sont présents dans chacune. Le fond
 * blanc est celui sur lequel l'œuvre a été dessinée.
 *
 * La variante `maskable` mérite son propre fichier. Android découpe l'icône
 * dans une forme dont seule la zone centrale — un disque de 80 % du côté — est
 * garantie visible. Le logo y est donc réduit pour que sa **diagonale** entre
 * dans ce disque : c'est la seule façon qu'aucun angle du dessin ne soit rogné.
 * La marge ainsi gagnée est blanche, et rien d'autre ne change.
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
        src: '/icones/dallytrading-ops-512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any',
      },
      {
        src: '/icones/dallytrading-ops-maskable-512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'maskable',
      },
    ],
  };
}
