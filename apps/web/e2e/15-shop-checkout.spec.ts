/**
 * La boutique dans un vrai navigateur : catalogue → fiche → panier → commande.
 *
 * ## Pourquoi cette spec existe alors que tout est déjà mesuré ailleurs
 *
 * Les tests Odoo prouvent l'idempotence et la tarification, les tests Vitest
 * prouvent les contrats, les sondes HTTP prouvent les refus. Aucun des trois ne
 * prouve qu'un client peut **effectivement** commander : ils n'exécutent ni le
 * JavaScript du navigateur, ni le rendu réel des pages, ni la circulation des
 * cookies entre trois requêtes successives.
 *
 * Deux régressions du cycle véhicule sont nées exactement là — un contrat `.strict()`
 * qui refusait une clé nouvelle, un 422 sur un champ que l'ancien build n'envoyait
 * pas. Les deux étaient invisibles à tout ce qui n'était pas un navigateur.
 *
 * ## Sérialisé, et pourquoi
 *
 * `mode: 'serial'` : le panier vit dans un cookie, et le parcours est une suite
 * d'étapes qui se transmettent cet état. Les paralléliser ferait courir plusieurs
 * navigateurs sur le même compteur de limitation de débit du checkout — dix par
 * minute — et les échecs seraient des artefacts.
 */

import { expect, test } from '@playwright/test';

import { accounts, loginThroughUi } from './fixtures';

/** Références produites par la graine boutique. */
function reference(nom: string): string {
  const valeur = process.env[nom];
  if (!valeur) throw new Error(`${nom} est requis (voir e2e-shop-seed.py).`);
  return valeur;
}

const PUBLIE = () => reference('SHOP_PUBLISHED_REF');
const STOCK = () => reference('SHOP_STOCK_REF');
const NON_PUBLIE = () => reference('SHOP_UNPUBLISHED_REF');
const PRIX = () => reference('SHOP_PRICE');
const PRIX_LISTE = () => reference('SHOP_LIST_PRICE');
const CANARI_NOTE = () => reference('SHOP_CANARY_NOTE');
const CANARI_FOURNISSEUR = () => reference('SHOP_CANARY_SUPPLIER');
const EMAIL_CONNU = () => reference('SHOP_KNOWN_EMAIL');

const CART_COOKIE = 'dt_shop_cart';

/**
 * Le montant tel qu'il s'affiche.
 *
 * `Intl.NumberFormat('fr-FR')` sépare les milliers par U+202F, un espace
 * insécable étroit. Chercher une espace ordinaire produit un faux négatif — ce
 * qui est arrivé une fois, et a fait croire à un prix absent d'une page qui
 * l'affichait.
 */
function normaliser(texte: string): string {
  return texte.replace(/[  ]/g, ' ');
}

test.describe.configure({ mode: 'serial' });

