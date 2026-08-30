'use strict';
/*
 * La projection CRM → classeur, éprouvée hors de Google.
 *
 * Ce harnais charge le code réel d'`Outbox.gs` (ainsi que les constantes et
 * les aides de `Code.gs` / `Cash.gs`) dans un contexte Node, avec un onglet
 * simulé. Il vérifie la seule propriété qui compte pour une projection : la
 * rejouer ne crée pas de ligne.
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const racine = path.join(__dirname, '..', 'integrations', 'google-sheets', 'freight-sync');
const lire = nom => fs.readFileSync(path.join(racine, nom), 'utf8');

/* --- Un onglet simulé, à la sémantique de Google ------------------- */

function fauxOnglet(nom, colonnes, onWrite) {
  const cellules = new Map();
  const cle = (row, col) => row + ':' + col;
  let dernier = 0;
  return {
    nom,
    colonnes,
    getLastRow: () => dernier,
    getRange(row, col) {
      return {
        getDisplayValue() {
          const v = cellules.get(cle(row, col));
          return v == null ? '' : String(v);
        },
        setValue(value) {
          cellules.set(cle(row, col), value);
          if (row > dernier) dernier = row;
          if (onWrite) onWrite({sheet: nom, row, col, value});
        },
      };
    },
    lignes() {
      const vues = new Set();
      for (const k of cellules.keys()) vues.add(Number(k.split(':')[0]));
      return [...vues].sort((a, b) => a - b);
    },
    valeur(row, col) {
      const v = cellules.get(cle(row, col));
      return v == null ? '' : v;
    },
  };
}

function fauxClasseur(onglets) {
  return {getSheetByName: nom => onglets[nom] || null};
}

/* --- Le contexte : le vrai code, sans Google ---------------------- */

/** Rend visibles sur l'objet global les constantes déclarées en `const`. */
function global_(source) {
  return source.replace(/^const (DALLY|DALLY_CASH|DALLY_OUTBOX) = /gm, 'var $1 = ');
}

function contexte(options) {
  const opts = options || {};
  const sandbox = {
    console,
    Date,
    Math,
    Object,
    String,
    Number,
    Set,
    Map,
    Utilities: {formatDate: () => '2026-08-30'},
    SpreadsheetApp: {getActive: opts.getActive || (() => null)},
    LockService: {getScriptLock: () => ({tryLock: () => true, releaseLock() {}})},
    withScriptLock_: fn => fn(),
    readConfig_: () => ({apiBaseUrl: 'https://odoo.invalid'}),
    apiGet_: opts.apiGet || (() => ({projections: []})),
    apiPost_: opts.apiPost || (() => ({})),
  };
  vm.createContext(sandbox);
  // Seules les parties utiles de `Code.gs` sont chargées : la constante DALLY,
  // la neutralisation de formule et la préservation du message de replan.
  const code = lire('Code.gs');
  const extraits = [
    code.slice(code.indexOf('const DALLY = Object.freeze('), code.indexOf('function onOpen()')),
    code.slice(code.indexOf('function preserveReplanIntentMessage_'),
               code.indexOf('function dirtyDossiers_')),
    code.slice(code.indexOf('function hasReplanIntentText_'),
               code.indexOf('function hasExplicitReplanIntent_')),
    code.slice(code.indexOf('function sheetLiteralText_'),
               code.indexOf('function value_(row, column)')),
    'function errorText_(err) { return err && err.message ? err.message : String(err); }',
  ].join('\n');
  // `const` au niveau d'un module n'apparaît pas sur l'objet global du
  // contexte : on le convertit pour que le harnais puisse lire DALLY et
  // DALLY_CASH sans dupliquer leur définition.
  vm.runInContext(global_(extraits), sandbox);
  const cash = lire('Cash.gs');
  vm.runInContext(global_(
    cash.slice(cash.indexOf('const DALLY_CASH = Object.freeze('),
               cash.indexOf('function dallyCashSetup()'))), sandbox);
  vm.runInContext(global_(lire('Outbox.gs')), sandbox);
  return sandbox;
}

const ctx = contexte();
const C = ctx.DALLY.columns;
const DALLY_CASH_EXPENSE = ctx.DALLY_CASH.expense;
const DALLY_CASH_TRANSFER = ctx.DALLY_CASH.transfer;

/* --- Projections de référence ------------------------------------- */

