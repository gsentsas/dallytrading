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
 * ## Pourquoi le test observe le rendu, et non le fichier
 *
 * Le projet n'embarque ni Testing Library ni `jest-dom` — les tests de
 * composant rendent le balisage avec `renderToStaticMarkup`. On lit donc les
 * styles **réellement produits**, attribut par attribut, plutôt que le texte
 * du composant : renommer une constante ne doit pas casser ce test, et
 * supprimer une déclaration doit le casser.
 */

/** Le contenu d'un attribut `style` rendu, en table déclaration → valeur. */
function stylesDe(balise: string): Record<string, string> {
  const attribut = /style="([^"]*)"/.exec(balise);
  if (!attribut?.[1]) return {};
  return Object.fromEntries(
    attribut[1]
      .split(';')
      .filter(Boolean)
      .map((declaration) => {
        const separateur = declaration.indexOf(':');
        return [
          declaration.slice(0, separateur).trim().toLowerCase(),
          declaration.slice(separateur + 1).trim().toLowerCase(),
        ];
      }),
  );
}

function baliseDe(html: string, nom: 'input' | 'button' | 'div'): string {
  const trouve = new RegExp(`<${nom}\\b[^>]*>`).exec(html);
  if (!trouve) throw new Error(`aucune balise <${nom}> rendue`);
  return trouve[0];
}

const html = renderToStaticMarkup(<FormulaireRecherche />);
const champ = stylesDe(baliseDe(html, 'input'));
const bouton = stylesDe(baliseDe(html, 'button'));
const rangee = stylesDe(baliseDe(html, 'div'));

describe('mise en page de la barre de recherche', () => {
  it('range le champ et le bouton sur une même ligne', () => {
    expect(rangee['display']).toBe('flex');
    expect(rangee['gap']).toBeTruthy();
  });

  it('donne au champ tout l’espace restant', () => {
    // `flex: 1` seul ne suffit pas : la base automatique laisse le contenu
    // décider, et un `width: 100%` hérité reprend la main.
    expect(champ['flex']).toBe('1 1 0');
  });

  it('autorise le champ à rétrécir sous sa largeur intrinsèque', () => {
    // Sans `min-width: 0`, un élément flex refuse de passer sous la taille de
    // son contenu : c'est exactement ce qui écrase le champ sur mobile étroit.
    expect(champ['min-width']).toBe('0');
  });

  it('neutralise le `width: 100%` global sur le champ', () => {
    expect(champ['width']).toBe('auto');
    expect(champ['width']).not.toBe('100%');
  });

  it('neutralise le `width: 100%` global sur le bouton', () => {
    expect(bouton['width']).toBe('auto');
    expect(bouton['width']).not.toBe('100%');
  });

  it('donne au bouton la seule largeur de son texte', () => {
    // `0 0 auto` : il ne grandit pas, ne rétrécit pas, et part de son contenu.
    expect(bouton['flex']).toBe('0 0 auto');
  });

  it('garde « Effacer » sur une seule ligne', () => {
    expect(bouton['white-space']).toBe('nowrap');
  });

  it('aligne le champ et le bouton sur la même hauteur', () => {
    // `input` porte un `margin-top` global qui, dans une rangée, décalerait le
    // champ vers le bas. L'espacement sous l'étiquette passe donc à la rangée.
    expect(rangee['align-items']).toBe('stretch');
    expect(champ['margin-top']).toBe('0');
    expect(rangee['margin-top']).toBeTruthy();
  });

  it('rend bien les deux commandes attendues', () => {
    expect(html).toContain('Nom, téléphone ou référence');
    expect(html).toContain('Effacer');
  });
});
