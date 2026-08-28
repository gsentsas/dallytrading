/* DallyTrading Freight — Google Sheets bound connector.
 *
 * Secrets are NEVER stored in cells or source code. Configure Script Properties:
 *   DALLY_FREIGHT_SYNC_API_KEY
 *   DALLY_FREIGHT_BILLING_API_KEY
 *
 * The connector groups rows by planned consolidation plus dossier, sends one freight payload per logical dossier,
 * then optionally creates the draft invoice and synchronises payments.
 */

const DALLY = Object.freeze({
  configSheet: 'Synchronisation CRM',
  dryRunSheet: 'Migration CRM dry-run',
  replanIntentMarker: 'Replanification demandée depuis la feuille.',
  dataSheets: ['Saisie maritime', 'Saisie aérien'],
  headerRow: 2,
  firstDataRow: 3,
  maxColumn: 63,
  columns: Object.freeze({
    depositDate: 1, plannedConsolidation: 2, dossier: 3, client: 4, phone: 5, clientType: 6,
    goodsCategory: 7, description: 8, quantity: 9, length: 10, width: 11,
    height: 12, unitVolume: 13, totalVolume: 14, announcedWeight: 15,
    exactWeight: 16, billingMethod: 19, billableWeight: 20, manualPrice: 21,
    appliedPrice: 22, dossierFee: 23, otherFees: 24, totalEur: 26,
    parcelState: 31, notes: 32,
    syncStatus: 33, partnerId: 34, shipmentId: 35, lastSync: 36,
    saleOrderId: 37, invoiceId: 38, invoiceNumber: 39, syncMessage: 40,
    responsible: 41, pricingType: 42, pricingReason: 43, customsValue: 44,
    transportMode: 46, tariffFamily: 47, address: 48, email: 49,
    paymentEur: 50, paymentXof: 51, paymentMethod: 55, collectedBy: 56,
    articleKey: 57, paymentFlag: 58, paymentKey: 59,
    syncSourceKey: 60, globalExternalReference: 61,
    intakeConsolidationRef: 62, collectionLocalRef: 63,
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
    'Annule': 'cancelled', 'Annulé': 'cancelled',
  }),
  paymentCodes: Object.freeze({'Espèces': 'cash', 'Especes': 'cash', 'Wave': 'wave', 'Virement': 'bank_transfer'}),
});

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Dally CRM')
    .addItem('Initialiser / installer les déclencheurs', 'dallySetup')
    .addItem('Diagnostic configuration', 'dallyDiagnostic')
    .addSeparator()
    .addItem('Actualiser les départs ouverts', 'dallyRefreshOpenConsolidations')
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
  DALLY.dataSheets.forEach(name => ensureSheetLayout_(SpreadsheetApp.getActive().getSheetByName(name)));
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
  if (!assertCanonicalSheetLayout_(sheet, true)) return;
  const firstRow = Math.max(e.range.getRow(), DALLY.firstDataRow);
  const lastRow = e.range.getLastRow();
  if (lastRow < DALLY.firstDataRow) return;
  const firstCol = e.range.getColumn();
  const lastCol = e.range.getLastColumn();
  const plannedEdited = firstCol <= DALLY.columns.plannedConsolidation && lastCol >= DALLY.columns.plannedConsolidation;
  // API output columns must not create an edit loop.
  if (firstCol >= DALLY.columns.syncStatus && lastCol <= DALLY.columns.syncMessage) return;
  for (let r = firstRow; r <= lastRow; r++) {
    const dossier = String(sheet.getRange(r, DALLY.columns.dossier).getDisplayValue() || '').trim();
    const planned = String(sheet.getRange(r, DALLY.columns.plannedConsolidation).getDisplayValue() || '').trim();
    if (dossier) {
      sheet.getRange(r, DALLY.columns.syncStatus).setValue('À synchroniser');
      const messageCell = sheet.getRange(r, DALLY.columns.syncMessage);
      const currentMessage = String(messageCell.getDisplayValue() || '').trim();
      if (plannedEdited) messageCell.setValue(DALLY.replanIntentMarker);
      else if (!hasReplanIntentText_(currentMessage)) messageCell.clearContent();
    } else if (planned) {
      sheet.getRange(r, DALLY.columns.syncStatus).setValue('À initialiser manuellement');
      sheet.getRange(r, DALLY.columns.syncMessage).setValue('Sélectionnez toutes les lignes du nouveau dossier puis utilisez « Synchroniser le dossier sélectionné ».');
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
    if (!assertCanonicalSheetLayout_(sh, true)) return;
    const last = sh.getLastRow();
    if (last < DALLY.firstDataRow) return;
    const dossiers = sh.getRange(DALLY.firstDataRow, DALLY.columns.dossier, last - DALLY.firstDataRow + 1, 1).getDisplayValues();
    const rowCount = last - DALLY.firstDataRow + 1;
    const planned = sh.getRange(DALLY.firstDataRow, DALLY.columns.plannedConsolidation, rowCount, 1).getDisplayValues();
    const out = dossiers.map((r, i) => [String(r[0] || '').trim() ? 'À synchroniser' : (String(planned[i][0] || '').trim() ? 'À initialiser manuellement' : '')]);
    sh.getRange(DALLY.firstDataRow, DALLY.columns.syncStatus, out.length, 1).setValues(out);
  });
  SpreadsheetApp.getActive().toast('Tous les dossiers renseignés ont été marqués « À synchroniser ».', 'Dally CRM', 6);
}

function dallySyncSelectedDossier() {
  withScriptLock_(() => {
    const ctx = selectedDossier_();
    syncDossier_(ctx.sheet, ctx.dossier, ctx.rows || rowsForDossier_(ctx.sheet, ctx.key), readConfig_());
  });
}