test.describe('boutique — parcours invité', () => {
  test('le catalogue montre le publié et rien d’autre', async ({ page }) => {
    await page.goto('/boutique');
    const corps = normaliser(await page.locator('body').innerText());

    expect(corps).toContain('Groupe E2E 5 kVA');
    expect(corps).toContain('Groupe E2E 12 kVA');
    // Le non publié n'apparaît pas — et le publié ci-dessus rend cette absence
    // informative plutôt que le symptôme d'une page vide.
    expect(corps).not.toContain('Groupe E2E 30 kVA');

    // Le prix affiché est celui du tarif boutique, jamais le prix de liste.
    expect(corps).toContain('150 000');
    expect(corps).not.toContain('999 999');
  });

  test('la fiche d’un produit publié s’ouvre', async ({ page }) => {
    await page.goto(`/boutique/${PUBLIE()}`);
    const corps = normaliser(await page.locator('body').innerText());

    expect(corps).toContain('Groupe E2E 5 kVA');
    expect(corps).toContain('150 000');
    expect(corps).toContain('Sur commande');
    await expect(page.getByRole('button', { name: /Ajouter au panier/i })).toBeVisible();
  });

  test('un produit non publié donne la page 404, comme un slug inventé', async ({ page }) => {
    const nonPublie = await page.goto(`/boutique/${NON_PUBLIE()}`);
    expect(nonPublie?.status()).toBe(404);

    const invente = await page.goto('/boutique/e2e-slug-jamais-cree');
    expect(invente?.status()).toBe(404);

    // Le nom du produit non publié ne doit apparaître nulle part.
    await page.goto(`/boutique/${NON_PUBLIE()}`);
    expect(await page.content()).not.toContain('Groupe E2E 30 kVA');
  });

  test('ajouter au panier, puis commander', async ({ page, context }) => {
    await page.goto(`/boutique/${PUBLIE()}`);
    await page.getByLabel(/Quantité/i).fill('2');
    await page.getByRole('button', { name: /Ajouter au panier/i }).click();
    await expect(page.getByText(/Ajouté au panier/i)).toBeVisible();

    // Le cookie de panier est bien posé, et il est HttpOnly : le script de la
    // page ne peut pas le lire.
    const avant = (await context.cookies()).find((c) => c.name === CART_COOKIE);
    expect(avant).toBeTruthy();
    expect(avant?.httpOnly).toBe(true);
    expect(await page.evaluate(() => document.cookie)).not.toContain(CART_COOKIE);

    await page.goto('/boutique/panier');
    const panier = normaliser(await page.locator('body').innerText());
    expect(panier).toContain('Groupe E2E 5 kVA');
    expect(panier).toContain('300 000');
    expect(panier).toContain('Hors frais de livraison');

    await page.getByRole('link', { name: /Passer commande/i }).click();
    await expect(page).toHaveURL(/\/boutique\/commande$/);

    const commande = normaliser(await page.locator('body').innerText());
    expect(commande).toContain('Vos coordonnées');
    expect(commande).toContain('Retrait sur place');
    expect(commande).toContain('300 000');
    // Dit explicitement qu'aucun paiement n'est demandé : c'est une promesse que
    // le MVP doit tenir, et l'oublier de l'écran serait une attente créée à tort.
    expect(commande).toContain('Aucun paiement en ligne');

    await page.getByLabel(/^Nom complet/).fill('Invité Navigateur');
    await page.getByLabel(/^E-mail/).fill('invite.navigateur@e2e-shop.invalid');
    await page.getByLabel(/^Téléphone/).fill('+221 77 000 00 05');
    await page.getByLabel(/^Ville/).fill('Dakar');
    await page.getByRole('button', { name: /Valider ma commande/i }).click();

    await expect(page.getByTestId('order-reference')).toBeVisible();
    const referenceCommande = await page.getByTestId('order-reference').innerText();
    expect(referenceCommande).toMatch(/^S\d+$/);

    const confirmation = normaliser(await page.locator('body').innerText());
    expect(confirmation).toContain('Votre demande de commande est enregistrée');
    expect(confirmation).toContain('Aucun paiement n’a été demandé');

    // Le panier a tourné : nouveau cookie, et panier vide.
    const apres = (await context.cookies()).find((c) => c.name === CART_COOKIE);
    expect(apres?.value).not.toBe(avant?.value);
    await page.goto('/boutique/panier');
    expect(await page.locator('body').innerText()).toContain('Votre panier est vide');
  });

  test('une adresse déjà rattachée à un compte demande la connexion', async ({ page }) => {
    // Le cas d'usurpation : n'importe qui connaissant l'adresse d'un client
    // pourrait autrement faire atterrir une commande dans son dossier.
    await page.goto(`/boutique/${PUBLIE()}`);
    await page.getByRole('button', { name: /Ajouter au panier/i }).click();
    await expect(page.getByText(/Ajouté au panier/i)).toBeVisible();

    await page.goto('/boutique/commande');
    await page.getByLabel(/^Nom complet/).fill('Usurpateur');
    await page.getByLabel(/^E-mail/).fill(accounts.portalA.login());
    await page.getByRole('button', { name: /Valider ma commande/i }).click();

    await expect(page.getByText(/Un compte existe déjà avec cette adresse/i)).toBeVisible();
    await expect(page.getByRole('link', { name: /Se connecter/i })).toBeVisible();
    // Aucune commande : la confirmation n'apparaît pas.
    await expect(page.getByTestId('order-reference')).toHaveCount(0);
  });

  test('une adresse connue SANS compte crée une commande invité', async ({ page }) => {
    // Contrôle négatif du précédent : la règle porte sur l'existence d'un compte,
    // pas sur celle d'un contact. Sans ce test, « refuser les adresses connues »
    // passerait pour la bonne implémentation.
    await page.goto(`/boutique/${STOCK()}`);
    await page.getByRole('button', { name: /Ajouter au panier/i }).click();
    await expect(page.getByText(/Ajouté au panier/i)).toBeVisible();

    await page.goto('/boutique/commande');
    await page.getByLabel(/^Nom complet/).fill('Homonyme Invité');
    await page.getByLabel(/^E-mail/).fill(EMAIL_CONNU());
    await page.getByRole('button', { name: /Valider ma commande/i }).click();

    await expect(page.getByTestId('order-reference')).toBeVisible();
  });
});

