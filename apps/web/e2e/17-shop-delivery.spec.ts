import { expect, test } from '@playwright/test';

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} est requis.`);
  return value;
}

const PUBLISHED = () => required('SHOP_PUBLISHED_REF');

function normalize(text: string): string {
  return text.replace(/[  ]/g, ' ');
}

test.describe.configure({ mode: 'serial' });

test.describe('boutique — livraison Lot C', () => {
  test('les méthodes Odoo sont rendues et une adresse distincte traverse le vrai checkout', async ({ page }) => {
    await page.goto(`/boutique/${PUBLISHED()}`);
    await page.getByRole('button', { name: /Ajouter au panier/i }).click();
    await expect(page.getByText(/Ajouté au panier/i)).toBeVisible();

    await page.goto('/boutique/commande');
    const initial = normalize(await page.locator('body').innerText());

    // Deux méthodes de référence créées côté Odoo. Le navigateur ne possède
    // aucune table codée en dur : leur présence prouve le trajet API réel.
    expect(initial).toContain('Retrait sur place');
    expect(initial).toContain('Livraison');
    expect(initial).toContain('Tarif à confirmer');

    await page.getByLabel(/^Nom complet/).fill('Invité Livraison Lot C');
    await page.getByLabel(/^E-mail/).fill('invite.livraison.lotc@e2e-shop.invalid');
    await page.getByRole('radio', { name: /Livraison/ }).check();

    await expect(page.getByText(/Adresse de livraison/i)).toBeVisible();
    await page.getByLabel(/Livrer à une autre adresse/i).check();
    await page.getByLabel(/^Destinataire/).fill('Dépôt Lot C');
    await page.getByLabel(/^Adresse \*/).fill('10 avenue du Port');
    await page.getByLabel(/^Ville \*/).fill('Dakar');
    // Le pays est volontairement laissé vide : il est facultatif et le contrat
    // doit transformer la chaîne vide du formulaire en absence, pas en 422.

    await page.getByRole('button', { name: /Valider ma commande/i }).click();

    await expect(page.getByTestId('order-reference')).toBeVisible();
    const confirmation = normalize(await page.locator('body').innerText());
    expect(confirmation).toContain('Livraison');
    expect(confirmation).toContain('Tarif à confirmer');
    expect(confirmation).toContain('Aucun paiement n’a été demandé');

    // Aucun montant de livraison inventé avant la cotation Odoo.
    expect(confirmation).not.toMatch(/frais de remise\s*:\s*[0-9]/i);
  });
});