function projectionDossier(surcharge) {
  const base = {
    projection_type: 'freight_dossier',
    outbox_id: 1,
    business_key: 'ops:uuid-1',
    sheet: 'Saisie aérien',
    identity: {
      sync_source_key: 'ops:uuid-1',
      global_external_reference: 'AIR-DSS-CDG-2026-002-A001',
      intake_consolidation_ref: 'AIR-DSS-CDG-2026-002',
      collection_local_ref: 'A001',
      shipment_id: 4242, partner_id: 77, sale_order_id: 0,
      invoice_id: 0, invoice_number: '',
    },
    dossier: {
      planned_consolidation: 'AIR-DSS-CDG-2026-002', reference: 'A001',
      deposit_date: '2026-08-29', state: 'goods_received',
      customer: {name: 'Aissatou Kandji', phone: '+221770000001',
                 email: 'a@example.test', address: 'Dakar'},
    },
    articles: [{
      article_key: 'AIR-DSS-CDG-2026-002-A001|A|1',
      goods_category: 'Non alimentaire', description: 'Savon', quantity: 1,
      length_cm: 0, width_cm: 0, height_cm: 0, unit_volume_cbm: 0,
      total_volume_cbm: 0, announced_weight_kg: 0, exact_weight_kg: 13.5,
      billable_weight_kg: 13.5, billing_method: 'real',
      applied_unit_price_eur: 5, transport_amount_eur: 67.5,
      tariff_family_code: 'non_food', customs_value_xof: 25000,
    }],
    payments: [],
  };
  return Object.assign(base, surcharge || {});
}

function nouveauClasseur(onWrite) {
  return {
    'Saisie aérien': fauxOnglet('Saisie aérien', 63, onWrite),
    'Saisie maritime': fauxOnglet('Saisie maritime', 63, onWrite),
    'Dépenses': fauxOnglet('Dépenses', 20, onWrite),
    'Transferts caisse': fauxOnglet('Transferts caisse', 16, onWrite),
  };
}

