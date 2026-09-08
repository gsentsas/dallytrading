/**
 * Les pictogrammes des cartes d'accès rapide.
 *
 * Les maquettes ne montrent pas des caractères typographiques mais de vraies
 * icônes blanches sur un carré coloré. Un glyphe emprunté à une police (`⌕`,
 * `◇`, `⇥`) ne dessine pas la même chose d'un appareil à l'autre, et sur un
 * téléphone de terrain il tombe souvent sur le rectangle de remplacement.
 *
 * Ces tracés sont donc dessinés ici, à taille fixe, dans le vocabulaire des
 * maquettes : un objet reconnaissable par métier — un dossier qu'on cherche,
 * un colis, un camion, une carte de paiement, des pièces, un échange, un
 * calendrier, une équipe.
 *
 * Ils sont purement décoratifs : le nom de l'accès est porté par le texte de
 * la carte, jamais par l'icône.
 */
export type OpsCardIconName =
  | 'recherche' | 'reception' | 'chargement' | 'encaissement'
  | 'depenses' | 'transferts' | 'agenda' | 'supervision' | 'traitement'
  | 'saisies' | 'insight';

const TRAIT = {
  fill: 'none',
  stroke: 'currentColor',
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  strokeWidth: 1.7,
};

const TRACES: Record<OpsCardIconName, React.JSX.Element> = {
  recherche: (
    <>
      <path {...TRAIT} d="M5 4.6h5l1.5 1.9H19v11.9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z" />
      <circle {...TRAIT} cx="12" cy="13" r="2.9" />
      <path {...TRAIT} d="m14.3 15.3 2 2" />
    </>
  ),
  reception: (
    <>
      <path {...TRAIT} d="m12 3.4 7.4 4.1v8.9L12 20.6l-7.4-4.2V7.5z" />
      <path {...TRAIT} d="m4.6 7.5 7.4 4.2 7.4-4.2M12 11.7v8.9" />
    </>
  ),
  chargement: (
    <>
      <path {...TRAIT} d="M3 6.6h10.2v9.2H3zM13.2 9.4h3.6l3.2 3.4v3H13.2z" />
      <circle {...TRAIT} cx="6.6" cy="17.8" r="1.8" />
      <circle {...TRAIT} cx="16.8" cy="17.8" r="1.8" />
    </>
  ),
  encaissement: (
    <>
      <rect {...TRAIT} x="2.9" y="5.6" width="18.2" height="12.8" rx="2.1" />
      <path {...TRAIT} d="M2.9 9.9h18.2M6.3 14.6h4.2" />
    </>
  ),
  depenses: (
    <>
      <ellipse {...TRAIT} cx="12" cy="6.6" rx="6.6" ry="2.6" />
      <path {...TRAIT} d="M5.4 6.6v4.3c0 1.4 3 2.6 6.6 2.6s6.6-1.2 6.6-2.6V6.6" />
      <path {...TRAIT} d="M5.4 10.9v4.3c0 1.5 3 2.6 6.6 2.6s6.6-1.1 6.6-2.6v-4.3" />
    </>
  ),
  transferts: (
    <>
      <path {...TRAIT} d="M4 8.7h13.4l-3-3M20 15.3H6.6l3 3" />
    </>
  ),
  agenda: (
    <>
      <rect {...TRAIT} x="3.6" y="5.2" width="16.8" height="15.1" rx="2.1" />
      <path {...TRAIT} d="M3.6 10h16.8M8.2 3.4v3.4M15.8 3.4v3.4" />
      <path {...TRAIT} d="M7.6 13.6h2.2M14.2 13.6h2.2M7.6 16.8h2.2M14.2 16.8h2.2" />
    </>
  ),
  supervision: (
    <>
      <circle {...TRAIT} cx="9.2" cy="8.6" r="2.9" />
      <path {...TRAIT} d="M3.6 19.4c0-3.1 2.5-5.2 5.6-5.2s5.6 2.1 5.6 5.2" />
      <path {...TRAIT} d="M16.1 6.2a2.7 2.7 0 0 1 0 5.2M17.2 14.6c2.1.6 3.2 2.3 3.2 4.8" />
    </>
  ),
  traitement: (
    <>
      <path {...TRAIT} d="M12 3.9 21 19.6H3z" />
      <path {...TRAIT} d="M12 9.9v4.1M12 16.6v.1" />
    </>
  ),
  saisies: (
    <>
      <path {...TRAIT} d="M6 3.6h8.4L19 8.2v12.2H6z" />
      <path {...TRAIT} d="M14 3.6v4.8h4.8M9 12.4h6M9 15.8h6" />
    </>
  ),
  insight: (
    <>
      <path {...TRAIT} d="M5.4 19V13M12 19V6.6M18.6 19v-8.4" />
    </>
  ),
};

export function OpsCardIcon(
  { name }: { readonly name: OpsCardIconName },
): React.JSX.Element {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {TRACES[name]}
    </svg>
  );
}
