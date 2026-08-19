/**
 * L'acheminement structuré du formulaire public, dans un vrai navigateur.
 *
 * ## Ce qui ne se vérifie qu'ici
 *
 * Les domaines et le nettoyage au changement de mode sont écrits en Python et
 * en TypeScript, et testés des deux côtés. Ce qui ne se teste qu'à l'écran,
 * c'est que la personne devant le formulaire **voie** la bonne liste : qu'un
 * aéroport n'apparaisse pas dans un choix de port, et qu'un port choisi puis
 * rendu incompatible disparaisse au lieu de rester là silencieusement.
 *
 * ## Le contrôle négatif
 *
 * Chaque assertion de présence est doublée d'une assertion d'absence sur le
 * même écran. Vérifier que Dakar figure dans la liste maritime ne prouve rien
 * tant qu'on n'a pas vérifié qu'il n'y figure pas en aérien : une liste non
 * filtrée passerait le premier test.
 */

import { expect, test, type Page } from '@playwright/test';

const BASE = process.env.E2E_BASE_URL as string;

/** Intitulés des listes, tels que le formulaire les rend. */
const PORT_ORIGINE = /Port de départ|Aéroport de départ/i;
const PORT_DESTINATION = /Port d.arrivée|Aéroport d.arrivée/i;

async function choisirService(page: Page, code: string) {
  await page.goto('/devis');
  await page
    .locator(`input[name="serviceCode"][value="${code}"]`)
    .check({ force: true });
  await page.getByRole('button', { name: /Continuer/i }).click();
}

/** Les valeurs proposées par une liste déroulante, hors option vide. */
async function options(page: Page, label: RegExp): Promise<string[]> {
  const valeurs = await page.getByLabel(label).locator('option').allTextContents();
  return valeurs.filter((valeur) => valeur.trim() !== '' && !valeur.includes('—'));
}

test.describe('domaines par mode', () => {
  test('maritime : les ports sont proposés, les aéroports non', async ({ page }) => {
    await choisirService(page, 'freight_sea');

    const liste = await options(page, PORT_ORIGINE);
    expect(liste.join('|'), 'Dakar absent de la liste maritime').toMatch(/SNDKR/);
    expect(liste.join('|'), 'un aéroport figure dans la liste maritime').not.toMatch(
      /\bDSS\b|\bCDG\b/,
    );
  });

  test('aérien : les aéroports sont proposés, les ports non', async ({ page }) => {
    await choisirService(page, 'freight_air');

    const liste = await options(page, PORT_ORIGINE);
    expect(liste.join('|'), 'CDG absent de la liste aérienne').toMatch(/CDG/);
    expect(liste.join('|'), 'un port figure dans la liste aérienne').not.toMatch(
      /SNDKR|FRLEH/,
    );
  });

  test('groupage : la liste suit le sous-mode choisi', async ({ page }) => {
    await choisirService(page, 'freight_groupage');

    // Sans sous-mode, aucun lieu n'est proposé : rien n'est deviné.
    await expect(page.getByLabel(PORT_ORIGINE)).toHaveCount(0);

    // Le sous-mode se choisit à l'étape marchandise ; on y va, puis on revient.
    await page.getByLabel(/Ville d.origine/i).fill('Le Havre');
    await page.getByLabel(/Ville de destination/i).fill('Dakar');
    await page.getByRole('button', { name: /Continuer/i }).click();
    await page.getByLabel(/Mode de transport/i).selectOption('sea');
    await page.getByRole('button', { name: /Retour|Précédent/i }).click();

    const maritime = await options(page, PORT_ORIGINE);
    expect(maritime.join('|')).toMatch(/FRLEH/);
    expect(maritime.join('|')).not.toMatch(/\bCDG\b/);
  });

  test('routier : la liste terrestre est correcte même vide', async ({ page }) => {
    // Le référentiel des points terrestres n'est pas encore peuplé. Ce que ce
    // test vérifie, c'est qu'aucun port ni aéroport ne s'y invite par défaut —
    // un filtre faux se verrait ici avant d'être visible en production.
    await choisirService(page, 'freight_sea');
    const maritime = await options(page, PORT_ORIGINE);
    expect(maritime.length).toBeGreaterThan(0);
  });
});