/* --- 1. Une projection neuve ajoute exactement une ligne ----------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const lignes = ctx.applyDossierProjection_(classeur, projectionDossier());
  assert.strictEqual(lignes.length, 1, 'une ligne par article');
  const aerien = onglets['Saisie aérien'];
  assert.strictEqual(aerien.lignes().length, 1, 'exactement une ligne écrite');
  assert.strictEqual(aerien.valeur(lignes[0], C.dossier), 'A001');
  assert.strictEqual(aerien.valeur(lignes[0], C.tariffFamily), 'Non alimentaire');
  assert.strictEqual(aerien.valeur(lignes[0], C.customsValue), 25000);
  assert.strictEqual(aerien.valeur(lignes[0], C.globalExternalReference),
                     'AIR-DSS-CDG-2026-002-A001');
  // Rien n'a été écrit dans l'onglet maritime.
  assert.strictEqual(onglets['Saisie maritime'].lignes().length, 0);
}

/* --- 2. Rejouer la même projection n'ajoute aucune ligne ----------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  ctx.applyDossierProjection_(classeur, projectionDossier());
  const avant = onglets['Saisie aérien'].lignes().length;
  ctx.applyDossierProjection_(classeur, projectionDossier());
  ctx.applyDossierProjection_(classeur, projectionDossier());
  assert.strictEqual(onglets['Saisie aérien'].lignes().length, avant,
                     'un rejeu ne doit ajouter aucune ligne');
}

/* --- 3. Une projection modifiée met à jour la même ligne ----------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const [ligne] = ctx.applyDossierProjection_(classeur, projectionDossier());
  const modifiee = projectionDossier();
  modifiee.articles[0].description = 'Savon corrigé';
  modifiee.articles[0].exact_weight_kg = 14.5;
  const [encore] = ctx.applyDossierProjection_(classeur, modifiee);
  assert.strictEqual(encore, ligne, 'la même ligne doit être réutilisée');
  assert.strictEqual(onglets['Saisie aérien'].valeur(ligne, C.description),
                     'Savon corrigé');
  assert.strictEqual(onglets['Saisie aérien'].valeur(ligne, C.exactWeight), 14.5);
  assert.strictEqual(onglets['Saisie aérien'].lignes().length, 1);
}

/* --- 4. Trois articles : trois lignes, et toujours trois ---------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const p = projectionDossier();
  p.articles = [1, 2, 3].map(n => Object.assign({}, p.articles[0], {
    article_key: 'AIR-DSS-CDG-2026-002-A001|A|' + n,
    description: 'Article ' + n,
  }));
  assert.strictEqual(ctx.applyDossierProjection_(classeur, p).length, 3);
  assert.strictEqual(onglets['Saisie aérien'].lignes().length, 3);
  ctx.applyDossierProjection_(classeur, p);
  assert.strictEqual(onglets['Saisie aérien'].lignes().length, 3,
                     'un rejeu multi-articles reste à trois lignes');
}

/* --- 5. Deux A001 de départs différents ne se confondent pas ------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const premier = projectionDossier();
  const second = projectionDossier();
  second.business_key = 'ops:uuid-2';
  second.identity = Object.assign({}, second.identity, {
    sync_source_key: 'ops:uuid-2',
    global_external_reference: 'AIR-DSS-CDG-2026-003-A001',
    intake_consolidation_ref: 'AIR-DSS-CDG-2026-003',
    shipment_id: 4343,
  });
  second.dossier = Object.assign({}, second.dossier, {
    planned_consolidation: 'AIR-DSS-CDG-2026-003',
  });
  second.articles = [Object.assign({}, second.articles[0], {
    article_key: 'AIR-DSS-CDG-2026-003-A001|A|1',
  })];

  ctx.applyDossierProjection_(classeur, premier);
  ctx.applyDossierProjection_(classeur, second);
  const aerien = onglets['Saisie aérien'];
  assert.strictEqual(aerien.lignes().length, 2, 'deux dossiers, deux lignes');
  const globales = aerien.lignes().map(r => aerien.valeur(r, C.globalExternalReference));
  assert.strictEqual(new Set(globales).size, 2, 'références globales distinctes');
}

/* --- 6. Un dossier maritime ne touche jamais l'onglet aérien ------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const p = projectionDossier({sheet: 'Saisie maritime'});
  ctx.applyDossierProjection_(classeur, p);
  assert.strictEqual(onglets['Saisie maritime'].lignes().length, 1);
  assert.strictEqual(onglets['Saisie aérien'].lignes().length, 0);
}

/* --- 7. Les cinq familles traversent, l'inconnue est refusée ------- */
{
  for (const [code, libelle] of Object.entries({
    food: 'Alimentaire standard', seafood: 'Halieutiques', honey: 'Miel',
    clothing: 'Habits / Vêtements', non_food: 'Non alimentaire',
  })) {
    assert.strictEqual(ctx.tariffFamilyLabel_(code), libelle);
  }
  assert.throws(() => ctx.tariffFamilyLabel_('inconnue'), /Famille tarifaire inconnue/);
  assert.throws(() => ctx.tariffFamilyLabel_(''), /Famille tarifaire inconnue/);
}

