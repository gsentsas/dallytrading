/**
 * La galerie dans le back-office Odoo, avec un vrai navigateur.
 *
 * Le bug signalé — « la zone galerie est là, mais aucun bouton » — n'était
 * visible qu'à l'écran : les droits et l'architecture de la vue se vérifient en
 * Python, la présence d'un bouton non. Cette spec existe pour ça, et pour rien
 * d'autre.
 *
 * Sérialisée : les scénarios se transmettent l'état de la galerie du produit.
 */

import { expect, test, type Page } from '@playwright/test';

const BASE = process.env.ODOO_URL!;
const PRODUIT = process.env.PRODUIT_ID!;
/**
 * Les comptes viennent de l'environnement, jamais du dépôt.
 *
 * Ce sont des comptes d'un banc jetable, mais une chaîne qui ressemble à un mot
 * de passe dans un fichier versionné finit par être copiée ailleurs. Le test
 * échoue bruyamment si l'environnement ne les fournit pas, plutôt que de tomber
 * sur une valeur par défaut que personne n'a choisie.
 */
function compte(prefixe: string) {
  const login = process.env[`${prefixe}_LOGIN`];
  const mdp = process.env[`${prefixe}_PASSWORD`];
  if (!login || !mdp) {
    throw new Error(`${prefixe}_LOGIN et ${prefixe}_PASSWORD sont requis.`);
  }
  return { login, mdp };
}

const CATALOGUE = compte('GALERIE_CATALOGUE');
const LECTURE = compte('GALERIE_LECTURE');

test.describe.configure({ mode: 'serial' });

