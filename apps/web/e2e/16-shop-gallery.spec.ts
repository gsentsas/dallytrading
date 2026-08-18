/**
 * Les photos produit dans un vrai navigateur.
 *
 * ## Ce que seul un navigateur peut prouver
 *
 * Les tests Odoo prouvent que le bon octet sort du bon jeton ; les tests Vitest
 * prouvent que le balisage porte les bonnes adresses. Aucun des deux ne prouve
 * qu'un client **voit** la photo : ils n'exécutent ni le chargement des images,
 * ni le clic sur une vignette, ni le défilement tactile.
 *
 * Les assertions les plus fortes de ce fichier comparent des **octets** obtenus
 * par le navigateur, pas des URL. Une galerie qui changerait d'adresse sans
 * changer d'image passerait toute vérification portant sur le balisage.
 */

import { expect, test, type Page } from '@playwright/test';

function reference(nom: string): string {
  const valeur = process.env[nom];
  if (!valeur) throw new Error(`${nom} est requis (voir e2e-shop-seed.py).`);
  return valeur;
}

const PUBLIE = () => reference('SHOP_PUBLISHED_REF');
const NON_PUBLIE = () => reference('SHOP_UNPUBLISHED_REF');
const SANS_PHOTO = () => reference('SHOP_NO_IMAGE_REF');

/** Les `src` des images de la page, absolus. */
async function sources(page: Page, selecteur: string): Promise<string[]> {
  return page.locator(selecteur).evaluateAll((noeuds) =>
    noeuds.map((n) => (n as HTMLImageElement).src),
  );
}

/** Les octets réellement servis pour une adresse, vus par le navigateur. */
async function octets(page: Page, url: string): Promise<Buffer> {
  const reponse = await page.request.get(url);
  expect(reponse.status(), url).toBe(200);
  return reponse.body();
}

test.describe('catalogue', () => {
  test('la tuile affiche la photo principale et rien d’autre', async ({ page }) => {
    await page.goto('/boutique');

    const tuile = page.locator('article', { hasText: 'Groupe E2E 5 kVA' });
    const images = tuile.locator('img');
    await expect(images).toHaveCount(1);

    const src = await images.first().getAttribute('src');
    expect(src).toContain(`/api/shop/products/${PUBLIE()}/image`);
    expect(src).toContain('size=card');
    // La galerie n'est pas dans le contrat de la liste : aucune tuile ne doit
    // donc porter de photo de galerie, même par accident.
    expect(src).not.toContain('gallery=');
  });

  test('la photo se charge vraiment', async ({ page }) => {
    // `src` renseigné ne veut pas dire image affichée : une URL correcte
    // répondant 404 laisserait une case vide que rien d'autre ne signalerait.
    await page.goto('/boutique');
    const image = page
      .locator('article', { hasText: 'Groupe E2E 5 kVA' })
      .locator('img')
      .first();

    await expect(image).toBeVisible();
    const charge = await image.evaluate(
      (n) => (n as HTMLImageElement).complete && (n as HTMLImageElement).naturalWidth > 0,
    );
    expect(charge).toBe(true);
  });

  test('un produit sans photo affiche le substitut, sans requête', async ({ page }) => {
    await page.goto('/boutique');

    const tuile = page.locator('article', { hasText: 'Groupe E2E 12 kVA' });
    await expect(tuile.locator('img')).toHaveCount(0);
    await expect(tuile.locator('svg')).toHaveCount(1);
  });

  test('aucune adresse technique dans le document', async ({ page }) => {
    await page.goto('/boutique');
    const html = await page.content();

    // Contrôle positif : la page parle bien du produit.
    expect(html).toContain(PUBLIE());
    for (const interdit of ['/web/image', 'product.template', 'image_1920', 'model=', 'field=']) {
      expect(html, interdit).not.toContain(interdit);
    }
  });
});

