import { expect, test, type Page } from '@playwright/test';

/**
 * La symbiose CRM / tableur / facturation, du téléphone jusqu'à la base.
 *
 * Trois parcours, et un fil commun : **l'écran ne décide de rien**. Il affiche
 * ce qu'Odoo lui dit d'afficher, et n'ouvre que les gestes qu'Odoo autorise.
 *
 * ## Ce qui se joue ici et nulle part ailleurs
 *
 * L'ajout d'un article tardif ne peut pas s'éprouver dans un test unitaire du
 * navigateur : il faut une vraie facture comptabilisée, donc une vraie
 * séquence comptable, et un serveur qui refuse le chemin ordinaire. Le
 * parcours passe donc par le formulaire réel, la vraie route, la vraie base.
 */

const GILLES = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};
const RESPONSABLE = {
  login: process.env.OPS_E2E_RESPONSABLE_LOGIN ?? 'responsable.banc',
  password: process.env.OPS_E2E_RESPONSABLE_PASSWORD ?? 'banc-responsable-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT = '+221 77 123 45 67';

async function seConnecter(page: Page, compte: { login: string; password: string }) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(compte.login);
  await page.getByLabel('Mot de passe').fill(compte.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByRole('heading', { name: /^Bonjour / })).toBeVisible();
}

async function remplirArticle(
  page: Page, { designation, poids }: { designation: string; poids: string },
) {
  await page.getByLabel('Catégorie').fill('Non alimentaire');
  await page.getByLabel('Désignation').fill(designation);
  await page.getByLabel('Quantité').fill('1');
  await page.getByLabel('Poids exact total (kg)').fill(poids);
  await page.getByLabel('Famille tarifaire').selectOption('non_food');
  await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');
}

/** Un dossier neuf, d'un article, et sa référence. */
async function creerUnDossier(page: Page, designation: string): Promise<string> {
  await page.goto('/reception');
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await page.getByLabel('Numéro de téléphone').fill(CLIENT);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toBeVisible();
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();

  await remplirArticle(page, { designation, poids: '3.55' });
  await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
  await expect(page.getByTestId('intake-enregistre')).toBeVisible();
  const reference = await page.getByTestId('intake-enregistre')
    .locator('.reference').textContent();
  return (reference ?? '').trim();
}

// ---------------------------------------------------------------------
// L'ajout d'un article arrivé après la facture
// ---------------------------------------------------------------------

test('un dossier non facturé n’ouvre pas le geste tardif', async ({ page }) => {
  // Le contre-test du parcours suivant. Sans lui, un bouton toujours présent
  // passerait pour une autorisation correctement lue.
  await seConnecter(page, GILLES);
  const reference = await creerUnDossier(page, 'Savon symbiose');

  await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
  await expect(page.getByRole('button', { name: '+ AJOUTER UN ARTICLE' })).toBeVisible();
  await expect(page.getByTestId('ajout-tardif')).toHaveCount(0);
});

test('l’écran affiche l’état CRM / tableur / facturation du dossier', async ({ page }) => {
  await seConnecter(page, GILLES);
  const reference = await creerUnDossier(page, 'Pagne symbiose');

  await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
  const sync = page.getByTestId('synchronisation-dossier');
  await expect(sync).toBeVisible();
  await expect(sync.getByTestId('etat-crm')).toContainText('Enregistré');
  // Le tableur a son propre état, et il n'est pas déduit du CRM.
  await expect(sync.getByTestId('etat-tableur')).toBeVisible();
  // Aucun identifiant Odoo ne descend : le contrat strict le refuserait, et
  // l'écran ne le fabriquerait pas non plus.
  await expect(sync).not.toContainText('invoice_id');
});

// ---------------------------------------------------------------------
// « À traiter » — une vue de supervision
// ---------------------------------------------------------------------

test('un logisticien ne voit ni l’entrée « À traiter » ni la page', async ({ page }) => {
  await seConnecter(page, GILLES);
  await expect(page.getByRole('link', { name: /À traiter/ })).toHaveCount(0);

  // Et la protection ne tient pas qu'à l'entrée cachée : la page elle-même
  // refuse. Cacher n'est pas protéger.
  await page.goto('/traitement');
  await expect(page.getByTestId('refus-supervision')).toBeVisible();
  await expect(page.getByTestId('anomalie')).toHaveCount(0);
});

test('le responsable ouvre « À traiter » depuis l’accueil', async ({ page }) => {
  await seConnecter(page, RESPONSABLE);
  await page.getByRole('link', { name: /À traiter/ }).click();

  await expect(page.getByRole('heading', { name: 'À TRAITER' })).toBeVisible();
  await expect(page.getByTestId('refus-supervision')).toHaveCount(0);
  // La liste peut être vide sur un banc propre : c'est un état, pas une panne.
  await expect(page.getByTestId('anomalies-indisponibles')).toHaveCount(0);
});

// ---------------------------------------------------------------------
// La synchronisation, en deux moitiés qui ne se mélangent pas
// ---------------------------------------------------------------------

