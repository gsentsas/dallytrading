/* DallyTrading Freight — Google Sheets bound connector.
 *
 * Secrets are NEVER stored in cells or source code. Configure Script Properties:
 *   DALLY_FREIGHT_SYNC_API_KEY
 *   DALLY_FREIGHT_BILLING_API_KEY
 *
 * The connector groups rows by dossier, sends one freight payload per dossier,
 * then optionally creates the draft invoice and synchronises payments.
 */

const DALLY = Object.freeze({
  configSheet: 'Synchronisation CRM',
  dryRunSheet: 'Migration CRM dry-run',
  dataSheets: ['Saisie maritime', 'Saisie aérien'],
  headerRow: 2,
  firstDataRow: 3,
  maxColumn: 58,
  columns: Object.freeze({
    depositDate: 1, dossier: 2, client: 3, phone: 4, clientType: 5,
    goodsCategory: 6, description: 7, quantity: 8, length: 9, width: 10,
    height: 11, unitVolume: 12, totalVolume: 13, announcedWeight: 14,
    exactWeight: 15, billingMethod: 18, billableWeight: 19, manualPrice: 20,
    appliedPrice: 21, dossierFee: 22, otherFees: 23, totalEur: 25,
    parcelState: 30, notes: 31,
    syncStatus: 32, partnerId: 33, shipmentId: 34, lastSync: 35,
    saleOrderId: 36, invoiceId: 37, invoiceNumber: 38, syncMessage: 39,
    responsible: 40, pricingType: 41, pricingReason: 42, customsValue: 43,
    transportMode: 45, tariffFamily: 46, address: 47, email: 48,
    paymentEur: 49, paymentXof: 50, paymentMethod: 54, collectedBy: 55,
    articleKey: 56, paymentFlag: 57, paymentKey: 58,
  }),
  familyCodes: Object.freeze({
    'Alimentaire standard': 'food',
    'Halieutiques': 'seafood',
    'Miel': 'honey',
    'Habits / Vêtements': 'clothing',
    'Non alimentaire': 'non_food',
  }),
  modeCodes: Object.freeze({'Aérien': 'air', 'Aerien': 'air', 'Maritime': 'sea'}),
  segmentCodes: Object.freeze({'Particulier': 'individual', 'Professionnel': 'business'}),
  billingCodes: Object.freeze({'Poids reel': 'real', 'Poids réel': 'real', 'Poids volumetrique': 'volumetric', 'Poids volumétrique': 'volumetric', 'Sur devis': 'quote'}),
  pricingCodes: Object.freeze({'Standard': 'standard', 'Promotion': 'promotion', 'Spécial': 'special', 'Special': 'special'}),
  stateCodes: Object.freeze({
    'Annonce': 'request_received', 'Depose': 'goods_received', 'Déposé': 'goods_received',
    'Pese': 'preparing', 'Pesé': 'preparing', 'Charge': 'ready', 'Chargé': 'ready',
    'Expedie': 'in_transit', 'Expédié': 'in_transit', 'Arrive': 'arrived', 'Arrivé': 'arrived',
    'Retire': 'delivered', 'Retiré': 'delivered',
  }),
  paymentCodes: Object.freeze({'Espèces': 'cash', 'Especes': 'cash', 'Wave': 'wave', 'Virement': 'bank_transfer'}),
});

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Dally CRM')
    .addItem('Initialiser / installer les déclencheurs', 'dallySetup')
    .addItem('Diagnostic configuration', 'dallyDiagnostic')
    .addSeparator()
    .addItem('Synchroniser les dossiers en attente', 'dallySyncPending')
    .addItem('Synchroniser le dossier sélectionné', 'dallySyncSelectedDossier')
    .addItem('Créer la facture brouillon du dossier', 'dallyInvoiceSelectedDossier')
    .addItem('Synchroniser / corriger les paiements du dossier', 'dallyPaymentsSelectedDossier')
    .addSeparator()
    .addItem('Marquer tous les dossiers à synchroniser', 'dallyMarkAllForSync')
    .addToUi();

  if (typeof dallyCashOnOpen_ === 'function') dallyCashOnOpen_();
  if (typeof dallyPdfOnOpen_ === 'function') dallyPdfOnOpen_();
}

function dallySetup() {
  ensureConfigSheet_();
  installTriggers_();
  SpreadsheetApp.getActive().toast('Connecteur Dally CRM initialisé. Configurez maintenant les 2 clés dans Script Properties.', 'Dally CRM', 8);
}