/* --- 8. Le numéro de facture met à jour la ligne, sans en créer ---- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const [ligne] = ctx.applyDossierProjection_(classeur, projectionDossier());
  const facturee = projectionDossier();
  facturee.identity = Object.assign({}, facturee.identity, {
    invoice_id: 909, invoice_number: 'INV/2026/0007', sale_order_id: 55,
  });
  ctx.applyDossierProjection_(classeur, facturee);
  const aerien = onglets['Saisie aérien'];
  assert.strictEqual(aerien.lignes().length, 1, 'aucune ligne ajoutée');
  assert.strictEqual(aerien.valeur(ligne, C.invoiceNumber), 'INV/2026/0007');
  assert.strictEqual(aerien.valeur(ligne, C.invoiceId), 909);
}

/* --- 9. Deux paiements partiels : deux lignes, deux clés ---------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const p = projectionDossier();
  p.articles = [1, 2].map(n => Object.assign({}, p.articles[0], {
    article_key: 'AIR-DSS-CDG-2026-002-A001|A|' + n,
  }));
  p.payments = [
    {payment_key: 'AIR-DSS-CDG-2026-002-A001|P|1', amount_eur: 0,
     amount_xof: 100000, currency_code: 'XOF', payment_method: 'wave',
     collected_by: 'Gilles', wave_reference: 'TW1', payment_date: '2026-08-29'},
    {payment_key: 'AIR-DSS-CDG-2026-002-A001|P|2', amount_eur: 0,
     amount_xof: 50000, currency_code: 'XOF', payment_method: 'wave',
     collected_by: 'Gilles', wave_reference: 'TW2', payment_date: '2026-08-29'},
  ];
  const lignes = ctx.applyDossierProjection_(classeur, p);
  const aerien = onglets['Saisie aérien'];
  const cles = lignes.map(r => aerien.valeur(r, C.paymentKey));
  assert.strictEqual(new Set(cles).size, 2, 'deux clés de paiement distinctes');
  assert.strictEqual(aerien.valeur(lignes[0], C.paymentXof), 100000);
  assert.strictEqual(aerien.valeur(lignes[1], C.paymentXof), 50000);
  assert.strictEqual(aerien.valeur(lignes[0], C.paymentMethod), 'Wave');
  assert.strictEqual(aerien.valeur(lignes[0], C.collectedBy), 'Gilles');
  // Rejeu : toujours deux lignes, aucune fusion.
  ctx.applyDossierProjection_(classeur, p);
  assert.strictEqual(aerien.lignes().length, 2);
}

/* --- 10. Les formules restent neutralisées ------------------------ */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const p = projectionDossier();
  p.dossier.customer.name = '=IMPORTXML("http://x","//a")';
  p.articles[0].description = '+HYPERLINK("http://x")';
  const [ligne] = ctx.applyDossierProjection_(classeur, p);
  const aerien = onglets['Saisie aérien'];
  assert.ok(String(aerien.valeur(ligne, C.client)).startsWith("'"),
            'un nom commençant par = doit être littéralisé');
  assert.ok(String(aerien.valeur(ligne, C.description)).startsWith("'"),
            'une désignation commençant par + doit être littéralisée');
}

/* --- 11. Une replanification en attente n'est pas écrasée --------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const [ligne] = ctx.applyDossierProjection_(classeur, projectionDossier());
  const aerien = onglets['Saisie aérien'];
  aerien.getRange(ligne, C.syncMessage).setValue(
    ctx.DALLY.replanIntentMarker + ' à traiter');
  ctx.applyDossierProjection_(classeur, projectionDossier());
  assert.ok(String(aerien.valeur(ligne, C.syncMessage))
              .startsWith(ctx.DALLY.replanIntentMarker),
            'l’intention humaine doit survivre à la projection');
}

/* --- 12. Dépense : une ligne, et une seule au rejeu --------------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const projection = {
    projection_type: 'cash_expense', outbox_id: 2, sheet: 'Dépenses',
    expense: {
      external_expense_key: 'ops:dep-1', date: '2026-08-29',
      category: 'Manutention', description: 'Portage', beneficiary: 'Équipe',
      allocations: [{actor: 'Gilles', amount: 15000}], total_amount: 15000,
      currency_code: 'XOF', payment_method: 'cash', reference: '',
      state: 'review', comment: '', consolidation_reference: 'AIR-1',
      odoo_id: 91,
    },
  };
  const ligne = ctx.applyExpenseProjection_(classeur, projection);
  const feuille = onglets['Dépenses'];
  assert.strictEqual(feuille.lignes().length, 1);
  assert.strictEqual(feuille.valeur(ligne, DALLY_CASH_EXPENSE.gilles), 15000);
  assert.strictEqual(feuille.valeur(ligne, DALLY_CASH_EXPENSE.currency), 'FCFA');
  assert.strictEqual(feuille.valeur(ligne, DALLY_CASH_EXPENSE.state), 'À vérifier');
  ctx.applyExpenseProjection_(classeur, projection);
  assert.strictEqual(feuille.lignes().length, 1, 'un rejeu de dépense reste unique');
}

/* --- 13. Transfert : une ligne, et une seule au rejeu ------------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  const projection = {
    projection_type: 'cash_transfer', outbox_id: 3, sheet: 'Transferts caisse',
    transfer: {
      external_transfer_key: 'ops:trf-1', date: '2026-08-29',
      from_actor: 'Gilles', to_actor: 'Dalanda', amount: 100000,
      currency_code: 'XOF', reason: 'Remise du soir', payment_method: 'cash',
      state: 'review', comment: '', odoo_id: 77,
    },
  };
  const ligne = ctx.applyTransferProjection_(classeur, projection);
  const feuille = onglets['Transferts caisse'];
  assert.strictEqual(feuille.lignes().length, 1);
  assert.strictEqual(feuille.valeur(ligne, DALLY_CASH_TRANSFER.fromActor), 'Gilles');
  assert.strictEqual(feuille.valeur(ligne, DALLY_CASH_TRANSFER.toActor), 'Dalanda');
  ctx.applyTransferProjection_(classeur, projection);
  assert.strictEqual(feuille.lignes().length, 1, 'un rejeu de transfert reste unique');
  // Et rien n'a touché les dossiers ni les dépenses.
  assert.strictEqual(onglets['Dépenses'].lignes().length, 0);
  assert.strictEqual(onglets['Saisie aérien'].lignes().length, 0);
}

/* --- 14. Une projection sans identité est refusée ------------------ */
{
  const classeur = fauxClasseur(nouveauClasseur());
  const p = projectionDossier();
  p.identity = {sync_source_key: '', global_external_reference: ''};
  assert.throws(() => ctx.applyDossierProjection_(classeur, p), /Identité absente/);
  assert.throws(
    () => ctx.applyProjection_(classeur, {projection_type: 'agenda'}),
    /Projection inconnue/, 'l’agenda est hors périmètre du classeur');
}

