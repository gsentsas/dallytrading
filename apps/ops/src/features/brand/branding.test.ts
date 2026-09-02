import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { inflateSync } from 'node:zlib';

import { describe, expect, it } from 'vitest';

/**
 * La marque DallyTrading dans Dally Ops.
 *
 * ## Ce que ces tests protègent
 *
 * **Le logo n'est jamais reconstruit.** Ni en CSS, ni en texte, ni en
 * monogramme. Une approximation du logo d'une entreprise est pire que pas de
 * logo : elle a l'air presque juste, et c'est ainsi qu'une mauvaise version
 * finit sur une facture imprimée.
 *
 * **Rien n'est rogné.** Les icônes de l'application installée dérivent du logo
 * **complet** — emblème, wordmark, signature. Les tests le vérifient sur les
 * pixels, pas sur les intentions : les bords doivent être blancs, donc le
 * dessin est entier ; et pour la variante `maskable`, tout ce qui sort du
 * disque de sûreté d'Android doit être blanc, donc rien ne sera découpé.
 */

const racine = (chemin: string) =>
  fileURLToPath(new URL(`../../../${chemin}`, import.meta.url));

const source = (chemin: string) => readFileSync(racine(chemin), 'utf8');

/** Le code seul : un commentaire qui *nomme* l'interdit n'est pas l'interdit. */
const codeSeul = (chemin: string) => source(chemin)
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/\/\/.*$/gm, '')
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
const exists = (chemin: string) => existsSync(racine(chemin));

/** Le rapport du fichier officiel : 715 × 514 une fois détouré. */
const RAPPORT_OFFICIEL = 715 / 514;

interface Image {
  readonly largeur: number;
  readonly hauteur: number;
  pixel(x: number, y: number): readonly [number, number, number];
}

/**
 * Un décodeur PNG minimal, écrit ici plutôt qu'ajouté en dépendance.
 *
 * Il n'existe que pour une raison : prouver sur les pixels qu'aucun élément du
 * logo n'est coupé. Une assertion sur les noms de fichiers ne le prouverait
 * pas, et c'est précisément la promesse de marque en jeu.
 */
function lirePng(chemin: string): Image {
  const donnees = readFileSync(racine(chemin));
  expect(donnees.subarray(0, 8).toString('latin1'))
    .toBe('\x89PNG\r\n\x1a\n');

  let i = 8;
  let largeur = 0;
  let hauteur = 0;
  let profondeur = 0;
  let typeCouleur = 0;
  let palette = Buffer.alloc(0);
  const morceaux: Buffer[] = [];

  while (i + 8 <= donnees.length) {
    const taille = donnees.readUInt32BE(i);
    const type = donnees.subarray(i + 4, i + 8).toString('latin1');
    const corps = donnees.subarray(i + 8, i + 8 + taille);
    if (type === 'IHDR') {
      largeur = corps.readUInt32BE(0);
      hauteur = corps.readUInt32BE(4);
      profondeur = corps[8]!;
      typeCouleur = corps[9]!;
    } else if (type === 'PLTE') palette = Buffer.from(corps);
    else if (type === 'IDAT') morceaux.push(Buffer.from(corps));
    else if (type === 'IEND') break;
    i += 12 + taille;
  }
  expect(profondeur, `${chemin} : profondeur`).toBe(8);
  expect([2, 3, 6], `${chemin} : type de couleur`).toContain(typeCouleur);

  const canaux = typeCouleur === 3 ? 1 : typeCouleur === 2 ? 3 : 4;
  const brut = inflateSync(Buffer.concat(morceaux));
  const ligneOctets = largeur * canaux;
  const lignes: Buffer[] = [];
  let precedente = Buffer.alloc(ligneOctets);

  for (let y = 0; y < hauteur; y += 1) {
    const debut = y * (ligneOctets + 1);
    const filtre = brut[debut]!;
    const ligne = Buffer.from(brut.subarray(debut + 1, debut + 1 + ligneOctets));
    for (let x = 0; x < ligneOctets; x += 1) {
      const a = x >= canaux ? ligne[x - canaux]! : 0;
      const b = precedente[x]!;
      const c = x >= canaux ? precedente[x - canaux]! : 0;
      let ajout = 0;
      if (filtre === 1) ajout = a;
      else if (filtre === 2) ajout = b;
      else if (filtre === 3) ajout = (a + b) >> 1;
      else if (filtre === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a);
        const pb = Math.abs(p - b);
        const pc = Math.abs(p - c);
        ajout = pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      ligne[x] = (ligne[x]! + ajout) & 0xff;
    }
    lignes.push(ligne);
    precedente = ligne;
  }

  return {
    largeur,
    hauteur,
    pixel(x, y) {
      const ligne = lignes[y]!;
      if (typeCouleur === 3) {
        const index = ligne[x]! * 3;
        return [palette[index]!, palette[index + 1]!, palette[index + 2]!];
      }
      const base = x * canaux;
      return [ligne[base]!, ligne[base + 1]!, ligne[base + 2]!];
    },
  };
}