function dallyInvoiceSelectedDossier() {
  withScriptLock_(() => {
    const ctx = selectedDossier_();
    const rows = rowsForDossier_(ctx.sheet, ctx.key);
    prepareInvoice_(ctx.sheet, rows, readConfig_(), true);
  });
}

function dallyPaymentsSelectedDossier() {
  withScriptLock_(() => {
    const ctx = selectedDossier_();
    syncPayments_(ctx.sheet, rowsForDossier_(ctx.sheet, ctx.key), readConfig_(), true);
  });
}

function syncPending_(cfg, manual) {
  let remaining = Math.max(1, Number(cfg.maxDossiers || 10));
  let done = 0;
  for (const name of DALLY.dataSheets) {
    if (remaining <= 0) break;
    const sheet = SpreadsheetApp.getActive().getSheetByName(name);
    if (!sheet || !cfg.routes[name] || !cfg.routes[name].active) continue;
    assertCanonicalSheetLayout_(sheet);
    const dirty = dirtyDossiers_(sheet);
    for (const dossier of dirty) {
      if (remaining-- <= 0) break;
      try {
        const group = rowsForDossier_(sheet, dossier);
        syncDossier_(sheet, firstText_(group, DALLY.columns.dossier), group, cfg);
        done++;
      } catch (err) {
        markDossierError_(sheet, dossier, err);
      }
    }
  }
  if (manual) SpreadsheetApp.getActive().toast(done + ' dossier(s) synchronisé(s).', 'Dally CRM', 6);
}

