import { expect, test, type Page } from '@playwright/test';

/**
 * Faire avancer un dossier depuis le comptoir.
 *
 * Ce que les assertions protègent : l'écran ne propose que ce que le serveur a
 * renvoyé, « prêt à expédier » demande une confirmation dont l'annulation
 * n'écrit rien, et aucun bouton de départ ou d'annulation n'apparaît jamais.
 */

const GILLES = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};
const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT = '+221 77 123 45 67';

async function seConnecter(page: Page) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(GILLES.login);
  await page.getByLabel('Mot de passe').fill(GILLES.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByRole('heading', { name: /^Bonjour / })).toBeVisible();
}

/** Un dossier neuf, réceptionné par le parcours réel, puis ouvert. */
async function creerUnDossier(page: Page): Promise<string> {
  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await page.getByLabel('Numéro de téléphone').fill(CLIENT);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toBeVisible();
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();

  await page.getByLabel('Catégorie').fill('Non alimentaire');
  await page.getByLabel('Désignation').fill(`Savon état ${Date.now()}`);
  await page.getByLabel('Quantité').fill('1');
  await page.getByLabel('Poids exact total (kg)').fill('13.5');
  await page.getByLabel('Famille tarifaire').selectOption('non_food');
  await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');
  await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();

  await expect(page.getByTestId('intake-enregistre')).toBeVisible();
  const reference = (await page.getByTestId('intake-enregistre')
    .locator('.reference').textContent() ?? '').trim();
  await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
  await expect(page.getByRole('heading', { name: /^DOSSIER / })).toBeVisible();
  return reference;
}

test('un dossier avance étape par étape, sans jamais proposer le départ',
  async ({ page }) => {
    await seConnecter(page);
    await creerUnDossier(page);

    // 1. L'état est lisible, et la seule étape offerte est la préparation.
    await expect(page.getByTestId('etat-libelle')).toHaveText('Déposé');
    await expect(page.getByTestId('etat-action-preparing')).toBeVisible();
    await expect(page.getByTestId('etat-action-ready')).toHaveCount(0);
    // Jamais de départ ni d'annulation : ces étapes n'appartiennent pas au terrain.
    await expect(page.getByTestId('etat-action-departed')).toHaveCount(0);
    await expect(page.getByTestId('etat-action-cancelled')).toHaveCount(0);

    // 2. La mise en préparation s'arrête d'abord sur une confirmation : cette
    //    étape aussi se voit dans le suivi client.
    await page.getByTestId('etat-action-preparing').click();
    const confirmationPreparation = page.getByTestId('etat-confirmation');
    await expect(confirmationPreparation).toBeVisible();
    await expect(confirmationPreparation).toContainText('suivi client');
    await expect(confirmationPreparation).toContainText('En préparation');

    // 3. Annuler n'écrit rien : le dossier est toujours déposé.
    await page.getByRole('button', { name: 'Annuler' }).click();
    await expect(confirmationPreparation).toHaveCount(0);
    await expect(page.getByTestId('etat-libelle')).toHaveText('Déposé');

    // 4. Confirmer avance réellement.
    await page.getByTestId('etat-action-preparing').click();
    await page.getByRole('button', { name: 'Confirmer' }).click();
    await expect(page.getByTestId('etat-libelle')).toHaveText('En préparation', {
      timeout: 20_000,
    });

    // 5. L'étape suivante a changé, et elle seule est proposée.
    await expect(page.getByTestId('etat-action-ready')).toBeVisible();
    await expect(page.getByTestId('etat-action-preparing')).toHaveCount(0);

    // 6. « Prêt à expédier » s'arrête aussi sur une confirmation.
    await page.getByTestId('etat-action-ready').click();
    const confirmation = page.getByTestId('etat-confirmation');
    await expect(confirmation).toBeVisible();
    await expect(confirmation).toContainText('suivi client');
    await expect(confirmation).toContainText('ne pourront plus être modifiés');

    // 7. Annuler n'écrit rien : le dossier n'a pas bougé.
    await page.getByRole('button', { name: 'Annuler' }).click();
    await expect(confirmation).toHaveCount(0);
    await expect(page.getByTestId('etat-libelle')).toHaveText('En préparation');

    // 8. Confirmer avance réellement, et plus rien n'est proposé ensuite.
    await page.getByTestId('etat-action-ready').click();
    await page.getByRole('button', { name: 'Confirmer' }).click();
    await expect(page.getByTestId('etat-libelle')).toHaveText('Prêt', {
      timeout: 20_000,
    });
    await expect(page.getByTestId('etat-action-ready')).toHaveCount(0);
    await expect(page.getByTestId('etat-action-departed')).toHaveCount(0);
  });