const estBlanc = ([r, v, b]: readonly [number, number, number]) =>
  r >= 250 && v >= 250 && b >= 250;

describe('le logo officiel, jamais reconstruit', () => {
  it('l’en-tête affiche le fichier du logo complet', () => {
    const brand = source('src/features/brand/DallyTradingBrand.tsx');
    expect(brand).toContain("src=\"/brand/dallytrading-logo.png\"");
    expect(exists('public/brand/dallytrading-logo.png')).toBe(true);
  });

  it('aucun wordmark n’est reconstruit en CSS ni en texte', () => {
    const brand = source('src/features/brand/DallyTradingBrand.tsx');
    const css = source('src/app/brand.css');
    for (const classe of ['ops-brand-wordmark', 'ops-brand-dally',
                          'ops-brand-trading', 'ops-brand-signature']) {
      expect(css, classe).not.toContain(classe);
      expect(brand, classe).not.toContain(classe);
    }
    // Le mot « DallyTrading » ne doit exister que comme texte accessible, et
    // jamais découpé en deux fragments colorés séparément.
    expect(brand).not.toContain('>Dally<');
    expect(brand).not.toContain('>Trading<');
    expect(brand).not.toContain('IMPORT');
  });

  it('aucun monogramme ni pictogramme alternatif n’est utilisé', () => {
    const brand = codeSeul('src/features/brand/DallyTradingBrand.tsx');
    const layout = codeSeul('src/app/layout.tsx');
    const manifest = codeSeul('src/app/manifest.ts');
    for (const alternative of ['monogram', 'monogramme', 'dt-mark', 'dallytrading-dt',
                               'dallytrading-ops.svg', 'dallytrading-ops-mark']) {
      for (const fichier of [brand, layout, manifest]) {
        expect(fichier, alternative).not.toContain(alternative);
      }
    }
  });

  it('« Dally Ops » reste un libellé d’application distinct', () => {
    const brand = source('src/features/brand/DallyTradingBrand.tsx');
    expect(brand).toContain('Dally Ops');
    expect(brand).toContain('ops-brand-app');
  });
});

describe('les icônes dérivent du logo complet', () => {
  const carrees = [
    ['public/icones/dallytrading-ops-192.png', 192],
    ['public/icones/dallytrading-ops-512.png', 512],
    ['public/icones/dallytrading-ops-apple-180.png', 180],
    ['public/icones/dallytrading-ops-maskable-512.png', 512],
    ['public/icones/dallytrading-ops-favicon-32.png', 32],
    ['public/icones/dallytrading-ops-favicon-16.png', 16],
  ] as const;

  it.each(carrees)('%s est un PNG carré de la taille annoncée', (chemin, cote) => {
    const image = lirePng(chemin);
    expect(image.largeur).toBe(cote);
    expect(image.hauteur).toBe(cote);
  });

  it('le fichier de marque conserve les proportions officielles', () => {
    const image = lirePng('public/brand/dallytrading-logo.png');
    expect(image.largeur / image.hauteur).toBeCloseTo(RAPPORT_OFFICIEL, 2);
  });

  it.each(carrees)('%s ne touche aucun bord : rien n’est rogné', (chemin, cote) => {
    const image = lirePng(chemin);
    for (let x = 0; x < cote; x += 1) {
      expect(estBlanc(image.pixel(x, 0)), `${chemin} bord haut x=${x}`).toBe(true);
      expect(estBlanc(image.pixel(x, cote - 1)), `${chemin} bord bas x=${x}`).toBe(true);
    }
    for (let y = 0; y < cote; y += 1) {
      expect(estBlanc(image.pixel(0, y)), `${chemin} bord gauche y=${y}`).toBe(true);
      expect(estBlanc(image.pixel(cote - 1, y)), `${chemin} bord droit y=${y}`).toBe(true);
    }
  });

  it('les icônes portent réellement le dessin, pas une plaque vide', () => {
    const image = lirePng('public/icones/dallytrading-ops-512.png');
    let encre = 0;
    let marine = 0;
    let vert = 0;
    for (let y = 0; y < 512; y += 2) {
      for (let x = 0; x < 512; x += 2) {
        const [r, v, b] = image.pixel(x, y);
        if (!estBlanc([r, v, b])) encre += 1;
        if (b > r && b > v && b > 40 && r < 90) marine += 1;
        if (v > r && v > b && v > 90) vert += 1;
      }
    }
    expect(encre).toBeGreaterThan(1000);
    expect(marine, 'le marine de la marque').toBeGreaterThan(100);
    expect(vert, 'le vert de la marque').toBeGreaterThan(100);
  });

  it('la variante maskable tient entière dans la zone sûre d’Android', () => {
    // Android peut découper l'icône dans n'importe quelle forme ; seul le
    // disque central de 80 % du côté est garanti visible. Tout ce qui déborde
    // doit donc être blanc, faute de quoi un morceau du logo serait coupé.
    const image = lirePng('public/icones/dallytrading-ops-maskable-512.png');
    const centre = 512 / 2;
    const rayonSur = (512 * 0.8) / 2;
    let dehors = 0;
    for (let y = 0; y < 512; y += 1) {
      for (let x = 0; x < 512; x += 1) {
        const d = Math.hypot(x + 0.5 - centre, y + 0.5 - centre);
        if (d > rayonSur && !estBlanc(image.pixel(x, y))) dehors += 1;
      }
    }
    expect(dehors, 'pixels de logo hors du disque de sûreté').toBe(0);
  });
});