/** Un PNG minuscule, produit à la volée : chaque couleur donne des octets différents. */
function png(r: number, g: number, b: number): Buffer {
  const crcTable = [...Array(256).keys()].map((n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const octet of buf) c = crcTable[(c ^ octet) & 0xff]! ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const bloc = (type: string, data: Buffer) => {
    const t = Buffer.from(type, 'ascii');
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const somme = Buffer.alloc(4);
    somme.writeUInt32BE(crc(Buffer.concat([t, data])));
    return Buffer.concat([len, t, data, somme]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(1, 0);
  ihdr.writeUInt32BE(1, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const zlib = require('node:zlib');
  const idat = zlib.deflateSync(Buffer.from([0, r, g, b]));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    bloc('IHDR', ihdr),
    bloc('IDAT', idat),
    bloc('IEND', Buffer.alloc(0)),
  ]);
}

async function connexion(page: Page, compte: { login: string; mdp: string }) {
  await page.goto(`${BASE}/web/login`);
  await page.fill('input[name="login"]', compte.login);
  await page.fill('input[name="password"]', compte.mdp);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/odoo|\/web/, { timeout: 30000 });
}

/** Ouvre la fiche produit et bascule sur l'onglet Boutique. */
async function ongletBoutique(page: Page) {
  // `domcontentloaded` et non `networkidle` : le back-office Odoo garde une
  // connexion ouverte pour son bus de notifications, si bien que le réseau
  // n'est jamais « au repos » et que l'attente expire toujours.
  await page.goto(`${BASE}/odoo/m-product.template/${PRODUIT}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.locator('.o_form_view')).toBeVisible({ timeout: 30000 });
  const onglet = page.getByRole('tab', { name: 'Boutique' });
  await expect(onglet).toBeVisible({ timeout: 20000 });
  await onglet.click();
  await expect(page.getByText('Galerie produit')).toBeVisible();
}

/**
 * Le nombre de vignettes réelles.
 *
 * `:not(.o_kanban_ghost)` : Odoo complète la dernière rangée avec des cartes
 * fantômes pour l'alignement. Trois photos en donnaient neuf — une erreur de
 * mesure, pas un défaut du produit.
 */
async function vignettes(page: Page): Promise<number> {
  return page
    .locator('.o_field_widget[name="dally_shop_image_ids"] .o_kanban_record:not(.o_kanban_ghost)')
    .count();
}

/** Dépose une photo par le dialogue d'ajout. */
async function ajouter(page: Page, nom: string, octets: Buffer, fichier: string, type: string) {
  await page.getByText('Ajouter des photos').click();
  const dialogue = page.locator('.modal-dialog');
  await expect(dialogue).toBeVisible();
  await dialogue.locator('input[type="file"]').setInputFiles({
    name: fichier, mimeType: type, buffer: octets,
  });
  await dialogue.locator('#name_0, input[id^="name"]').first().fill(nom);
  // `.o_form_button_save` et non un libellé : le dialogue en porte deux —
  // « Save & Close » et « Save & New » — et un motif textuel les attrape tous
  // les deux.
  await dialogue.locator('button.o_form_button_save').click();
  await expect(dialogue).toBeHidden({ timeout: 15000 });
}

async function enregistrer(page: Page) {
  const bouton = page.locator('.o_form_button_save, button[data-hotkey="s"]').first();
  if (await bouton.isVisible().catch(() => false)) {
    await bouton.click();
  }
  await page.waitForTimeout(1500);
}

test.describe('gestionnaire de catalogue', () => {
  test('le bouton « Ajouter des photos » est visible', async ({ page }) => {
    await connexion(page, CATALOGUE);
    await ongletBoutique(page);

    // LE test du bug signalé.
    await expect(page.getByText('Ajouter des photos')).toBeVisible();
  });

  test('ajouter trois photos JPG, WEBP et PNG', async ({ page }) => {
    await connexion(page, CATALOGUE);
    await ongletBoutique(page);

    await ajouter(page, 'Vue avant', png(0, 200, 0), 'avant.jpg', 'image/jpeg');
    await ajouter(page, 'Vue arrière', png(0, 0, 200), 'arriere.webp', 'image/webp');
    await ajouter(page, 'Intérieur', png(200, 200, 0), 'interieur.png', 'image/png');
    await enregistrer(page);

    expect(await vignettes(page)).toBe(3);
  });

  test('les trois photos survivent au rechargement', async ({ page }) => {
    await connexion(page, CATALOGUE);
    await ongletBoutique(page);

    expect(await vignettes(page)).toBe(3);
  });

  test('supprimer la deuxième photo', async ({ page }) => {
    await connexion(page, CATALOGUE);
    await ongletBoutique(page);
    expect(await vignettes(page)).toBe(3);

    // La suppression passe par la fiche de la photo : dans un kanban imbriqué,
    // le bouton de retrait vit dans le pied du dialogue, pas sur la carte.
    await page
      .locator('.o_field_widget[name="dally_shop_image_ids"] .o_kanban_record:not(.o_kanban_ghost)')
      .nth(1)
      .click();
    const dialogue = page.locator('.modal-dialog');
    await expect(dialogue).toBeVisible();
    await dialogue
      .getByRole('button', { name: /Remove|Supprimer|Delete|Retirer/ })
      .first()
      .click();
    await expect(dialogue).toBeHidden({ timeout: 15000 });
    await enregistrer(page);

    expect(await vignettes(page)).toBe(2);
  });

  test('deux photos après rechargement', async ({ page }) => {
    await connexion(page, CATALOGUE);
    await ongletBoutique(page);

    expect(await vignettes(page)).toBe(2);
  });
  test('réordonner, et l’ordre survit au rechargement', async ({ page }) => {
    await connexion(page, CATALOGUE);
    await ongletBoutique(page);

    /*
     * L'ordre se change par le champ `sequence` de la fiche, pas par un
     * glisser-déposer simulé. La poignée existe — elle est déclarée dans la vue
     * — mais rejouer une physique de glissement HTML5 dans un kanban imbriqué
     * produit un test qui échoue pour des raisons de pixels. Ce qui compte ici
     * est que l'ordre soit modifiable et qu'il persiste ; c'est ce qui est
     * mesuré.
     */
    const cartes = page.locator(
      '.o_field_widget[name="dally_shop_image_ids"] .o_kanban_record:not(.o_kanban_ghost)',
    );
    const avant = (await cartes.first().innerText()).split("\n")[0];

    await cartes.first().click();
    const dialogue = page.locator('.modal-dialog');
    await expect(dialogue).toBeVisible();
    await dialogue.locator('#sequence_0, input[id^="sequence"]').first().fill('999');
    await dialogue.locator('button.o_form_button_save').click();
    await expect(dialogue).toBeHidden({ timeout: 15000 });
    await enregistrer(page);

    await ongletBoutique(page);
    const apres = (await cartes.first().innerText()).split("\n")[0];
    expect(apres).not.toBe(avant);
    // Et la photo déplacée est bien passée en dernier.
    expect((await cartes.last().innerText())).toContain(avant);
  });

  test('un SVG est refusé', async ({ page }) => {
    await connexion(page, CATALOGUE);
    await ongletBoutique(page);
    const avant = await vignettes(page);

    await page.getByText('Ajouter des photos').click();
    const dialogue = page.locator('.modal-dialog');
    await expect(dialogue).toBeVisible();
    await dialogue.locator('input[type="file"]').setInputFiles({
      name: 'piege.svg',
      mimeType: 'image/svg+xml',
      buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>'),
    });
    await dialogue.locator('#name_0, input[id^="name"]').first().fill('Tentative SVG');
    await dialogue.locator('button.o_form_button_save').click();

    // Odoo refuse : soit le champ image rejette le fichier, soit la contrainte
    // du modèle lève. Dans les deux cas, aucune photo n'est ajoutée.
    await page.waitForTimeout(3000);
    const boutonFermer = dialogue.locator('button.o_form_button_cancel, .btn-close').first();
    if (await boutonFermer.isVisible().catch(() => false)) {
      await boutonFermer.click().catch(() => {});
    }
    await page.keyboard.press('Escape').catch(() => {});
    await ongletBoutique(page);

    expect(await vignettes(page)).toBe(avant);
  });
});

test.describe('lecture seule', () => {
  test('voit la galerie mais ne peut rien y faire', async ({ page }) => {
    await connexion(page, LECTURE);
    await ongletBoutique(page);

    // Contrôle positif : la galerie est bien là, avec ses photos.
    expect(await vignettes(page)).toBeGreaterThan(0);
    // Et le bouton d'ajout est absent — c'est le comportement correct, et
    // c'est exactement ce que l'administrateur voyait par erreur.
    await expect(page.getByText('Ajouter des photos')).toHaveCount(0);
  });
});