test.describe('fiche produit', () => {
  test('montre la photo principale puis les trois photos de galerie', async ({ page }) => {
    await page.goto(`/boutique/${PUBLIE()}`);

    const grandes = await sources(page, '[data-testid="photo-produit"] img');
    expect(grandes).toHaveLength(4);

    // La principale d'abord, sans paramètre de galerie.
    expect(grandes[0]).not.toContain('gallery=');
    expect(grandes[0]).toContain('size=detail');
    // Puis trois photos de galerie, chacune avec son jeton.
    for (const src of grandes.slice(1)) {
      expect(src).toContain('gallery=');
    }
    expect(new Set(grandes).size).toBe(4);
  });

  test('les quatre photos sont réellement différentes', async ({ page }) => {
    // L'assertion qui compte. Quatre adresses distinctes servant quatre fois la
    // même image passeraient toutes les vérifications de balisage.
    await page.goto(`/boutique/${PUBLIE()}`);
    const grandes = await sources(page, '[data-testid="photo-produit"] img');

    // Séquentiel, et non `Promise.all`. Quatre requêtes simultanées saturent
    // l'Odoo de la pile jetable — un seul worker — et quelques appels
    // repartaient en erreur. Le navigateur, lui, ne charge jamais les quatre
    // d'un coup : les photos suivantes sont paresseuses. Paralléliser mesurait
    // donc la capacité du banc d'essai plutôt que le comportement du produit.
    const corps: Buffer[] = [];
    for (const src of grandes) {
      corps.push(await octets(page, src));
    }
    const distincts = new Set(corps.map((b) => b.toString('base64')));
    expect(distincts.size).toBe(4);
  });

  test('les octets servis sont bien des PNG', async ({ page }) => {
    await page.goto(`/boutique/${PUBLIE()}`);
    const [premier] = await sources(page, '[data-testid="photo-produit"] img');

    const reponse = await page.request.get(premier!);
    expect(reponse.headers()['content-type']).toBe('image/png');
    expect(reponse.headers()['x-content-type-options']).toBe('nosniff');
    // Signature binaire : le type annoncé correspond au contenu.
    expect((await reponse.body()).subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
  });

  test('l’image versionnée est déclarée immuable', async ({ page }) => {
    await page.goto(`/boutique/${PUBLIE()}`);
    const [premier] = await sources(page, '[data-testid="photo-produit"] img');

    const reponse = await page.request.get(premier!);
    const cache = reponse.headers()['cache-control'] ?? '';
    expect(cache).toContain('public');
    expect(cache).toContain('immutable');
  });

  test('cliquer une vignette change la photo affichée', async ({ page }) => {
    await page.goto(`/boutique/${PUBLIE()}`);

    const vignettes = page.locator('[data-testid="vignettes"] button');
    await expect(vignettes).toHaveCount(4);
    await expect(vignettes.nth(0)).toHaveAttribute('aria-current', 'true');

    await vignettes.nth(2).click();

    await expect(vignettes.nth(2)).toHaveAttribute('aria-current', 'true');
    await expect(vignettes.nth(0)).not.toHaveAttribute('aria-current', 'true');

    // La piste a réellement défilé jusqu'à la troisième photo : sans cette
    // assertion, une sélection purement visuelle passerait pour une navigation.
    //
    // `expect.poll` et non une lecture unique : le défilement est fluide, donc
    // étalé sur plusieurs images. Mesurer aussitôt après le clic lit une
    // position intermédiaire — ce qu'une première version de ce test a pris
    // pour un défaut du composant.
    const piste = page.locator('[data-testid="photo-produit"]').first().locator('..');
    await expect
      .poll(
        () =>
          piste.evaluate((n) =>
            Math.round(n.scrollLeft / Math.max(n.clientWidth, 1)),
          ),
        { timeout: 5000 },
      )
      .toBe(2);
  });

  test('les flèches avancent et bouclent', async ({ page }) => {
    await page.goto(`/boutique/${PUBLIE()}`);
    const vignettes = page.locator('[data-testid="vignettes"] button');

    await page.getByLabel('Photo suivante').click();
    await expect(vignettes.nth(1)).toHaveAttribute('aria-current', 'true');

    // Depuis la première, « précédente » ramène à la dernière : buter obligerait
    // à revenir en arrière quatre fois pour revoir la première.
    await page.getByLabel('Photo précédente').click();
    await page.getByLabel('Photo précédente').click();
    await expect(vignettes.nth(3)).toHaveAttribute('aria-current', 'true');
  });

  test('une fiche sans photo affiche le substitut', async ({ page }) => {
    await page.goto(`/boutique/${SANS_PHOTO()}`);

    await expect(page.locator('[data-testid="photo-produit"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="vignettes"]')).toHaveCount(0);
  });
});

test.describe('mobile', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('la galerie reste utilisable au doigt', async ({ page }) => {
    await page.goto(`/boutique/${PUBLIE()}`);

    // Les vignettes cèdent la place aux indicateurs : quatre vignettes de 80 px
    // ne tiennent pas sur 390 px de large.
    await expect(page.locator('[data-testid="indicateurs"]')).toBeVisible();
    const indicateurs = page.locator('[data-testid="indicateurs"] button');
    await expect(indicateurs).toHaveCount(4);
    await expect(indicateurs.nth(0)).toHaveAttribute('aria-current', 'true');

    await indicateurs.nth(1).click();
    await expect(indicateurs.nth(1)).toHaveAttribute('aria-current', 'true');
  });

  test('la piste défile horizontalement', async ({ page }) => {
    await page.goto(`/boutique/${PUBLIE()}`);
    const piste = page.locator('[data-testid="photo-produit"]').first().locator('..');

    const defilable = await piste.evaluate(
      (n) => n.scrollWidth > n.clientWidth + 10,
    );
    expect(defilable).toBe(true);
  });
});

