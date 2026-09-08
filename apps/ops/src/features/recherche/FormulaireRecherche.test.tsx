import { readFileSync } from 'node:fs';

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { FormulaireRecherche } from '@/features/recherche/FormulaireRecherche';

/**
 * La barre de recherche, telle qu'un téléphone la met en page.
 *
 * ## Ce que ce test protège, et pourquoi il existe
 *
 * `globals.css` impose `width: 100%` à **tout** `input` et à **tout**
 * `button`. C'est le bon défaut pour les formulaires empilés de Dally Ops :
 * un champ pleine largeur se vise au pouce.
 *
 * Mais la barre de recherche met un champ et un bouton sur la même rangée.
 * Les deux réclament alors 100 % de la largeur, et Chrome Android tranche à sa
 * façon : il écrase le champ jusqu'à ne laisser voir que la croix de
 * `type="search"`, pendant que « Effacer » prend presque toute la ligne.
 * Constaté en production.
 *
 * ## Pourquoi ce test a changé de cible
 *
 * La protection était d'abord posée en styles inline sur le composant. Elle
 * marchait sur grand écran et empêchait tout le reste : un `display: flex`
 * en ligne l'emporte sur n'importe quelle règle, y compris sur le palier
 * mobile où « Effacer » doit passer **sous** le champ. Le bouton ne pouvait
 * donc jamais descendre, quelle que soit la largeur.
 *
 * La mise en page est maintenant entièrement dans `ui-search.css`, en grille.
 * Ce test lit donc la feuille de style — c'est là que le comportement vit — et
 * vérifie en plus que le composant n'y remet pas de style inline de mise en
 * page. Les deux garanties comptent : la première protège du bug de
 * production, la seconde protège le palier mobile.
 */

const FEUILLE = readFileSync(
  new URL('../../app/ui-search.css', import.meta.url), 'utf8',
);

/** Le corps d'une règle CSS, lu dans la feuille (dernier bloc gagnant). */
function regle(selecteur: string, dansMedia?: string): string {
  const source = dansMedia
    ? FEUILLE.slice(FEUILLE.indexOf(dansMedia))
    : FEUILLE;
  const echappe = selecteur.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const trouve = new RegExp(`${echappe}\\s*\\{([^}]*)\\}`).exec(source);
  const corps = trouve?.[1];
  if (corps === undefined) throw new Error(`règle introuvable : ${selecteur}`);
  return corps.replace(/\s+/g, ' ').trim();
}

const html = renderToStaticMarkup(<FormulaireRecherche />);

describe('mise en page de la barre de recherche', () => {
  it('range le champ et le bouton sur une même ligne', () => {
    const rangee = regle('.ops-search-input-row');
    expect(rangee).toContain('display: grid');
    expect(rangee).toMatch(/grid-template-columns:\s*auto minmax\(0, 1fr\) auto/);
  });

  it('autorise le champ à rétrécir sous sa largeur intrinsèque', () => {
    // La piste `minmax(0, 1fr)` fait, en grille, ce que `min-width: 0` fait en
    // flex : sans elle, la colonne refuse de passer sous la taille du contenu,
    // et c'est exactement ce qui écrasait le champ.
    expect(regle('.ops-search-input-row')).toContain('minmax(0, 1fr)');
    expect(regle('.ops-search-input-row input')).toContain('min-width: 0');
  });

  it('neutralise le `width: 100%` global sur le bouton', () => {
    expect(regle('.ops-search-clear')).toContain('width: auto');
  });

  it('garde « Effacer » sur une seule ligne', () => {
    expect(regle('.ops-search-clear')).toContain('white-space: nowrap');
  });

  it('aligne le champ et le bouton sur la même hauteur', () => {
    const rangee = regle('.ops-search-input-row');
    expect(rangee).toContain('align-items: center');
    // Le `margin-top` global de l'input est annulé ; l'espacement sous
    // l'étiquette est porté par la rangée.
    expect(regle('.ops-search-input-row input')).toContain('margin: 0');
    expect(FEUILLE).toContain('.ops-search-input-row { margin-top: .35rem; }');
  });

  it('fait passer « Effacer » sous le champ au palier mobile', () => {
    // La raison d'être du changement : à 430 px et moins, le bouton prend
    // toute la largeur sur sa propre ligne.
    const mobile = regle('.ops-search-clear', '@media (max-width: 430px)');
    expect(mobile).toContain('grid-column: 1 / -1');
    expect(mobile).toContain('width: 100%');
  });

  it('ne remet aucun style inline de mise en page', () => {
    // Un seul `style=` en ligne suffirait à reprendre la main sur la feuille
    // et à neutraliser le palier mobile.
    expect(html).not.toMatch(/style="[^"]*display\s*:/);
    expect(html).not.toMatch(/style="[^"]*(flex|width|min-width)\s*:/);
  });

  it('rend bien les deux commandes attendues', () => {
    expect(html).toContain('Nom, téléphone ou référence');
    expect(html).toContain('Effacer');
  });
});