function syncDossier_(sheet, dossier, rows, cfg) {
  ensureSourceKey_(sheet, dossier, rows);
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
    if (Object.prototype.hasOwnProperty.call(data, 'planned_consolidation_ref')) {
      setCell_(sheet, row.row, DALLY.columns.plannedConsolidation, sheetLiteralText_(data.planned_consolidation_ref));
    }
    if (data.collection_local_ref) setCell_(sheet, row.row, DALLY.columns.dossier, data.collection_local_ref);
    setCell_(sheet, row.row, DALLY.columns.partnerId, data.partner_id || '');
    setCell_(sheet, row.row, DALLY.columns.shipmentId, data.shipment_id || '');
    setCell_(sheet, row.row, DALLY.columns.collectionLocalRef, data.collection_local_ref || '');
    setCell_(sheet, row.row, DALLY.columns.globalExternalReference, data.external_reference || '');
    setCell_(sheet, row.row, DALLY.columns.intakeConsolidationRef, data.intake_consolidation_ref || '');
    setCell_(sheet, row.row, DALLY.columns.syncSourceKey, data.sync_source_key || sourceKey_(sheet.getName(), dossier, rows));
    setCell_(sheet, row.row, DALLY.columns.lastSync, now);
    const normalMessage = line ? ('CRM OK • tarif ' + line.pricing_status) : 'CRM OK • ligne paiement/administrative';
    const msg = data.requires_replan
      ? String(data.sync_message || 'Départ clôturé — replanification requise') + ' • ' + normalMessage
      : normalMessage;
    setCell_(sheet, row.row, DALLY.columns.syncMessage, msg);
  });
  rows.forEach(row => setCell_(sheet, row.row, DALLY.columns.syncStatus, 'Synchronisé'));

  // The writes above make the in-memory snapshot stale. Reload by the
  // server-issued source identity before invoice/payment calls.
  const stableKey = data.sync_source_key ? 'source|' + data.sync_source_key : logicalDossierKey_(rows[0].display);
  rows = rowsForDossier_(sheet, stableKey);
  const refreshedArticleRows = prepareArticleRows_(sheet, dossier, rows);

  let invoiceData = null;
  if (cfg.autoInvoice && invoiceReady_(refreshedArticleRows)) {
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

function sheetShipmentState_(row) {
  const label = display_(row, DALLY.columns.parcelState);
  if (!label) return 'request_received';

  const code = DALLY.stateCodes[label];
  if (!code) {
    throw new Error(
      'Statut colis non reconnu: "' + label +
      '". Corrigez la colonne AD avant synchronisation.'
    );
  }
  return code;
}

function buildFreightPayload_(sheetName, dossier, rows, articleRows, cfg) {
  const first = articleRows[0];
  const route = cfg.routes[sheetName];
  const partnerId = firstNumber_(rows, DALLY.columns.partnerId);
  const source = cfg.migrationMode ? 'legacy_xlsx' : 'google_sheets';
  const plannedRef = firstText_(rows, DALLY.columns.plannedConsolidation);
  const sourceKey = sourceKey_(sheetName, dossier, rows);
  const serverIdentified = isServerIdentifiedDossier_(rows);
  const explicitReplan = hasExplicitReplanIntent_(rows);
  if (serverIdentified && explicitReplan && !plannedRef) {
    throw new Error('Une replanification doit sélectionner une consolidation ouverte ; vider la colonne B n’est pas une désaffectation valide.');
  }
  const sendPlannedRef = !!plannedRef && (!serverIdentified || explicitReplan);
  const payload = {
    external_reference: payloadExternalReference_(rows, dossier),
    sync_source_key: sourceKey,
    transport_mode: route.mode || DALLY.modeCodes[display_(first, DALLY.columns.transportMode)],
    direction: route.direction,
    source: source,
    goods_received_on: dateIso_(value_(first, DALLY.columns.depositDate)),
    customer_segment: DALLY.segmentCodes[display_(first, DALLY.columns.clientType)] || 'individual',
    state: sheetShipmentState_(first),
    planned_consolidation_ref: sendPlannedRef ? plannedRef : undefined,
    collection_local_ref: plannedRef ? undefined : (firstText_(rows, DALLY.columns.collectionLocalRef) || undefined),
    dossier_fee_eur: firstNumber_(rows, DALLY.columns.dossierFee) || 0,
    other_fees_eur: sum_(articleRows, DALLY.columns.otherFees),
    client: {
      name: firstText_(rows, DALLY.columns.client),
      email: firstText_(rows, DALLY.columns.email),
      phone: firstText_(rows, DALLY.columns.phone),
      address: firstText_(rows, DALLY.columns.address),
    },
    origin: {country_code: route.originCountry, city: route.originCity, location: route.originLocation || undefined},
    destination: {country_code: route.destinationCountry, city: route.destinationCity, location: route.destinationLocation || undefined},
    lines: articleRows.map(buildLine_),
  };
  if (partnerId) payload.partner_id = partnerId;
  pruneEmptyObject_(payload.client);
  Object.keys(payload).forEach(k => { if (typeof payload[k] === 'undefined' || payload[k] === '') delete payload[k]; });
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
  const globalRef = payloadExternalReference_(rows, dossier);
  const payload = shipmentId ? {shipment_id: shipmentId} : {};
  if (globalRef) payload.external_reference = globalRef;
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

  rows.forEach(row => {
    const eur = Number(value_(row, DALLY.columns.paymentEur) || 0);
    const xof = Number(value_(row, DALLY.columns.paymentXof) || 0);
    if (eur > 0 && xof > 0) throw new Error('Deux devises sur la même ligne de paiement du dossier ' + dossier);
    if (eur <= 0 && xof <= 0) return;

    let key = display_(row, DALLY.columns.paymentKey);
    if (!key) {
      key = stableGlobalKey_(row, dossier) + '|P|' + Utilities.getUuid();
      setCell_(sheet, row.row, DALLY.columns.paymentKey, key);
    }
    setCell_(sheet, row.row, DALLY.columns.paymentFlag, 1);
    activeKeys.push(key);

    const methodLabel = display_(row, DALLY.columns.paymentMethod);
    const method = DALLY.paymentCodes[methodLabel];
    if (!method) throw new Error('Mode de paiement non mappé: ' + methodLabel);
    const payload = {
      external_payment_key: key,
      ...(payloadExternalReference_(rows, dossier) ? {external_reference: payloadExternalReference_(rows, dossier)} : {}),
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
    ...(payloadExternalReference_(rows, dossier) ? {external_reference: payloadExternalReference_(rows, dossier)} : {}),
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

function dallyRefreshOpenConsolidations() {
  DALLY.dataSheets.forEach(name => {
    const sheet = SpreadsheetApp.getActive().getSheetByName(name);
    if (sheet) assertCanonicalSheetLayout_(sheet);
  });
  const refreshedCount = withScriptLock_(() => {
    const cfg=readConfig_(); const data=apiGet_('/api/v1/freight/consolidations/open','DALLY_FREIGHT_SYNC_API_KEY',cfg);
    const bindings = fetchSheetBindings_(cfg);
    const sh=ensureConfigSheet_(); const start=21; const rows=(data.consolidations||[]).map(c=>[c.name,c.transport_mode,c.direction,c.origin_city||c.origin||'',c.destination_city||c.destination||'',c.collection_close_on||'']);
    const safeRows = rows.map(row => row.map(sheetLiteralText_));
    sh.getRange(start,1,Math.max(1, sh.getMaxRows()-start+1),6).clearContent();
    sh.getRange(20,1,1,6).setValues([['Consolidations ouvertes','Mode','Direction','Origine','Destination','Clôture collecte']]);
    if (safeRows.length) sh.getRange(start,1,safeRows.length,6).setValues(safeRows);
    DALLY.dataSheets.forEach(name => {
      const dataSheet = SpreadsheetApp.getActive().getSheetByName(name); if (!dataSheet) return;
      applySheetBindings_(dataSheet, bindings);
      dataSheet.getRange(DALLY.firstDataRow, DALLY.columns.plannedConsolidation, dataSheet.getMaxRows()-DALLY.firstDataRow+1, 1).clearDataValidations();
      const route=cfg.routes[name]||{};
      const allowed=(data.consolidations||[]).filter(c => c.transport_mode===route.mode && c.direction===route.direction && (!route.originCountry || c.origin_country_code===route.originCountry) && (!route.originCity || c.origin_city===route.originCity) && (!route.destinationCountry || c.destination_country_code===route.destinationCountry) && (!route.destinationCity || c.destination_city===route.destinationCity)).map(c=>c.name);
      const assigned = [];
      if (dataSheet.getLastRow() >= DALLY.firstDataRow) {
        const shipmentValues = dataSheet.getRange(DALLY.firstDataRow, DALLY.columns.shipmentId, dataSheet.getLastRow() - DALLY.firstDataRow + 1, 1).getDisplayValues();
        shipmentValues.forEach(value => {
          const binding = bindings[String(value[0] || '').trim()];
          if (binding && binding.planned_consolidation_ref && !assigned.includes(binding.planned_consolidation_ref)) assigned.push(binding.planned_consolidation_ref);
        });
      }
      assigned.forEach(value => { if (!allowed.includes(value)) allowed.push(value); });
      if (allowed.length) {
        const validation=SpreadsheetApp.newDataValidation().requireValueInList(allowed,true).setAllowInvalid(false).build();
        dataSheet.getRange(DALLY.firstDataRow,DALLY.columns.plannedConsolidation,dataSheet.getMaxRows()-DALLY.firstDataRow+1,1).setDataValidation(validation);
      }
    });
    return rows.length;
  });
  SpreadsheetApp.getActive().toast(refreshedCount+' départ(s) ouvert(s) actualisé(s).','Dally CRM',6);
}

function fetchSheetBindings_(cfg) {
  const ids = [];
  DALLY.dataSheets.forEach(name => {
    const sheet = SpreadsheetApp.getActive().getSheetByName(name);
    if (!sheet || sheet.getLastRow() < DALLY.firstDataRow) return;
    const values = sheet.getRange(DALLY.firstDataRow, DALLY.columns.shipmentId, sheet.getLastRow() - DALLY.firstDataRow + 1, 1).getDisplayValues();
    values.forEach(row => {
      const id = Number(String(row[0] || '').trim());
      if (Number.isInteger(id) && id > 0 && !ids.includes(id)) ids.push(id);
    });
  });
  const bindings = {};
  for (let start = 0; start < ids.length; start += 200) {
    const chunk = ids.slice(start, start + 200);
    const data = apiGet_('/api/v1/freight/sheet-bindings?shipment_ids=' + encodeURIComponent(chunk.join(',')), 'DALLY_FREIGHT_SYNC_API_KEY', cfg);
    (data.bindings || []).forEach(binding => { bindings[String(binding.shipment_id)] = binding; });
  }
  return bindings;
}

function applySheetBindings_(sheet, bindings) {
  if (!sheet || sheet.getLastRow() < DALLY.firstDataRow) return;
  const count = sheet.getLastRow() - DALLY.firstDataRow + 1;
  const display = sheet.getRange(DALLY.firstDataRow, 1, count, DALLY.maxColumn).getDisplayValues();
  const grouped = new Map();
  for (let i = 0; i < display.length; i++) {
    const shipmentId = String(display[i][DALLY.columns.shipmentId - 1] || '').trim();
    if (!shipmentId || !bindings[shipmentId]) continue;
    const dossier = String(display[i][DALLY.columns.dossier - 1] || '').trim();
    const source = String(display[i][DALLY.columns.syncSourceKey - 1] || '').trim();
    const global = String(display[i][DALLY.columns.globalExternalReference - 1] || '').trim();
    const key = source ? 'source|' + source : (global ? 'global|' + global : 'shipment|' + shipmentId + '|' + dossier);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push({index: i, row: display[i], binding: bindings[shipmentId]});
  }
  const concurrentMessage = 'Modification Sheet détectée pendant l’actualisation : valeur de consolidation conservée. Synchronisez le dossier puis relancez l’actualisation.';
  const readState = member => {
    const row = DALLY.firstDataRow + member.index;
    return {
      planned: String(sheet.getRange(row, DALLY.columns.plannedConsolidation, 1, 1).getDisplayValue() || '').trim(),
      status: String(sheet.getRange(row, DALLY.columns.syncStatus, 1, 1).getDisplayValue() || '').trim(),
      message: String(sheet.getRange(row, DALLY.columns.syncMessage, 1, 1).getDisplayValue() || '').trim(),
    };
  };
  const markConcurrent = members => members.forEach(member => {
    const row = DALLY.firstDataRow + member.index;
    const currentMessage = String(sheet.getRange(row, DALLY.columns.syncMessage, 1, 1).getDisplayValue() || '').trim();
    setCell_(sheet, row, DALLY.columns.syncMessage, preserveReplanIntentMessage_(currentMessage, concurrentMessage));
  });
  grouped.forEach(members => {
    const binding = members[0].binding;
    const crmValue = String(binding.planned_consolidation_ref || '').trim();
    const changed = [];
    members.forEach(member => {
      const snapshotPlanned = String(member.row[DALLY.columns.plannedConsolidation - 1] || '').trim();
      const snapshotStatus = String(member.row[DALLY.columns.syncStatus - 1] || '').trim();
      const live = readState(member);
      member._bindingExpected = live;
      if (live.planned !== snapshotPlanned || live.status !== snapshotStatus) changed.push(member);
      member.row[DALLY.columns.plannedConsolidation - 1] = live.planned;
      member.row[DALLY.columns.syncStatus - 1] = live.status;
      member.row[DALLY.columns.syncMessage - 1] = live.message;
    });
    const unsafeChange = changed.some(member =>
      member._bindingExpected.status !== 'À synchroniser' || member._bindingExpected.planned === crmValue
    );
    if (unsafeChange) {
      markConcurrent(members);
      return;
    }
    const stillCurrent = () => members.every(member => {
      const live = readState(member);
      return live.planned === member._bindingExpected.planned && live.status === member._bindingExpected.status && live.message === member._bindingExpected.message;
    });
    const replanRequested = members.some(member => hasReplanIntentText_(member.row[DALLY.columns.syncMessage - 1]));
    const pending = members.filter(member =>
      String(member.row[DALLY.columns.syncStatus - 1] || '').trim() === 'À synchroniser' &&
      String(member.row[DALLY.columns.plannedConsolidation - 1] || '').trim() !== crmValue
    );
    if (pending.length) {
      const pendingValues = [...new Set(pending.map(member =>
        String(member.row[DALLY.columns.plannedConsolidation - 1] || '').trim()
      ))];
      const localValue = pendingValues[0] || '';
      const message = pendingValues.length > 1
        ? 'Conflit de consolidation dans le dossier : plusieurs valeurs Sheet en attente. Harmonisez la colonne B avant synchronisation.'
        : 'Consolidation en attente : Sheet ' + (localValue || '(vide)') + ' / CRM ' + (crmValue || '(vide)') + '. Synchronisez le dossier pour appliquer le changement.';
      if (!stillCurrent()) {
        markConcurrent(members);
        return;
      }
      members.forEach(member => {
        if (pendingValues.length === 1) setCell_(sheet, DALLY.firstDataRow + member.index, DALLY.columns.plannedConsolidation, sheetLiteralText_(localValue));
        setCell_(sheet, DALLY.firstDataRow + member.index, DALLY.columns.syncMessage, replanRequested ? DALLY.replanIntentMarker + ' ' + message : message);
      });
      return;
    }

    // Historical rollout guard: an empty CRM assignment must not erase a
    // pre-existing planned consolidation from the Sheet. Odoo cannot silently
    // unassign a shipment once it has a planned departure, so CRM=false here
    // may mean the legacy Sheet assignment has not yet been backfilled.
    const localPlannedValues = [...new Set(members.map(member =>
      String(member.row[DALLY.columns.plannedConsolidation - 1] || '').trim()
    ).filter(Boolean))];
    if (!crmValue && localPlannedValues.length) {
      if (!stillCurrent()) markConcurrent(members);
      return;
    }

    if (!stillCurrent()) {
      markConcurrent(members);
      return;
    }
    members.forEach(member => {
      setCell_(sheet, DALLY.firstDataRow + member.index, DALLY.columns.plannedConsolidation, sheetLiteralText_(crmValue));
      if (binding.requires_replan) {
        setCell_(sheet, DALLY.firstDataRow + member.index, DALLY.columns.syncMessage, 'Replanification requise dans une consolidation ouverte.');
      } else if (hasReplanIntentText_(member.row[DALLY.columns.syncMessage - 1])) {
        setCell_(sheet, DALLY.firstDataRow + member.index, DALLY.columns.syncMessage, '');
      }
    });
  });
}

function apiGet_(path, propertyName, cfg) {
  const key=PropertiesService.getScriptProperties().getProperty(propertyName); if (!key) throw new Error('Script Property manquante: '+propertyName);
  const response=UrlFetchApp.fetch(cfg.baseUrl.replace(/\/$/,'')+path,{method:'get',muteHttpExceptions:true,headers:{'X-API-Key':key}});
  const status=response.getResponseCode(); let parsed; try { parsed=JSON.parse(response.getContentText()||'{}'); } catch(e) { throw new Error('Réponse CRM non JSON (HTTP '+status+')'); }
  if (status<200 || status>=300 || !parsed.success) throw new Error('HTTP '+status+' • '+((parsed.error||{}).message||'Erreur CRM')); return parsed.data||{};
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
  const routeValues = sh.getRange(16, 1, 2, 8).getDisplayValues();
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

function ensureSheetLayout_(sheet) {
  if (!sheet) return;
  const initialLayout = detectSheetLayout_(sheet);
  migrateLegacySheetLayout_(sheet);
  if (sheet.getMaxColumns() < DALLY.maxColumn) sheet.insertColumnsAfter(sheet.getMaxColumns(), DALLY.maxColumn-sheet.getMaxColumns());
  if (initialLayout === 'empty') {
    sheet.getRange(DALLY.headerRow, DALLY.columns.depositDate).setValue('Date depot');
    sheet.getRange(DALLY.headerRow, DALLY.columns.plannedConsolidation).setValue('Consolidation prévue');
    sheet.getRange(DALLY.headerRow, DALLY.columns.dossier).setValue('N dossier');
    sheet.getRange(DALLY.headerRow, DALLY.columns.articleKey, 1, 3).setValues([['Clé article facture','Flag règlement facture','Clé règlement facture']]);
    sheet.getRange(DALLY.headerRow, DALLY.columns.syncSourceKey, 1, 4).setValues([['sync source key','global external reference','intake consolidation ref','collection local ref']]);
    sheet.hideColumns(DALLY.columns.syncSourceKey, 4);
    return;
  }
  const planned = sheet.getRange(DALLY.headerRow, DALLY.columns.plannedConsolidation);
  if (!planned.getValue()) planned.setValue('Consolidation prévue');
  const labels = ['sync source key','global external reference','intake consolidation ref','collection local ref'];
  const range = sheet.getRange(DALLY.headerRow, DALLY.columns.syncSourceKey, 1, labels.length);
  const current = range.getValues()[0];
  labels.forEach((label,i) => { if (!current[i]) range.getCell(1,i+1).setValue(label); });
  sheet.hideColumns(DALLY.columns.syncSourceKey, 4);
}

function isLegacy58Header_(header) {
  const value = index => String(header[index - 1] || '').trim();
  return value(1) === 'Date depot' && value(2) === 'N dossier' &&
    value(3) !== 'Consolidation prévue' &&
    [59, 60, 61, 62, 63].every(index => !value(index));
}

function migrateLegacySheetLayout_(sheet) {
  const header = sheet.getRange(DALLY.headerRow, 1, 1, Math.min(sheet.getMaxColumns(), DALLY.maxColumn)).getDisplayValues()[0];
  const date = String(header[0] || '').trim();
  const b = String(header[1] || '').trim();
  const c = String(header[2] || '').trim();
  if (b === 'Consolidation prévue' && c === 'N dossier') return;
  if (!date && !b && !c) return;
  const legacyPlanned = String(header[58] || '').trim();
  const legacyTechnical = ['sync source key', 'global external reference', 'intake consolidation ref', 'collection local ref'];
  const hasLegacy63 = date === 'Date depot' && b === 'N dossier' && legacyPlanned === 'Consolidation prévue' &&
    legacyTechnical.every((label, index) => String(header[59 + index] || '').trim() === label);
  const hasLegacy58 = isLegacy58Header_(header);
  if (!hasLegacy63 && !hasLegacy58) throw new Error('Disposition de feuille inconnue — migration automatique refusée.');
  sheet.insertColumnAfter(1);
  const rows = Math.max(0, sheet.getMaxRows() - DALLY.headerRow + 1);
  if (hasLegacy63 && rows) {
    sheet.getRange(DALLY.headerRow, 60, rows, 1).copyTo(sheet.getRange(DALLY.headerRow, 2, rows, 1), {contentsOnly: false});
    sheet.deleteColumn(60);
  }
  if (sheet.getMaxColumns() < DALLY.maxColumn) sheet.insertColumnsAfter(sheet.getMaxColumns(), DALLY.maxColumn - sheet.getMaxColumns());
  sheet.getRange(DALLY.headerRow, 2).setValue('Consolidation prévue');
  sheet.getRange(DALLY.headerRow, 3).setValue('N dossier');
  sheet.getRange(DALLY.headerRow, 57, 1, 7).setValues([['Clé article facture','Flag règlement facture','Clé règlement facture', ...legacyTechnical]]);
  sheet.hideColumns(60, 4);
}

function detectSheetLayout_(sheet) {
  if (!sheet) return 'unknown';
  const max = sheet.getMaxColumns();
  const header = sheet.getRange(DALLY.headerRow, 1, 1, Math.min(max, DALLY.maxColumn)).getDisplayValues()[0];
  const value = index => String(header[index - 1] || '').trim();
  if (!value(1) && !value(2) && !value(3)) return 'empty';
  if (value(2) === 'Consolidation prévue' && value(3) === 'N dossier' &&
      value(57) === 'Clé article facture' && value(58) === 'Flag règlement facture' &&
      value(59) === 'Clé règlement facture' && value(60) === 'sync source key' &&
      value(61) === 'global external reference' && value(62) === 'intake consolidation ref' && value(63) === 'collection local ref') return 'canonical';
  if (value(1) === 'Date depot' && value(2) === 'N dossier' && value(59) === 'Consolidation prévue' &&
      ['sync source key','global external reference','intake consolidation ref','collection local ref'].every((label, i) => value(60 + i) === label)) return 'legacy63';
  if (isLegacy58Header_(header)) return 'legacy58';
  return 'unknown';
}

function assertCanonicalSheetLayout_(sheet, quiet) {
  const layout = detectSheetLayout_(sheet);
  if (layout === 'canonical') return true;
  if (quiet && (layout === 'legacy58' || layout === 'legacy63')) return false;
  if (layout === 'legacy58' || layout === 'legacy63' || layout === 'empty') throw new Error('Disposition ancienne détectée. Lancez Dally CRM → Initialiser / installer les déclencheurs avant toute synchronisation.');
  throw new Error('Disposition de feuille inconnue — opération refusée.');
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

function logicalDossierKey_(row) {
  const source = String(row[DALLY.columns.syncSourceKey - 1] || '').trim();
  const global = String(row[DALLY.columns.globalExternalReference - 1] || '').trim();
  const dossier = String(row[DALLY.columns.dossier - 1] || '').trim();
  const planned = String(row[DALLY.columns.plannedConsolidation - 1] || '').trim();
  if (source) return 'source|' + source;
  if (global) return 'global|' + global;
  const shipment = String(row[DALLY.columns.shipmentId - 1] || '').trim();
  return 'shipment|' + (shipment || dossier) + '|' + dossier;
}

// Resolve the identity sent to freight/billing endpoints.  A planned dossier
// only falls back to its visible Axxx while it is still a legacy first bind;
// once Odoo has returned a server identity, the local Axxx must never be sent
// as a forged global reference.
function payloadExternalReference_(rows, dossier) {
  const global = firstText_(rows, DALLY.columns.globalExternalReference);
  if (global) return global;
  const planned = firstText_(rows, DALLY.columns.plannedConsolidation);
  if (!planned) return dossier;
  const serverIdentified = !!(
    firstNumber_(rows, DALLY.columns.shipmentId) ||
    firstText_(rows, DALLY.columns.intakeConsolidationRef) ||
    firstText_(rows, DALLY.columns.collectionLocalRef)
  );
  return serverIdentified ? '' : dossier;
}

function isServerIdentifiedDossier_(rows) {
  return !!(
    firstNumber_(rows, DALLY.columns.shipmentId) ||
    firstText_(rows, DALLY.columns.globalExternalReference) ||
    firstText_(rows, DALLY.columns.intakeConsolidationRef) ||
    firstText_(rows, DALLY.columns.collectionLocalRef)
  );
}

function hasReplanIntentText_(value) {
  return String(value || '').trim().startsWith(DALLY.replanIntentMarker);
}

function hasExplicitReplanIntent_(rows) {
  return rows.some(row => hasReplanIntentText_(display_(row, DALLY.columns.syncMessage)));
}

function preserveReplanIntentMessage_(current, message) {
  return hasReplanIntentText_(current) ? DALLY.replanIntentMarker + (message ? ' ' + message : '') : message;
}

function dirtyDossiers_(sheet) {
  const last = sheet.getLastRow();
  if (last < DALLY.firstDataRow) return [];
  const start = DALLY.firstDataRow;
  const count = last - start + 1;
  const values = sheet.getRange(start, 1, count, DALLY.maxColumn).getValues();
  const display = sheet.getRange(start, 1, count, DALLY.maxColumn).getDisplayValues();
  const groups = new Map();
  for (let i = 0; i < count; i++) {
    const row = display[i];
    const dossier = String(row[DALLY.columns.dossier - 1] || '').trim();
    const planned = String(row[DALLY.columns.plannedConsolidation - 1] || '').trim();
    if (!dossier) continue; // blank-B dossiers remain manual-init only.
    const shipment = String(row[DALLY.columns.shipmentId - 1] || '').trim();
    const namespace = 'shipment|' + (shipment || dossier) + '|' + dossier;
    if (!groups.has(namespace)) groups.set(namespace, []);
    groups.get(namespace).push({index: i, display: row});
  }
  // A server identity must never span two visible namespaces (for example
  // C1|A001 and C2|A001).  Build the indexes before normalising any row so a
  // duplicate cannot be hidden by propagation.
  const identityIndexes = [DALLY.columns.syncSourceKey, DALLY.columns.globalExternalReference, DALLY.columns.shipmentId].map(column => {
    const index = new Map();
    groups.forEach((members, namespace) => members.forEach(m => {
      const value = String(m.display[column - 1] || '').trim();
      if (!value) return;
      if (!index.has(value)) index.set(value, new Set());
      index.get(value).add(namespace);
    }));
    return index;
  });
  const crossNamespace = new Set();
  identityIndexes.forEach(index => index.forEach(namespaces => {
    if (namespaces.size > 1) namespaces.forEach(namespace => crossNamespace.add(namespace));
  }));
  const out = [];
  groups.forEach((members, namespace) => {
    const unique = column => new Set(members.map(m => String(m.display[column - 1] || '').trim()).filter(Boolean));
    const planned = unique(DALLY.columns.plannedConsolidation);
    const clients = unique(DALLY.columns.client);
    const sources = unique(DALLY.columns.syncSourceKey);
    const globals = unique(DALLY.columns.globalExternalReference);
    const shipments = unique(DALLY.columns.shipmentId);
    const locals = unique(DALLY.columns.collectionLocalRef);
    if (crossNamespace.has(namespace) || planned.size > 1 || clients.size > 1 || sources.size > 1 || globals.size > 1 || shipments.size > 1 || locals.size > 1) {
      members.forEach(m => {
        setCell_(sheet, start + m.index, DALLY.columns.syncStatus, 'Erreur');
        setCell_(sheet, start + m.index, DALLY.columns.syncMessage, crossNamespace.has(namespace) ? 'Identité serveur associée à plusieurs namespaces de dossier.' : 'La sélection contient des identités de dossier en conflit.');
      });
      return;
    }
    const source = sources.values().next().value || '';
    const global = globals.values().next().value || '';
    const shipment = shipments.values().next().value || '';
    const local = locals.values().next().value || '';
    [[DALLY.columns.syncSourceKey, source], [DALLY.columns.globalExternalReference, global], [DALLY.columns.shipmentId, shipment], [DALLY.columns.collectionLocalRef, local]].forEach(([column, value]) => {
      if (!value) return;
      members.forEach(m => {
        if (!String(m.display[column - 1] || '').trim()) {
          setCell_(sheet, start + m.index, column, value);
          m.display[column - 1] = value;
        }
      });
    });
    const key = source ? 'source|' + source : (global ? 'global|' + global : namespace);
    if (members.some(m => String(m.display[DALLY.columns.syncStatus - 1] || '').trim() === 'À synchroniser')) out.push(key);
  });
  return [...new Set(out)];
}

function rowsForDossier_(sheet, key) {
  const last = sheet.getLastRow(); if (last < DALLY.firstDataRow) return [];
  const count = last - DALLY.firstDataRow + 1;
  const values = sheet.getRange(DALLY.firstDataRow, 1, count, DALLY.maxColumn).getValues();
  const display = sheet.getRange(DALLY.firstDataRow, 1, count, DALLY.maxColumn).getDisplayValues(); const out=[];
  for (let i=0;i<count;i++) if (logicalDossierKey_(display[i]) === key) out.push({row:DALLY.firstDataRow+i,values:values[i],display:display[i]});
  return out;
}

function assertNoSelectedIdentityCollision_(sheet, selectedRows) {
  const namespaceOf = row => logicalDossierKey_(row.display);
  const selectedNamespace = namespaceOf(selectedRows[0]);
  const selectedRowNumbers = new Set(selectedRows.map(row => row.row));
  const selectedIsBlank = selectedRows.every(row => !display_(row, DALLY.columns.dossier));
  const identities = [DALLY.columns.syncSourceKey, DALLY.columns.globalExternalReference, DALLY.columns.shipmentId]
    .map(column => new Set(selectedRows.map(row => display_(row, column)).filter(Boolean)));
  if (identities.some(values => values.size > 1)) throw new Error('La sélection contient des identités de dossier en conflit.');
  const all = sheet.getRange(DALLY.firstDataRow, 1, sheet.getLastRow() - DALLY.firstDataRow + 1, DALLY.maxColumn).getDisplayValues();
  for (let index = 0; index < all.length; index++) {
    const row = all[index];
    if (selectedRowNumbers.has(DALLY.firstDataRow + index)) continue;
    const rowDossier = String(row[DALLY.columns.dossier - 1] || '').trim();
    if (!selectedIsBlank && rowDossier && namespaceOf({display: row}) === selectedNamespace) continue;
    for (let i = 0; i < identities.length; i++) {
      const value = String(row[[DALLY.columns.syncSourceKey, DALLY.columns.globalExternalReference, DALLY.columns.shipmentId][i] - 1] || '').trim();
      if (value && identities[i].has(value)) throw new Error('Identité serveur associée à plusieurs namespaces de dossier.');
    }
  }
}

function selectedDossier_() {
  const sheet=SpreadsheetApp.getActiveSheet(); if (!DALLY.dataSheets.includes(sheet.getName())) throw new Error('Sélectionnez une ligne dans une feuille de saisie.');
  assertCanonicalSheetLayout_(sheet);
  const range=SpreadsheetApp.getActiveRange(); const first=range.getRow(); const last=first + Math.max(1, range.getNumRows()) - 1;
  if (first < DALLY.firstDataRow) throw new Error('Sélectionnez une ligne de dossier.');
  const values=sheet.getRange(first,1,last-first+1,DALLY.maxColumn).getValues();
  const display=sheet.getRange(first,1,last-first+1,DALLY.maxColumn).getDisplayValues();
  const rows=values.map((v,i)=>({row:first+i,values:v,display:display[i]}));
  const dossier=String(display[0][DALLY.columns.dossier-1]||'').trim();
  const blank=display.some(v=>!String(v[DALLY.columns.dossier-1]||'').trim());
  if (blank && display.some(v=>String(v[DALLY.columns.dossier-1]||'').trim())) throw new Error('La sélection contient des dossiers Axxx et des lignes vierges.');
  if (blank) {
    const planned=String(display[0][DALLY.columns.plannedConsolidation-1]||'').trim();
    const client=String(display[0][DALLY.columns.client-1]||'').trim();
    if (!planned) throw new Error('Un nouveau dossier doit choisir une consolidation prévue.');
    const sourceKeys = rows.map(r=>display_(r,DALLY.columns.syncSourceKey));
    const nonEmptySourceKeys = sourceKeys.filter(Boolean);
    if ((nonEmptySourceKeys.length && nonEmptySourceKeys.length !== sourceKeys.length) || new Set(nonEmptySourceKeys).size > 1 || rows.some(r=>display_(r,DALLY.columns.globalExternalReference) || display_(r,DALLY.columns.shipmentId) || display_(r,DALLY.columns.plannedConsolidation)!==planned || display_(r,DALLY.columns.client)!==client)) throw new Error('Les lignes sélectionnées doivent partager client/consolidation et ne posséder aucune identité conflictuelle.');
    assertNoSelectedIdentityCollision_(sheet, rows);
    return {sheet, dossier:'', key:logicalDossierKey_(values[0]), rows};
  }
  const logicalKeys = rows.map(r => logicalDossierKey_(r.display));
  if (new Set(logicalKeys).size > 1) throw new Error('La sélection contient plusieurs dossiers logiques.');
  const key = logicalKeys[0];
  const allRows = rowsForDossier_(sheet, key);
  if (!allRows.length) throw new Error('Dossier sélectionné introuvable.');
  const plannedRefs = new Set(allRows.map(row => display_(row, DALLY.columns.plannedConsolidation)));
  if (plannedRefs.size > 1) throw new Error('Les lignes du dossier ont des consolidations prévues différentes.');
  const namespaces = new Set(allRows.map(row => logicalDossierKey_(row.display)));
  if (namespaces.size > 1) throw new Error('Identité serveur associée à plusieurs namespaces de dossier.');
  assertNoSelectedIdentityCollision_(sheet, allRows);
  return {sheet, dossier, key, rows:allRows};
}

function ensureSourceKey_(sheet, dossier, rows) {
  const keys = rows.map(r => display_(r, DALLY.columns.syncSourceKey)).filter(Boolean);
  if (new Set(keys).size > 1) throw new Error('Les lignes du dossier ont des sync_source_key différentes.');
  if (keys.length) return keys[0];
  const planned = firstText_(rows,DALLY.columns.plannedConsolidation);
  const key = planned ? 'sheets:' + SpreadsheetApp.getActive().getId() + ':' + Utilities.getUuid() : sourceKey_(sheet.getName(), dossier, rows);
  rows.forEach(r => setCell_(sheet, r.row, DALLY.columns.syncSourceKey, key));
  rows.forEach(r => r.display[DALLY.columns.syncSourceKey - 1] = key);
  return key;
}

function sourceKey_(sheetName, dossier, rows) {
  const existing = rows.map(r => display_(r,DALLY.columns.syncSourceKey)).filter(Boolean);
  if (new Set(existing).size > 1) throw new Error('Les lignes du dossier ont des sync_source_key différentes.');
  if (existing.length) return existing[0];
  const planned = firstText_(rows,DALLY.columns.plannedConsolidation);
  return planned ? '' : 'sheets:' + sheetName + ':legacy:' + dossier;
}

function prepareArticleRows_(sheet, dossier, rows) {
  const articleRows = rows.filter(isArticleRow_);
  articleRows.forEach(row => {
    const existing = display_(row, DALLY.columns.articleKey);
    row._syncArticleKey = existing || (stableGlobalKey_(row, dossier) + '|A|' + Utilities.getUuid());
    if (!existing) setCell_(sheet, row.row, DALLY.columns.articleKey, row._syncArticleKey);
  });
  return articleRows;
}

function stableGlobalKey_(row, dossier) {
  return display_(row, DALLY.columns.globalExternalReference) || display_(row, DALLY.columns.syncSourceKey) || dossier;
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
    const currentMessage = String(sheet.getRange(row.row, DALLY.columns.syncMessage).getDisplayValue() || '').trim();
    setCell_(sheet, row.row, DALLY.columns.syncMessage, preserveReplanIntentMessage_(currentMessage, msg));
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

function sheetLiteralText_(value) {
  if (value === null || value === false || value === undefined || value === '') return '';
  const text = String(value);
  return /^[=+\-@]/.test(text) ? "'" + text : text;
}
function value_(row, column) { return row.values[column - 1]; }
function display_(row, column) { return String(row.display[column - 1] == null ? '' : row.display[column - 1]).trim(); }
function firstText_(rows, column) { for (const r of rows) { const v = display_(r, column); if (v) return v; } return ''; }
function firstNumber_(rows, column) { for (const r of rows) { const v = numberOrNull_(value_(r, column)); if (v !== null) return v; } return null; }
function sum_(rows, column) { return rows.reduce((acc, r) => acc + Number(value_(r, column) || 0), 0); }
function numberOr_(value, fallback) { const n = Number(value); return Number.isFinite(n) && n > 0 ? n : fallback; }
function numberOrNull_(value) { if (value === '' || value === null || typeof value === 'undefined') return null; const normalized = typeof value === 'string' ? value.replace(/[\s\u00A0\u202F]/g, '').replace(',', '.') : value; if (normalized === '') return null; const n = Number(normalized); return Number.isFinite(n) ? n : null; }
function dateIso_(value) { if (!value) return ''; if (value instanceof Date) return Utilities.formatDate(value, 'Etc/UTC', 'yyyy-MM-dd'); const d = new Date(value); return isNaN(d.getTime()) ? '' : Utilities.formatDate(d, 'Etc/UTC', 'yyyy-MM-dd'); }
function pruneEmptyObject_(obj) { Object.keys(obj).forEach(k => { if (!obj[k]) delete obj[k]; }); }
function errorText_(err) { return err && err.message ? err.message : String(err); }
function withScriptLock_(fn) { const lock = LockService.getScriptLock(); if (!lock.tryLock(5000)) throw new Error('Une synchronisation Dally CRM est déjà en cours.'); try { return fn(); } finally { lock.releaseLock(); } }