test.describe('visibilité', () => {
  test('un produit non publié ne montre ni fiche ni photo', async ({ page }) => {
    const fiche = await page.request.get(`/boutique/${NON_PUBLIE()}`);
    expect(fiche.status()).toBe(404);

    const image = await page.request.get(
      `/api/shop/products/${NON_PUBLIE()}/image?size=card`,
    );
    expect(image.status()).toBe(404);
    expect(image.headers()['cache-control']).toBe('no-store');
  });

  test('un jeton de galerie ne franchit pas les produits', async ({ page }) => {
    // Le jeton est authentique et fonctionne sur son produit ; il ne doit rien
    // donner ailleurs. C'est la propriété que la comparaison côté serveur, aux
    // seules photos du produit demandé, garantit.
    await page.goto(`/boutique/${PUBLIE()}`);
    const grandes = await sources(page, '[data-testid="photo-produit"] img');
    const jeton = new URL(grandes[1]!).searchParams.get('gallery');
    expect(jeton).toBeTruthy();

    const surSonProduit = await page.request.get(
      `/api/shop/products/${PUBLIE()}/image?gallery=${jeton}&size=card`,
    );
    expect(surSonProduit.status(), 'contrôle positif').toBe(200);

    const ailleurs = await page.request.get(
      `/api/shop/products/${NON_PUBLIE()}/image?gallery=${jeton}&size=card`,
    );
    expect(ailleurs.status()).toBe(404);
  });

  test('un jeton inventé et un produit inconnu répondent pareil', async ({ page }) => {
    const inventeSurConnu = await page.request.get(
      `/api/shop/products/${PUBLIE()}/image?gallery=0000000000000000&size=card`,
    );
    const produitInconnu = await page.request.get(
      '/api/shop/products/slug-jamais-existe/image?size=card',
    );

    expect(inventeSurConnu.status()).toBe(404);
    expect(produitInconnu.status()).toBe(404);
    expect(await inventeSurConnu.body()).toEqual(await produitInconnu.body());
  });

  test('aucune clé d’API ne circule vers le navigateur', async ({ page }) => {
    const vues: string[] = [];
    page.on('request', (r) => vues.push(r.url()));
    await page.goto(`/boutique/${PUBLIE()}`);

    // Contrôle positif : des images ont bien été demandées.
    expect(vues.some((u) => u.includes('/api/shop/products/'))).toBe(true);
    for (const url of vues) {
      expect(url.toLowerCase()).not.toContain('api-key');
      expect(url.toLowerCase()).not.toContain('apikey');
      expect(url).not.toContain('/web/image');
    }
  });
});
