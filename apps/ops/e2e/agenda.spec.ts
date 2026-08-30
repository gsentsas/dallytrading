import { expect, test, type Page } from '@playwright/test';

const OPERATOR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};
const CUSTOMER_PHONE = '+221 77 123 45 67';
const CUSTOMER_NAME = 'Aissatou Kandji';
const CONSOLIDATION = 'AIR-DSS-CDG-TEST-001';

async function login(page: Page) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(OPERATOR.login);
  await page.getByLabel('Mot de passe').fill(OPERATOR.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
}

async function openNewAppointment(page: Page) {
  await page.getByRole('link', { name: /Agenda/ }).click();
  await expect(page.getByRole('heading', { name: 'AGENDA' })).toBeVisible();
  await page.getByRole('button', { name: '+ NOUVEAU RENDEZ-VOUS' }).click();
  await page.getByLabel('Numéro de téléphone').fill(CUSTOMER_PHONE);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toContainText(CUSTOMER_NAME);
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();
  await expect(page.getByRole('heading', { name: 'NOUVEAU RENDEZ-VOUS' })).toBeVisible();
}

async function createAppointment(page: Page, note: string) {
  await openNewAppointment(page);
  await page.getByLabel('Type de rendez-vous').selectOption('dropoff');
  await page.getByLabel('Date et heure').fill('2026-08-31T10:00');
  await page.getByLabel('Durée').selectOption('30');
  await page.getByLabel('Départ').selectOption(CONSOLIDATION);
  await page.getByLabel('Lieu').fill('Dépôt Dakar');
  await page.getByLabel('Note').fill(note);
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith('/api/appointments')
    && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'ENREGISTRER LE RENDEZ-VOUS' }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const body = await response.json() as { data: { appointment: { reference: string } } };
  await expect(page.getByRole('heading', { name: CUSTOMER_NAME.toUpperCase() })).toBeVisible();
  return body.data.appointment.reference;
}

test('un rendez-vous présent préremplit puis crée une réception Freight', async ({ page }) => {
  const requestedUrls: string[] = [];
  page.on('request', (request) => requestedUrls.push(request.url()));
  await login(page);
  const marker = `Agenda E2E réception ${Date.now()}`;
  await createAppointment(page, marker);

  const call = page.getByRole('link', { name: 'APPELER' });
  const whatsapp = page.getByRole('link', { name: 'WHATSAPP' });
  await expect(call).toHaveAttribute('href', /^tel:\+?\d+$/);
  await expect(whatsapp).toHaveAttribute('href', /^https:\/\/wa\.me\/\d+$/);

  await page.getByRole('button', { name: 'CLIENT PRÉSENT' }).click();
  await expect(page.getByText('✓ CLIENT PRÉSENT')).toBeVisible();

  const intakeCallsBefore = requestedUrls.filter((url) => url.endsWith('/api/intakes')).length;
  await page.getByRole('button', { name: 'RÉCEPTIONNER LE COLIS' }).click();
  await expect(page).toHaveURL(/\/reception\/colis\/preparee$/);
  await expect(page.getByTestId('client-selectionne')).toHaveText(CUSTOMER_NAME);
  await expect(page.getByTestId('consolidation-selectionnee')).toHaveText(CONSOLIDATION);
  await expect(page.getByLabel('Désignation')).toBeVisible();
  expect(requestedUrls.filter((url) => url.endsWith('/api/intakes')).length)
    .toBe(intakeCallsBefore);
  expect(page.url()).not.toContain('customer');
  expect(page.url()).not.toContain('partner');

  await page.getByLabel('Catégorie').fill('Non alimentaire');
  await page.getByLabel('Désignation').fill(marker);
  await page.getByLabel('Quantité').fill('1');
  await page.getByLabel('Poids exact total (kg)').fill('13.5');
  await page.getByLabel('Famille tarifaire').selectOption('non_food');
  await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');
  await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
  await expect(page.getByTestId('intake-enregistre')).toBeVisible();
  await expect(page.getByTestId('intake-enregistre').locator('.reference'))
    .toContainText(`${CONSOLIDATION}-A`);
});

test('un rendez-vous absent est reporté en une nouvelle occurrence', async ({ page }) => {
  await login(page);
  const oldReference = await createAppointment(
    page, `Agenda E2E report ${Date.now()}`);
  await page.getByRole('button', { name: 'CLIENT ABSENT' }).click();
  await expect(page.getByText('ABSENT', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'REPORTER LE RENDEZ-VOUS' }).click();
  await page.getByLabel('Nouvelle date et heure').fill('2026-09-01T15:00');
  await page.getByLabel('Nouvelle durée').selectOption('30');
  const reportPromise = page.waitForResponse((response) =>
    response.url().includes('/reschedule') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'CONFIRMER LE REPORT' }).click();
  const report = await reportPromise;
  expect(report.status()).toBe(200);
  const reportBody = await report.json() as {
    data: { appointment: { reference: string; status: string } };
  };
  expect(reportBody.data.appointment.reference).not.toBe(oldReference);
  expect(reportBody.data.appointment.status).toBe('scheduled');
  await expect(page.getByText('Prévu', { exact: true })).toBeVisible();

  const old = await page.request.get(
    `/api/appointments/${encodeURIComponent(oldReference)}`);
  expect(old.status()).toBe(200);
  expect((await old.json()).data.status).toBe('rescheduled');
});