describe('le manifeste et les métadonnées suivent les fichiers', () => {
  it('le manifeste ne déclare que des PNG existants, aux bonnes dimensions', () => {
    const manifest = source('src/app/manifest.ts');
    for (const [chemin, taille] of [
      ['/icones/dallytrading-ops-192.png', '192x192'],
      ['/icones/dallytrading-ops-512.png', '512x512'],
      ['/icones/dallytrading-ops-maskable-512.png', '512x512'],
    ] as const) {
      expect(manifest).toContain(`src: '${chemin}'`);
      expect(manifest).toContain(`sizes: '${taille}'`);
      expect(exists(`public${chemin}`)).toBe(true);
    }
    expect(manifest).toContain("type: 'image/png'");
    expect(manifest).not.toContain('image/jpeg');
    expect(manifest).toContain("purpose: 'any'");
    expect(manifest).toContain("purpose: 'maskable'");
    expect(manifest).toContain("theme_color: '#16365B'");
    expect(manifest).toContain("background_color: '#ffffff'");
  });

  it('les métadonnées Apple et le favicon pointent le logo officiel', () => {
    const layout = source('src/app/layout.tsx');
    expect(layout).toContain('/icones/dallytrading-ops-apple-180.png');
    expect(layout).toContain('/icones/dallytrading-ops-favicon-32.png');
    expect(layout).toContain('/icones/dallytrading-ops-favicon-16.png');
    expect(layout).toContain('appleWebApp');
    expect(layout).toContain("themeColor: '#16365B'");
    expect(exists('public/icones/dallytrading-ops-apple-180.png')).toBe(true);
  });

  it('le logo reste disponible hors connexion', () => {
    // Le service worker met /icones/ en cache ; le logo de l'en-tête vit
    // sous /brand/. Sans cette ligne, l'en-tête montrerait une image cassée
    // exactement quand le réseau manque.
    const sw = source('public/sw.js');
    expect(sw).toContain("url.pathname.startsWith('/brand/')");
  });

  it('le branding est posé une seule fois, par le layout racine', () => {
    const layout = source('src/app/layout.tsx');
    expect(layout).toContain('DallyTradingBrand');
    expect(layout).toContain('ops-brand-header');
  });

  it('les anciennes icônes ont disparu du dépôt comme du code', () => {
    const anciennes = ['ops-192.png', 'ops-512.png', 'ops-maskable-512.png',
                       'dallytrading-ops-512.jpg', 'dallytrading-ops-maskable-512.jpg'];
    for (const nom of anciennes) {
      expect(exists(`public/icones/${nom}`), nom).toBe(false);
    }
    const fichiers = readdirSync(racine('public/icones'));
    expect(fichiers.filter((n) => !n.startsWith('dallytrading-ops-'))).toEqual([]);
    expect(fichiers.every((n) => n.endsWith('.png'))).toBe(true);

    const manifest = source('src/app/manifest.ts');
    const layout = source('src/app/layout.tsx');
    const brand = source('src/features/brand/DallyTradingBrand.tsx');
    for (const nom of anciennes) {
      // Le chemin entier, pas le nom nu : « ops-192.png » est une
      // sous-chaîne de « dallytrading-ops-192.png », qui est légitime.
      const chemin = `/icones/${nom}`;
      for (const fichier of [manifest, layout, brand]) {
        expect(fichier, chemin).not.toContain(chemin);
      }
    }
  });
});