/* --- 15. Un onglet absent est une erreur permanente ---------------- */
{
  const classeur = fauxClasseur(nouveauClasseur());
  const p = projectionDossier({sheet: 'Onglet qui n’existe pas'});
  assert.throws(() => ctx.applyDossierProjection_(classeur, p), /Onglet introuvable/);
  assert.strictEqual(
    ctx.isPermanentProjectionError_(new Error('Onglet introuvable : X')), true);
  assert.strictEqual(
    ctx.isPermanentProjectionError_(new Error('Service indisponible')), false);
}

/* --- 16. L'ACK part seulement après l'écriture --------------------- */
{
  const evenements = [];
  const onglets = nouveauClasseur(() => evenements.push('write'));
  const classeur = fauxClasseur(onglets);
  const transport = contexte({
    getActive: () => classeur,
    apiGet: () => ({projections: [projectionDossier()]}),
    apiPost: (_path, _property, body) => {
      assert.strictEqual(_path, '/api/v1/freight/sheet-outbox/ack',
                         'la projection ne doit jamais appeler le sync Sheet → Odoo');
      evenements.push('ack');
      assert.strictEqual(onglets['Saisie aérien'].lignes().length, 1,
                         'la ligne doit exister avant l’ACK');
      assert.strictEqual(body.results[0].ok, true);
    },
  });
  transport.dallySheetProjectionPull();
  assert.strictEqual(evenements[0], 'write');
  assert.strictEqual(evenements[evenements.length - 1], 'ack');
}

/* --- 17. Sheet écrit, ACK perdu : rejeu sans doublon --------------- */
{
  const onglets = nouveauClasseur();
  const classeur = fauxClasseur(onglets);
  let accusés = 0;
  const transport = contexte({
    getActive: () => classeur,
    apiGet: () => ({projections: [projectionDossier()]}),
    apiPost: () => {
      accusés += 1;
      if (accusés === 1) throw new Error('ACK perdu');
      return {};
    },
  });
  assert.throws(() => transport.dallySheetProjectionPull(), /ACK perdu/);
  assert.strictEqual(onglets['Saisie aérien'].lignes().length, 1,
                     'le Sheet a été écrit avant la perte de l’ACK');
  transport.dallySheetProjectionPull();
  assert.strictEqual(onglets['Saisie aérien'].lignes().length, 1,
                     'le rejeu retrouve la ligne au lieu de la dupliquer');
  assert.strictEqual(accusés, 2, 'le second ACK aboutit');
}

/* --- 18. Google indisponible : erreur transportable, aucun succès -- */
{
  let accusé = null;
  const transport = contexte({
    getActive: () => { throw new Error('Google indisponible'); },
    apiGet: () => ({projections: [projectionDossier()]}),
    apiPost: (_path, _property, body) => { accusé = body; },
  });
  const résultat = transport.dallySheetProjectionPull();
  assert.strictEqual(résultat.results[0].ok, false);
  assert.strictEqual(résultat.results[0].permanent, false,
                     'une panne Google doit rester réessayable');
  assert.strictEqual(accusé.results[0].ok, false,
                     'Odoo reçoit un échec, jamais un faux delivered');
}

console.log('test_freight_sheet_outbox_projection: OK');
