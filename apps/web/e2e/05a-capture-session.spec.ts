/**
 * Première moitié du scénario « session Odoo expirée ».
 *
 * Ce fichier se connecte et SAUVEGARDE l'état du navigateur sur disque. Entre les
 * deux moitiés, le lanceur détruit les sessions côté Odoo. La seconde moitié
 * recharge cet état : le cookie est authentique, correctement scellé et non
 * expiré — seule la session Odoo a disparu.
 *
 * C'est le seul montage qui permette de tester cela depuis un vrai navigateur :
 * le conteneur Playwright n'a aucun accès à l'hôte Docker, et lui en donner un
 * pour les besoins d'un test serait un prix disproportionné.
 *
 * Budget : 1 tentative de connexion.
 */

import { expect, test } from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

test('capture une session valide sur disque', async ({ page }) => {
  const path = process.env.E2E_STATE_PATH;
  expect(path, 'E2E_STATE_PATH est requis').toBeTruthy();

  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');
  await expect(page.getByText(/E2E Contact A/i).first()).toBeVisible();

  await page.context().storageState({ path: path as string });
});