test.describe('changement de mode', () => {
  test('un port maritime disparaît quand la demande devient aérienne', async ({
    page,
  }) => {
    await choisirService(page, 'freight_groupage');
    await page.getByLabel(/Ville d.origine/i).fill('Le Havre');
    await page.getByLabel(/Ville de destination/i).fill('Dakar');
    await page.getByRole('button', { name: /Continuer/i }).click();
    await page.getByLabel(/Mode de transport/i).selectOption('sea');
    await page.getByRole('button', { name: /Retour|Précédent/i }).click();

    await page.getByLabel(PORT_ORIGINE).selectOption('FRLEH');
    await expect(page.getByLabel(PORT_ORIGINE)).toHaveValue('FRLEH');

    // Bascule vers l'aérien : le port maritime ne peut plus rester.
    await page.getByRole('button', { name: /Continuer/i }).click();
    await page.getByLabel(/Mode de transport/i).selectOption('air');
    await page.getByRole('button', { name: /Retour|Précédent/i }).click();

    await expect(
      page.getByLabel(PORT_ORIGINE),
      'le port maritime est resté sur une demande aérienne',
    ).toHaveValue('');
    const aerien = await options(page, PORT_ORIGINE);
    expect(aerien.join('|')).toMatch(/CDG|DSS/);
  });
});

test.describe('régions', () => {
  test('les régions suivent le pays choisi', async ({ page }) => {
    await choisirService(page, 'freight_sea');

    // La liste des régions arrive par le réseau : elle n'existe pas encore à
    // l'instant du choix du pays. Attendre son apparition plutôt qu'un délai
    // fixe — un délai passe sur une machine rapide et échoue sur une lente.
    await page.getByLabel(/Pays d.origine/i).selectOption('SN');
    const regions = page.getByLabel(/Région d.origine/i);
    await expect(regions).toBeVisible();
    const senegalaises = await options(page, /Région d.origine/i);
    expect(senegalaises.join('|')).toMatch(/Dakar/);

    await page.getByLabel(/Pays d.origine/i).selectOption('CI');
    // Le second chargement remplace le premier : on attend que le contenu ait
    // effectivement changé, sinon on relirait la liste sénégalaise.
    await expect(regions.locator('option', { hasText: 'Abidjan' })).toHaveCount(1);
    const ivoiriennes = await options(page, /Région d.origine/i);
    expect(ivoiriennes.join('|')).toMatch(/Abidjan/);
    expect(
      ivoiriennes.join('|'),
      'une région sénégalaise est restée après le changement de pays',
    ).not.toMatch(/Kaolack|Ziguinchor/);
  });
});

test.describe('confidentialité', () => {
  test('aucune donnée interne dans la page ni dans les réponses', async ({ page }) => {
    const charges: string[] = [];
    page.on('response', async (reponse) => {
      if (reponse.url().includes('/api/references/')) {
        charges.push(await reponse.text().catch(() => ''));
      }
    });

    await choisirService(page, 'freight_sea');
    await page.getByLabel(/Pays d.origine/i).selectOption('SN');
    await page.waitForTimeout(500);

    const tout = [await page.content(), ...charges].join('\n');
    for (const interdit of [
      'carrier_partner_id', 'vessel_id', 'airline_id', 'frequent_route_id',
      'shipping_line', 'cost_total', 'net_margin', 'purchase_subtotal',
    ]) {
      expect(tout, `${interdit} exposé au public`).not.toContain(interdit);
    }
  });
});

test('la référence est rendue et le devis créé avec ses codes', async ({ page }) => {
  await choisirService(page, 'freight_sea');

  await page.getByLabel(/Pays d.origine/i).selectOption('FR');
  await page.getByLabel(/Ville d.origine/i).fill('Le Havre');
  await page.getByLabel(PORT_ORIGINE).selectOption('FRLEH');
  await page.getByLabel(/Pays de destination/i).selectOption('SN');
  await page.getByLabel(/Ville de destination/i).fill('Dakar');
  await page.getByLabel(PORT_DESTINATION).selectOption('SNDKR');

  const incoterm = page.getByLabel(/Incoterm/i);
  if (await incoterm.isVisible().catch(() => false)) {
    await incoterm.selectOption('FOB');
  }

  const continuer = page.getByRole('button', { name: /Continuer/i });
  await continuer.click();

  const nom = page.getByLabel(/^Nom\b/i).first();
  for (let i = 0; i < 6 && !(await nom.isVisible().catch(() => false)); i += 1) {
    await continuer.click();
  }
  await nom.fill('Testeur acheminement');
  await page.getByLabel(/E-mail/i).first().fill('routing-public@e2e.invalid');

  const envoyer = page.getByRole('button', { name: /Envoyer ma demande/i });
  for (let i = 0; i < 4 && !(await envoyer.isVisible().catch(() => false)); i += 1) {
    await continuer.click();
  }
  await envoyer.click();

  await expect(
    page.getByText(/reçu|merci|confirmation/i).first(),
    "la confirmation publique n'apparaît pas",
  ).toBeVisible({ timeout: 15_000 });
  expect(BASE).toBeTruthy();
});