function dallyDiagnostic() {
  const cfg = readConfig_();
  const props = PropertiesService.getScriptProperties();
  const errors = [];
  const warnings = [];
  if (!/^https:\/\//i.test(cfg.baseUrl)) errors.push('URL CRM invalide');
  if (!props.getProperty('DALLY_FREIGHT_SYNC_API_KEY')) errors.push('DALLY_FREIGHT_SYNC_API_KEY manquante');
  if (!props.getProperty('DALLY_FREIGHT_BILLING_API_KEY')) errors.push('DALLY_FREIGHT_BILLING_API_KEY manquante');
  DALLY.dataSheets.forEach(name => {
    const sh = SpreadsheetApp.getActive().getSheetByName(name);
    if (!sh) errors.push('Feuille manquante: ' + name);
    if (sh && sh.getMaxColumns() < DALLY.maxColumn) errors.push('Colonnes CRM incomplètes sur: ' + name);
    if (!cfg.routes[name] || !cfg.routes[name].active) errors.push('Routage inactif/manquant: ' + name);
  });
  if (!cfg.syncPayments) warnings.push('Synchronisation paiements = NON : utiliser le menu paiement pour appliquer les corrections.');
  if (!cfg.autoSync) warnings.push('Synchronisation automatique = NON : fonctionnement manuel sécurisé.');
  const lines = errors.length ? errors : ['Configuration prête. Aucune écriture CRM effectuée.'];
  if (warnings.length) lines.push('', 'Avertissements:', ...warnings);
  SpreadsheetApp.getUi().alert('Diagnostic Dally CRM', lines.join('\n'), SpreadsheetApp.getUi().ButtonSet.OK);
}

function installTriggers_() {
  const ss = SpreadsheetApp.getActive();
  const handlers = new Set(['dallyMarkEdited_', 'dallyScheduledSync_']);
  ScriptApp.getProjectTriggers().forEach(t => {
    if (handlers.has(t.getHandlerFunction())) ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('dallyMarkEdited_').forSpreadsheet(ss).onEdit().create();
  ScriptApp.newTrigger('dallyScheduledSync_').timeBased().everyMinutes(1).create();
}

function dallyMarkEdited_(e) {
  if (!e || !e.range) return;
  const sheet = e.range.getSheet();
  if (!DALLY.dataSheets.includes(sheet.getName())) return;
  const firstRow = Math.max(e.range.getRow(), DALLY.firstDataRow);
  const lastRow = e.range.getLastRow();
  if (lastRow < DALLY.firstDataRow) return;
  const firstCol = e.range.getColumn();
  const lastCol = e.range.getLastColumn();
  // API output columns must not create an edit loop.
  if (firstCol >= DALLY.columns.syncStatus && lastCol <= DALLY.columns.syncMessage) return;
  for (let r = firstRow; r <= lastRow; r++) {
    if (String(sheet.getRange(r, DALLY.columns.dossier).getDisplayValue() || '').trim()) {
      sheet.getRange(r, DALLY.columns.syncStatus).setValue('À synchroniser');
      sheet.getRange(r, DALLY.columns.syncMessage).clearContent();
    }
  }
}

function dallyScheduledSync_() {
  const cfg = readConfig_();
  if (!cfg.autoSync) return;
  withScriptLock_(() => syncPending_(cfg, false));
}

function dallySyncPending() {
  withScriptLock_(() => syncPending_(readConfig_(), true));
}

function dallyMarkAllForSync() {
  DALLY.dataSheets.forEach(name => {
    const sh = SpreadsheetApp.getActive().getSheetByName(name);
    if (!sh) return;
    const last = sh.getLastRow();
    if (last < DALLY.firstDataRow) return;
    const dossiers = sh.getRange(DALLY.firstDataRow, DALLY.columns.dossier, last - DALLY.firstDataRow + 1, 1).getDisplayValues();
    const out = dossiers.map(r => [String(r[0] || '').trim() ? 'À synchroniser' : '']);
    sh.getRange(DALLY.firstDataRow, DALLY.columns.syncStatus, out.length, 1).setValues(out);
  });
  SpreadsheetApp.getActive().toast('Tous les dossiers renseignés ont été marqués « À synchroniser ».', 'Dally CRM', 6);
}

function dallySyncSelectedDossier() {
  withScriptLock_(() => {
    const ctx = selectedDossier_();
    syncDossier_(ctx.sheet, ctx.dossier, rowsForDossier_(ctx.sheet, ctx.dossier), readConfig_());
  });
}

function dallyInvoiceSelectedDossier() {
  withScriptLock_(() => {
    const ctx = selectedDossier_();
    const rows = rowsForDossier_(ctx.sheet, ctx.dossier);
    prepareInvoice_(ctx.sheet, rows, readConfig_(), true);
  });
}

function dallyPaymentsSelectedDossier() {
  withScriptLock_(() => {
    const ctx = selectedDossier_();
    syncPayments_(ctx.sheet, rowsForDossier_(ctx.sheet, ctx.dossier), readConfig_(), true);
  });
}

function syncPending_(cfg, manual) {
  let remaining = Math.max(1, Number(cfg.maxDossiers || 10));
  let done = 0;
  for (const name of DALLY.dataSheets) {
    if (remaining <= 0) break;
    const sheet = SpreadsheetApp.getActive().getSheetByName(name);
    if (!sheet || !cfg.routes[name] || !cfg.routes[name].active) continue;
    const dirty = dirtyDossiers_(sheet);
    for (const dossier of dirty) {
      if (remaining-- <= 0) break;
      try {
        syncDossier_(sheet, dossier, rowsForDossier_(sheet, dossier), cfg);
        done++;
      } catch (err) {
        markDossierError_(sheet, dossier, err);
      }
    }
  }
  if (manual) SpreadsheetApp.getActive().toast(done + ' dossier(s) synchronisé(s).', 'Dally CRM', 6);
}

function syncDossier_(sheet, dossier, rows, cfg) {
  const articleRows = prepareArticleRows_(sheet, dossier, rows);
  if (!articleRows.length) throw new Error('Aucun article Freight détecté pour ' + dossier);
  const payload = buildFreightPayload_(sheet.getName(), dossier, rows, articleRows, cfg);
  const data = apiPost_('/api/v1/freight/sync', 'DALLY_FREIGHT_SYNC_API_KEY', payload, cfg);
  const lineByKey = {};
  (data.lines || []).forEach(line => lineByKey[String(line.external_line_key)] = line);
  const now = new Date();
  rows.forEach(row => {
    const key = articleKey_(row);
    const line = lineByKey[String(key || '')];
    setCell_(sheet, row.row, DALLY.columns.syncStatus, 'Synchronisé');
    setCell_(sheet, row.row, DALLY.columns.partnerId, data.partner_id || '');
    setCell_(sheet, row.row, DALLY.columns.shipmentId, data.shipment_id || '');
    setCell_(sheet, row.row, DALLY.columns.lastSync, now);
    const msg = line ? ('CRM OK • tarif ' + line.pricing_status) : 'CRM OK • ligne paiement/administrative';
    setCell_(sheet, row.row, DALLY.columns.syncMessage, msg);
  });

  let invoiceData = null;
  if (cfg.autoInvoice && invoiceReady_(articleRows)) {
    try { invoiceData = prepareInvoice_(sheet, rows, cfg, false); }
    catch (err) { appendMessage_(sheet, rows, 'Facture: ' + errorText_(err)); }
  }
  if (cfg.syncPayments) {
    try { syncPayments_(sheet, rows, cfg, false); }
    catch (err) { appendMessage_(sheet, rows, 'Paiement: ' + errorText_(err)); }
  } else if (dossierHasPayments_(rows)) {
    appendMessage_(sheet, rows, 'Paiements non synchronisés : option globale désactivée');
  }
  return {sync: data, invoice: invoiceData};
}

function buildFreightPayload_(sheetName, dossier, rows, articleRows, cfg) {
  const first = articleRows[0];
  const route = cfg.routes[sheetName];
  const partnerId = firstNumber_(rows, DALLY.columns.partnerId);
  const source = cfg.migrationMode ? 'legacy_xlsx' : 'google_sheets';
  const payload = {
    external_reference: dossier,
    transport_mode: route.mode || DALLY.modeCodes[display_(first, DALLY.columns.transportMode)],
    direction: route.direction,
    source: source,
    goods_received_on: dateIso_(value_(first, DALLY.columns.depositDate)),
    customer_segment: DALLY.segmentCodes[display_(first, DALLY.columns.clientType)] || 'individual',
    state: DALLY.stateCodes[display_(first, DALLY.columns.parcelState)] || 'request_received',
    dossier_fee_eur: firstNumber_(rows, DALLY.columns.dossierFee) || 0,
    other_fees_eur: sum_(articleRows, DALLY.columns.otherFees),
    client: {
      name: firstText_(rows, DALLY.columns.client),
      email: firstText_(rows, DALLY.columns.email),
      phone: firstText_(rows, DALLY.columns.phone),
      address: firstText_(rows, DALLY.columns.address),
    },
    origin: {country_code: route.originCountry, city: route.originCity, location: route.originCity},
    destination: {country_code: route.destinationCountry, city: route.destinationCity, location: route.destinationCity},
    lines: articleRows.map(buildLine_),
  };
  if (partnerId) payload.partner_id = partnerId;
  pruneEmptyObject_(payload.client);
  return payload;
}

function buildLine_(row) {
  const family = display_(row, DALLY.columns.tariffFamily);
  const pricingType = display_(row, DALLY.columns.pricingType);
  const out = {
    external_line_key: articleKey_(row),
    package_type: 'parcel',
    description: display_(row, DALLY.columns.description),
    goods_category: display_(row, DALLY.columns.goodsCategory),
    quantity: numberOr_(value_(row, DALLY.columns.quantity), 1),
    announced_weight_kg: numberOrNull_(value_(row, DALLY.columns.announcedWeight)),
    exact_weight_kg: numberOrNull_(value_(row, DALLY.columns.exactWeight)),
    length_cm: numberOrNull_(value_(row, DALLY.columns.length)),
    width_cm: numberOrNull_(value_(row, DALLY.columns.width)),
    height_cm: numberOrNull_(value_(row, DALLY.columns.height)),
    unit_volume_cbm: numberOrNull_(value_(row, DALLY.columns.unitVolume)),
    total_volume_cbm: numberOrNull_(value_(row, DALLY.columns.totalVolume)),
    billing_method: DALLY.billingCodes[display_(row, DALLY.columns.billingMethod)] || 'real',
    tariff_family_code: DALLY.familyCodes[family],
    manual_unit_price_eur: numberOrNull_(value_(row, DALLY.columns.manualPrice)),
    pricing_type: DALLY.pricingCodes[pricingType] || 'standard',
    pricing_reason: display_(row, DALLY.columns.pricingReason),
    customs_value_xof: numberOrNull_(value_(row, DALLY.columns.customsValue)),
  };
  Object.keys(out).forEach(k => { if (out[k] === null || out[k] === '' || typeof out[k] === 'undefined') delete out[k]; });
  return out;
}

function prepareInvoice_(sheet, rows, cfg, force) {
  const shipmentId = firstNumber_(rows, DALLY.columns.shipmentId);
  const dossier = firstText_(rows, DALLY.columns.dossier);
  if (!shipmentId && !dossier) throw new Error('Dossier non synchronisé');
  const articleRows = prepareArticleRows_(sheet, dossier, rows);
  if (!invoiceReady_(articleRows)) {
    const message = 'Facturation bloquée : tarif/poids incomplet ou dossier « Sur devis ».';
    if (force) throw new Error(message);
    return null;
  }
  const payload = shipmentId ? {shipment_id: shipmentId, external_reference: dossier} : {external_reference: dossier};
  const data = apiPost_('/api/v1/freight/invoice', 'DALLY_FREIGHT_BILLING_API_KEY', payload, cfg);
  rows.forEach(row => {
    setCell_(sheet, row.row, DALLY.columns.saleOrderId, data.sale_order_id || '');
    setCell_(sheet, row.row, DALLY.columns.invoiceId, data.invoice_id || '');
    setCell_(sheet, row.row, DALLY.columns.invoiceNumber, data.invoice_number || 'Brouillon');
    appendMessage_(sheet, [row], 'Facture ' + (data.invoice_state || 'draft') + ' • ' + (data.amount_total || 0) + ' ' + (data.currency || 'EUR'));
  });
  return data;
}

function syncPayments_(sheet, rows, cfg, force) {
  const dossier = firstText_(rows, DALLY.columns.dossier);
  const shipmentId = firstNumber_(rows, DALLY.columns.shipmentId);
  if (!shipmentId && !dossier) {
    if (force) throw new Error('Synchronisez le dossier avant ses paiements.');
    return [];
  }

  const source = cfg.migrationMode ? 'legacy_xlsx' : 'google_sheets';
  const results = [];
  const activeKeys = [];
  let paymentOrdinal = 0;

  rows.forEach(row => {
    const eur = Number(value_(row, DALLY.columns.paymentEur) || 0);
    const xof = Number(value_(row, DALLY.columns.paymentXof) || 0);
    if (eur > 0 && xof > 0) throw new Error('Deux devises sur la même ligne de paiement du dossier ' + dossier);
    if (eur <= 0 && xof <= 0) return;

    paymentOrdinal++;
    let key = display_(row, DALLY.columns.paymentKey);
    if (!key) {
      key = dossier + '|P|' + paymentOrdinal;
      setCell_(sheet, row.row, DALLY.columns.paymentKey, key);
    }
    setCell_(sheet, row.row, DALLY.columns.paymentFlag, 1);
    activeKeys.push(key);

    const methodLabel = display_(row, DALLY.columns.paymentMethod);
    const method = DALLY.paymentCodes[methodLabel];
    if (!method) throw new Error('Mode de paiement non mappé: ' + methodLabel);
    const payload = {
      external_payment_key: key,
      external_reference: dossier,
      shipment_id: shipmentId || undefined,
      amount: eur > 0 ? eur : xof,
      currency_code: eur > 0 ? 'EUR' : 'XOF',
      payment_date: dateIso_(value_(row, DALLY.columns.depositDate)),
      payment_method: method,
      collected_by: display_(row, DALLY.columns.collectedBy),
      source: source,
    };
    Object.keys(payload).forEach(k => { if (typeof payload[k] === 'undefined' || payload[k] === '') delete payload[k]; });
    const data = apiPost_('/api/v1/freight/payment', 'DALLY_FREIGHT_BILLING_API_KEY', payload, cfg);
    appendMessage_(sheet, [row], 'Paiement ' + data.collection_state + ' • ' + data.amount + ' ' + data.currency);
    if (data.invoice_id) {
      setCell_(sheet, row.row, DALLY.columns.invoiceId, data.invoice_id);
      setCell_(sheet, row.row, DALLY.columns.invoiceNumber, data.invoice_number || '');
    }
    results.push(data);
  });

  const reconcilePayload = {
    external_reference: dossier,
    shipment_id: shipmentId || undefined,
    active_payment_keys: activeKeys,
    source: source,
  };
  Object.keys(reconcilePayload).forEach(k => { if (typeof reconcilePayload[k] === 'undefined' || reconcilePayload[k] === '') delete reconcilePayload[k]; });
  const reconciliation = apiPost_('/api/v1/freight/payment/reconcile', 'DALLY_FREIGHT_BILLING_API_KEY', reconcilePayload, cfg);
  const cancelled = reconciliation.cancelled_payment_keys || [];
  const blocked = reconciliation.blocked_registered_payment_keys || [];
  appendMessage_(sheet, rows.slice(0, 1), 'Paiements alignés • ' + activeKeys.length + ' actif(s) • ' + cancelled.length + ' annulé(s)');
  if (blocked.length) {
    const message = 'Paiement(s) déjà comptabilisé(s), correction comptable requise : ' + blocked.join(', ');
    appendMessage_(sheet, rows.slice(0, 1), message);
    if (force) throw new Error(message);
  }
  return {payments: results, reconciliation: reconciliation};
}

function apiPost_(path, propertyName, payload, cfg) {
  const key = PropertiesService.getScriptProperties().getProperty(propertyName);
  if (!key) throw new Error('Script Property manquante: ' + propertyName);
  const body = Object.assign({request_uuid: Utilities.getUuid()}, payload);
  const response = UrlFetchApp.fetch(cfg.baseUrl.replace(/\/$/, '') + path, {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: {'X-API-Key': key}, payload: JSON.stringify(body),
  });
  const status = response.getResponseCode();
  let parsed;
  try { parsed = JSON.parse(response.getContentText() || '{}'); }
  catch (e) { throw new Error('Réponse CRM non JSON (HTTP ' + status + ')'); }
  if (status < 200 || status >= 300 || !parsed.success) {
    const err = parsed.error || {};
    throw new Error('HTTP ' + status + ' • ' + (err.code || 'api_error') + ' • ' + (err.message || 'Erreur CRM'));
  }
  return parsed.data || {};
}

function readConfig_() {
  const sh = ensureConfigSheet_();
  const yes = v => String(v || '').trim().toUpperCase() === 'OUI';
  const cfg = {
    baseUrl: String(sh.getRange('B4').getDisplayValue() || '').trim(),
    autoSync: yes(sh.getRange('B5').getDisplayValue()),
    autoInvoice: yes(sh.getRange('B6').getDisplayValue()),
    syncPayments: yes(sh.getRange('B7').getDisplayValue()),
    maxDossiers: Number(sh.getRange('B8').getValue() || 10),
    migrationMode: yes(sh.getRange('B9').getDisplayValue()),
    routes: {},
  };
  const routeValues = sh.getRange(16, 1, Math.max(1, sh.getLastRow() - 15), 8).getDisplayValues();
  routeValues.forEach(r => {
    const name = String(r[0] || '').trim();
    if (!name) return;
    cfg.routes[name] = {
      active: yes(r[1]), mode: String(r[2] || '').trim(), direction: String(r[3] || '').trim(),
      originCountry: String(r[4] || '').trim(), originCity: String(r[5] || '').trim(),
      destinationCountry: String(r[6] || '').trim(), destinationCity: String(r[7] || '').trim(),
    };
  });
  return cfg;
}

function ensureConfigSheet_() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(DALLY.configSheet);
  if (sh) return sh;
  sh = ss.insertSheet(DALLY.configSheet, 0);
  sh.getRange('A1:H1').merge().setValue('DALLYTRADING — SYNCHRONISATION GOOGLE SHEETS ↔ CRM FREIGHT').setFontWeight('bold');
  sh.getRange('A4:B9').setValues([
    ['URL CRM', 'https://crm.dallytrading.com'],
    ['Synchronisation automatique', 'NON'],
    ['Facture brouillon automatique', 'NON'],
    ['Synchronisation paiements', 'NON'],
    ['Dossiers max par cycle', 10],
    ['Mode initial migration', 'NON'],
  ]);
  sh.getRange('A15:H17').setValues([
    ['Feuille','Actif','Mode API','Direction','Pays départ','Ville départ','Pays arrivée','Ville arrivée'],
    ['Saisie maritime','OUI','sea','export','SN','Dakar','FR','Paris'],
    ['Saisie aérien','OUI','air','export','SN','Dakar','FR','Paris'],
  ]);
  return sh;
}

function dirtyDossiers_(sheet) {
  const last = sheet.getLastRow();
  if (last < DALLY.firstDataRow) return [];
  const data = sheet.getRange(DALLY.firstDataRow, 1, last - DALLY.firstDataRow + 1, DALLY.columns.syncStatus).getDisplayValues();
  const out = [];
  const seen = new Set();
  data.forEach(r => {
    const dossier = String(r[DALLY.columns.dossier - 1] || '').trim();
    const status = String(r[DALLY.columns.syncStatus - 1] || '').trim();
    if (dossier && status === 'À synchroniser' && !seen.has(dossier)) { seen.add(dossier); out.push(dossier); }
  });
  return out;
}

function rowsForDossier_(sheet, dossier) {
  const last = sheet.getLastRow();
  if (last < DALLY.firstDataRow) return [];
  const count = last - DALLY.firstDataRow + 1;
  const values = sheet.getRange(DALLY.firstDataRow, 1, count, DALLY.maxColumn).getValues();
  const display = sheet.getRange(DALLY.firstDataRow, 1, count, DALLY.maxColumn).getDisplayValues();
  const out = [];
  for (let i = 0; i < count; i++) {
    if (String(display[i][DALLY.columns.dossier - 1] || '').trim() === dossier) {
      out.push({row: DALLY.firstDataRow + i, values: values[i], display: display[i]});
    }
  }
  return out;
}

function selectedDossier_() {
  const sheet = SpreadsheetApp.getActiveSheet();
  if (!DALLY.dataSheets.includes(sheet.getName())) throw new Error('Sélectionnez une ligne dans Saisie maritime ou Saisie aérien.');
  const row = SpreadsheetApp.getActiveRange().getRow();
  if (row < DALLY.firstDataRow) throw new Error('Sélectionnez une ligne de dossier.');
  const dossier = String(sheet.getRange(row, DALLY.columns.dossier).getDisplayValue() || '').trim();
  if (!dossier) throw new Error('Aucun N dossier sur la ligne sélectionnée.');
  return {sheet, dossier};
}

function prepareArticleRows_(sheet, dossier, rows) {
  const articleRows = rows.filter(isArticleRow_);
  let ordinal = 0;
  articleRows.forEach(row => {
    ordinal++;
    const existing = display_(row, DALLY.columns.articleKey);
    row._syncArticleKey = existing || (dossier + '|A|' + ordinal);
    if (!existing) setCell_(sheet, row.row, DALLY.columns.articleKey, row._syncArticleKey);
  });
  return articleRows;
}

function articleKey_(row) {
  return String(row._syncArticleKey || display_(row, DALLY.columns.articleKey) || '').trim();
}

function isArticleRow_(row) {
  if (display_(row, DALLY.columns.articleKey)) return true;
  if (Number(value_(row, DALLY.columns.totalEur) || 0) > 0) return true;
  if (!display_(row, DALLY.columns.description)) return false;
  const measures = [
    DALLY.columns.announcedWeight,
    DALLY.columns.exactWeight,
    DALLY.columns.length,
    DALLY.columns.width,
    DALLY.columns.height,
    DALLY.columns.unitVolume,
    DALLY.columns.totalVolume,
  ];
  return measures.some(col => Number(value_(row, col) || 0) > 0);
}

function invoiceReady_(articleRows) {
  if (!articleRows.length) return false;
  return articleRows.every(row => {
    const method = DALLY.billingCodes[display_(row, DALLY.columns.billingMethod)] || '';
    return !!articleKey_(row) && method !== 'quote' &&
      Number(value_(row, DALLY.columns.billableWeight) || 0) > 0 &&
      Number(value_(row, DALLY.columns.appliedPrice) || 0) > 0;
  });
}

function dossierHasPayments_(rows) {
  return rows.some(row => Number(value_(row, DALLY.columns.paymentEur) || 0) > 0 || Number(value_(row, DALLY.columns.paymentXof) || 0) > 0);
}

function markDossierError_(sheet, dossier, err) {
  const msg = errorText_(err).slice(0, 500);
  rowsForDossier_(sheet, dossier).forEach(row => {
    setCell_(sheet, row.row, DALLY.columns.syncStatus, 'Erreur');
    setCell_(sheet, row.row, DALLY.columns.lastSync, new Date());
    setCell_(sheet, row.row, DALLY.columns.syncMessage, msg);
  });
}

function appendMessage_(sheet, rows, message) {
  rows.forEach(row => {
    const cell = sheet.getRange(row.row, DALLY.columns.syncMessage);
    const current = String(cell.getDisplayValue() || '').trim();
    cell.setValue(current ? current + ' | ' + message : message);
  });
}

function setCell_(sheet, row, column, value) { sheet.getRange(row, column).setValue(value); }
function value_(row, column) { return row.values[column - 1]; }
function display_(row, column) { return String(row.display[column - 1] == null ? '' : row.display[column - 1]).trim(); }
function firstText_(rows, column) { for (const r of rows) { const v = display_(r, column); if (v) return v; } return ''; }
function firstNumber_(rows, column) { for (const r of rows) { const v = numberOrNull_(value_(r, column)); if (v !== null) return v; } return null; }
function sum_(rows, column) { return rows.reduce((acc, r) => acc + Number(value_(r, column) || 0), 0); }
function numberOr_(value, fallback) { const n = Number(value); return Number.isFinite(n) && n > 0 ? n : fallback; }
function numberOrNull_(value) { if (value === '' || value === null || typeof value === 'undefined') return null; const n = Number(value); return Number.isFinite(n) ? n : null; }
function dateIso_(value) { if (!value) return ''; if (value instanceof Date) return Utilities.formatDate(value, 'Etc/UTC', 'yyyy-MM-dd'); const d = new Date(value); return isNaN(d.getTime()) ? '' : Utilities.formatDate(d, 'Etc/UTC', 'yyyy-MM-dd'); }
function pruneEmptyObject_(obj) { Object.keys(obj).forEach(k => { if (!obj[k]) delete obj[k]; }); }
function errorText_(err) { return err && err.message ? err.message : String(err); }
function withScriptLock_(fn) { const lock = LockService.getScriptLock(); if (!lock.tryLock(5000)) throw new Error('Une synchronisation Dally CRM est déjà en cours.'); try { return fn(); } finally { lock.releaseLock(); } }
