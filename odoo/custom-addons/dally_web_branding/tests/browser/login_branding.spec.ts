import { expect, test, type Page } from '@playwright/test';

const LOGIN = process.env.BRANDING_LOGIN;
const PASSWORD = process.env.BRANDING_PASSWORD;
const SCREENSHOT_DIR = process.env.BRANDING_SCREENSHOT_DIR || '/tmp/dally-branding-shots';

if (!LOGIN || !PASSWORD) {
  throw new Error('BRANDING_LOGIN et BRANDING_PASSWORD sont requis.');
}

async function login(page: Page) {
  await page.goto('/web/login', { waitUntil: 'domcontentloaded' });
  await page.locator('input[name="login"]').fill(LOGIN!);
  await page.locator('input[name="password"]').fill(PASSWORD!);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/(odoo|web)(\?|$)/, { timeout: 30000 });
}

const viewports = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1024', width: 1024, height: 768 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'mobile-390', width: 390, height: 844 },
] as const;

for (const viewport of viewports) {
  test(`login responsive ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto('/web/login', { waitUntil: 'domcontentloaded' });

    await expect(page).toHaveTitle('DallyTrading CRM');
    await expect(page.locator('.dally-auth-shell')).toBeVisible();
    await expect(page.locator('form.oe_login_form')).toBeVisible();
    await expect(
      page.getByRole('button', { name: /^(Log in|Se connecter)$/i }),
    ).toBeVisible();
    await expect(page.locator('header, footer')).toHaveCount(0);
    await expect(page.getByText(/Powered by Odoo|Généré par Odoo/i)).toHaveCount(0);

    const metrics = await page.evaluate(() => ({
      viewport: window.innerWidth,
      document: document.documentElement.scrollWidth,
      formTop: document.querySelector('form.oe_login_form')?.getBoundingClientRect().top,
      brandWidth: document.querySelector('.dally-auth-brand')?.getBoundingClientRect().width,
    }));
    expect(metrics.document).toBeLessThanOrEqual(metrics.viewport);
    if (viewport.width >= 900) {
      expect(metrics.brandWidth).toBeDefined();
      expect(metrics.brandWidth! / metrics.viewport).toBeCloseTo(0.56, 2);
    }
    if (viewport.width === 390) {
      expect(metrics.formTop).toBeDefined();
      expect(metrics.formTop!).toBeLessThan(viewport.height * 0.6);
    }

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/after-${viewport.name}.png`,
      fullPage: true,
    });
  });
}

test('mode debug assets conserve la page de connexion', async ({ page }) => {
  await page.goto('/web/login?debug=assets', { waitUntil: 'domcontentloaded' });
  await expect(page).toHaveTitle('DallyTrading CRM');
  await expect(page.locator('.dally-auth-shell')).toBeVisible();
  await expect(page.locator('form.oe_login_form')).toBeVisible();
  await expect(page.locator('link[href*="/debug/web.assets_frontend.css"]')).toHaveCount(1);
});

test('erreur de connexion visible', async ({ page }) => {
  await page.goto('/web/login', { waitUntil: 'domcontentloaded' });
  await page.locator('input[name="login"]').fill('invalid@test.invalid');
  await page.locator('input[name="password"]').fill('wrong-password');
  await page.locator('button[type="submit"]').click();
  await expect(page.locator('.alert-danger')).toBeVisible();
  await expect(page.locator('.dally-auth-shell')).toBeVisible();
});

test('reset, inscription et passkey restent accessibles', async ({ page }) => {
  await page.goto('/web/login', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('a[href^="/web/reset_password"]')).toBeVisible();
  await expect(page.locator('a[href^="/web/signup"]')).toBeVisible();
  await expect(page.locator('.passkey_login_link')).toBeVisible();

  await page.goto('/web/reset_password', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('form.oe_reset_password_form')).toBeVisible();
  await expect(page.locator('.dally-auth-shell')).toBeVisible();

  await page.goto('/web/signup', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('form.oe_signup_form')).toBeVisible();
  await expect(page.locator('.dally-auth-shell')).toBeVisible();
});

test('connexion, backend puis deconnexion', async ({ page }) => {
  await login(page);
  await expect(page.locator('.o_web_client')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('.dally-auth-shell')).toHaveCount(0);

  await page.goto('/web/session/logout?redirect=/web/login', {
    waitUntil: 'domcontentloaded',
  });
  await expect(page).toHaveURL(/\/web\/login/);
  await expect(page.locator('.dally-auth-shell')).toBeVisible();
});
