import { expect, test, type Page } from '@playwright/test';

/**
 * Consigner un fait, et vérifier qu'il ne fait rien d'autre.
 *
 * Ce que ce parcours prouve et qu'aucun test unitaire ne peut prouver : que
 * l'événement traverse la chaîne entière — navigateur, BFF, session Odoo,
 * `dally.shipment.event` — puis revient après rechargement, **sans** que
 * l'état du dossier ait bougé.
 *
 * Le contrôle décisif est le dernier : l'état affiché avant et après doit être
 * identique. Un événement décrit, il ne fait pas avancer.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT_CONNU = '+221 77 123 45 67';

async function ouvrirLAccueil(page: Page) {
  await page.goto('/');
  if (/\/connexion$/.test(page.url())) {
    await page.getByLabel('Identifiant').fill(OPERATEUR.login);
    await page.getByLabel('Mot de passe').fill(OPERATEUR.password);
    await page.getByRole('button', { name: 'Se connecter' }).click();
  }
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
}

async function creerUnDossier(page: Page): Promise<string> {
  await ouvrirLAccueil(page);
  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await page.getByLabel('Numéro de téléphone').fill(CLIENT_CONNU);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toBeVisible();
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();

  await page.getByLabel('Catégorie').fill('Non alimentaire');
  await page.getByLabel('Désignation').fill('Savon');
  await page.getByLabel('Quantité').fill('1');
  await page.getByLabel('Poids exact total (kg)').fill('13.5');
  await page.getByLabel('Famille tarifaire').selectOption('non_food');
  await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');
  await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();

  await expect(page.getByTestId('intake-enregistre')).toBeVisible();
  const reference = await page.getByTestId('intake-enregistre')
    .locator('.reference').textContent();
  return (reference ?? '').trim();
}

test('un fait est consigné, relu après rechargement, et laisse l’état intact',
  async ({ page }) => {
    const reference = await creerUnDossier(page);
    await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
    await expect(page.getByRole('heading', { name: /^DOSSIER A\d{3}$/ })).toBeVisible();

    const etatDossier = page.getByTestId('etat-libelle');
    const etatAvant = await etatDossier.textContent();

    await expect(page.getByTestId('evenements-dossier')).toBeVisible();
    await expect(page.getByTestId('aucun-evenement')).toBeVisible();

    await page.getByTestId('ouvrir-evenement').click();
    // La nature exige une note : le bouton reste gris tant qu'elle manque.
    await page.getByTestId('choix-nature-evenement').selectOption('damage_noted');
    await expect(page.getByTestId('envoyer-evenement')).toBeDisabled();

    await page.getByTestId('note-evenement').fill('Coin du carton écrasé');
    await expect(page.getByTestId('envoyer-evenement')).toBeEnabled();
    await page.getByTestId('envoyer-evenement').click();

    await expect(page.getByTestId('evenement')).toHaveCount(1);
    await expect(page.getByTestId('evenement-nature')).toHaveText('Dommage constaté');
    await expect(page.getByTestId('evenement-note')).toHaveText('Coin du carton écrasé');
    await expect(page.getByTestId('evenement-auteur')).toHaveText('Gilles');
    await expect(page.getByTestId('evenement-source')).toHaveText('Terrain');
    await expect(page.getByTestId('evenement-date')).toHaveText(
      /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/);

    // Rien ne vit dans la page : tout vient d'Odoo.
    await page.reload();
    await expect(page.getByTestId('evenement')).toHaveCount(1);
    await expect(page.getByTestId('evenement-nature')).toHaveText('Dommage constaté');

    // Le contrôle décisif : l'état du dossier n'a pas bougé d'un mot.
    await expect(etatDossier).toHaveText(etatAvant ?? '');
  });