test('la synchronisation sépare l’appareil du tableur', async ({ page }) => {
  await seConnecter(page, RESPONSABLE);
  await page.goto('/synchronisation');

  await expect(page.getByRole('heading', { name: 'APPAREIL → CRM' })).toBeVisible();
  const tableur = page.getByTestId('projection-tableur');
  await expect(tableur).toBeVisible();
  await expect(tableur.getByRole('heading', { name: 'CRM → TABLEUR' })).toBeVisible();
  // Le message vient du serveur ; l'écran ne le compose pas.
  await expect(tableur.getByTestId('projection-message')).toBeVisible();
  // Et jamais l'erreur de transport brute.
  await expect(tableur).not.toContainText('script.google.com');
});

test('la file de l’appareil reste lisible sans la moitié serveur', async ({ page }) => {
  // La page doit s'ouvrir sans réseau — c'est sa raison d'être. On coupe donc
  // la seule dépendance serveur qu'elle a acquise et on vérifie que la
  // première moitié tient toujours.
  await seConnecter(page, GILLES);
  await page.route('**/api/sheet-sync', (route) => route.abort());
  await page.goto('/synchronisation');

  await expect(page.getByRole('heading', { name: 'SYNCHRONISATION' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'APPAREIL → CRM' })).toBeVisible();
  await expect(page.getByTestId('projection-tableur')).toHaveCount(0);
});

test('un logisticien ne reçoit pas la moitié tableur', async ({ page }) => {
  await seConnecter(page, GILLES);
  await page.goto('/synchronisation');

  await expect(page.getByRole('heading', { name: 'APPAREIL → CRM' })).toBeVisible();
  // Le serveur refuse ; la section disparaît plutôt que d'afficher un refus
  // sur un écran qu'on ouvre justement pour savoir si le réseau marche.
  await expect(page.getByTestId('projection-tableur')).toHaveCount(0);
});

// ---------------------------------------------------------------------
// Le parcours complet de l'ajout tardif
// ---------------------------------------------------------------------

/**
 * Le décor — une facture réellement comptabilisée — se pose côté Odoo, par
 * `scripts/seed_ops_late_line_e2e.py` : l'application ne sait pas émettre
 * une pièce comptable, et c'est voulu.
 *
 * Sans la variable, le parcours se déclare ignoré. Le remplacer par un test
 * qui passerait sans décor prétendrait couvrir ce qu'il ne couvre pas.
 */
const REFERENCE_FACTUREE = process.env.OPS_E2E_LATE_REFERENCE;

test('un article arrivé après la facture entre sans la toucher', async ({ page }) => {
  test.skip(
    !REFERENCE_FACTUREE,
    'OPS_E2E_LATE_REFERENCE absente : lancez scripts/seed_ops_late_line_e2e.py',
  );
  await seConnecter(page, GILLES);
  await page.goto(`/reception/dossier/${encodeURIComponent(REFERENCE_FACTUREE!)}`);

  // Le dossier est verrouillé : l'ajout ordinaire est fermé…
  await expect(page.getByTestId('blocage')).toContainText('déjà engagé dans la facturation');
  await expect(page.getByRole('button', { name: '+ AJOUTER UN ARTICLE', exact: true }))
    .toHaveCount(0);
  // …et pourtant le geste tardif est ouvert, parce que le serveur l'autorise.
  await expect(page.getByTestId('ajout-tardif')).toBeVisible();

  const facture = page.getByTestId('etat-facturation');
  await expect(facture).toContainText('Comptabilisée');
  const montantAvant = await facture.textContent();

  // Une désignation propre à ce passage : le décor est réutilisé d'une
  // exécution à l'autre, et un libellé fixe finirait par désigner deux
  // articles — le test deviendrait ambigu plutôt que faux, ce qui est pire.
  const designation = `Crème tardive ${Date.now().toString(36)}`;
  await page.getByRole('button', { name: '+ AJOUTER UN ARTICLE TARDIF' }).click();
  await remplirArticle(page, { designation, poids: '1' });
  await page.getByRole('button', { name: 'ENREGISTRER L’ARTICLE TARDIF' }).click();

  // L'article est là…
  await expect(page.getByTestId('article').filter({ hasText: designation }))
    .toBeVisible();
  // …la facture principale n'a pas bougé…
  await expect(page.getByTestId('etat-facturation')).toContainText('Comptabilisée');
  expect(await page.getByTestId('etat-facturation').textContent()).toBe(montantAvant);
  // …et le montant non facturé est annoncé par le serveur.
  await expect(page.getByTestId('articles-non-factures')).toBeVisible();
  await expect(page.getByTestId('articles-non-factures'))
    .toContainText(/\d+ articles? non facturés?/);
});

test('le responsable retrouve ce colis dans « À traiter »', async ({ page }) => {
  test.skip(!REFERENCE_FACTUREE, 'OPS_E2E_LATE_REFERENCE absente');
  await seConnecter(page, RESPONSABLE);
  await page.goto('/traitement');

  // L'anomalie est calculée par Odoo depuis la facturation, pas déduite ici.
  const anomalie = page.locator('[data-type="UNBILLED_PACKAGE"]')
    .filter({ hasText: REFERENCE_FACTUREE! });
  await expect(anomalie).toBeVisible();
  await expect(anomalie.getByRole('link', { name: 'OUVRIR LE DOSSIER' })).toBeVisible();
});