test.describe('boutique — client connecté', () => {
  test('la commande est rattachée au compte, sans ressaisir son identité', async ({
    page,
  }) => {
    await loginThroughUi(page, accounts.portalA);
    await expect(page).toHaveURL(/\/espace-client/);

    await page.goto(`/boutique/${PUBLIE()}`);
    await page.getByLabel(/Quantité/i).fill('3');
    await page.getByRole('button', { name: /Ajouter au panier/i }).click();
    await expect(page.getByText(/Ajouté au panier/i)).toBeVisible();

    await page.goto('/boutique/commande');
    const commande = normaliser(await page.locator('body').innerText());

    // Aucun champ d'identité : elle vient de la session, lue par Odoo.
    await expect(page.getByLabel(/^Nom complet/)).toHaveCount(0);
    expect(commande).toContain('Cette commande sera rattachée à votre compte');
    expect(commande).toContain('450 000');

    // Le mode « livraison » est choisi ici, pour que les deux modes soient
    // exercés dans un navigateur et non seulement un seul.
    await page.getByRole('radio', { name: /Livraison/ }).check();
    await page.getByRole('button', { name: /Valider ma commande/i }).click();

    await expect(page.getByTestId('order-reference')).toBeVisible();
    const confirmation = normaliser(await page.locator('body').innerText());
    expect(confirmation).toContain('Livraison — tarif à confirmer');
    // Aucun tarif de livraison inventé.
    expect(confirmation).not.toMatch(/frais de livraison\s*:\s*\d/i);
  });
});

test.describe('boutique — canaris navigateur', () => {
  test('aucune donnée interne dans le HTML servi, ni dans le réseau', async ({ page }) => {
    const reponses: string[] = [];
    page.on('response', async (reponse) => {
      const type = reponse.headers()['content-type'] ?? '';
      if (!/json|html|javascript/.test(type)) return;
      try {
        reponses.push(await reponse.text());
      } catch {
        // Réponse déjà consommée ou redirigée : rien à balayer.
      }
    });

    await page.goto('/boutique');
    await page.goto(`/boutique/${PUBLIE()}`);
    await page.getByRole('button', { name: /Ajouter au panier/i }).click();
    await expect(page.getByText(/Ajouté au panier/i)).toBeVisible();
    await page.goto('/boutique/panier');
    await page.goto('/boutique/commande');

    // `page.content()` seul ne suffirait pas : il ne contient pas les réponses
    // JSON du BFF, qui sont précisément le chemin par lequel une projection trop
    // large fuirait.
    const corpus = reponses.join('\n') + (await page.content());

    // Contrôle positif : le corpus doit être substantiel, sinon les assertions
    // d'absence ne prouveraient rien.
    expect(corpus.length).toBeGreaterThan(10_000);
    expect(corpus).toContain('Groupe E2E 5 kVA');

    for (const canari of [
      CANARI_NOTE(),
      CANARI_FOURNISSEUR(),
      '424242',
      PRIX_LISTE().replace('.0', ''),
      'standard_price',
      'seller_ids',
      'pricelist_id',
      'partner_id',
      'price_unit',
      'cartId',
    ]) {
      expect(corpus, `« ${canari} » ne doit pas franchir la frontière`).not.toContain(
        canari,
      );
    }
  });

  test('le cookie de panier est illisible et inexploitable côté navigateur', async ({
    page,
    context,
  }) => {
    await page.goto(`/boutique/${PUBLIE()}`);
    await page.getByRole('button', { name: /Ajouter au panier/i }).click();
    await expect(page.getByText(/Ajouté au panier/i)).toBeVisible();

    const cookie = (await context.cookies()).find((c) => c.name === CART_COOKIE);
    expect(cookie).toBeTruthy();
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.sameSite).toBe('Lax');
    // Aucun `Domain=` élargi : le cookie ne doit pas partir vers crm.*.
    expect(cookie?.domain).toBe('127.0.0.1');

    // Le contenu est chiffré : ni la référence, ni un prix, ni le mot `quantity`.
    const valeur = cookie?.value ?? '';
    expect(valeur.startsWith('v1.')).toBe(true);
    expect(valeur).not.toContain(PUBLIE());
    expect(valeur).not.toContain(PRIX().replace('.0', ''));
    expect(valeur).not.toContain('quantity');
  });

  test('un cookie de panier altéré ne produit aucune commande', async ({
    page,
    context,
  }) => {
    await page.goto(`/boutique/${PUBLIE()}`);
    await page.getByRole('button', { name: /Ajouter au panier/i }).click();
    await expect(page.getByText(/Ajouté au panier/i)).toBeVisible();

    const cookie = (await context.cookies()).find((c) => c.name === CART_COOKIE);
    const morceaux = (cookie?.value ?? '').split('.');
    // Premier caractère du tag GCM, jamais le dernier : celui-ci ne porte que
    // deux bits utiles, et une substitution sur quatre laisserait le tag valide.
    const tag = morceaux[3] ?? '';
    morceaux[3] = (tag[0] === 'A' ? 'B' : 'A') + tag.slice(1);
    await context.addCookies([
      { ...cookie!, value: morceaux.join('.') },
    ]);

    // La page de commande renvoie au panier : il n'y a plus rien à commander.
    await page.goto('/boutique/commande');
    await expect(page).toHaveURL(/\/boutique\/(panier|commande)$/);
    const corps = await page.locator('body').innerText();
    expect(corps).toMatch(/panier est vide|n’est pas commandable/i);
    await expect(page.getByTestId('order-reference')).toHaveCount(0);
  });
});
