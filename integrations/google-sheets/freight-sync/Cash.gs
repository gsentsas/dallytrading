/* DallyTrading Freight — internal cash connector.
 * Loaded in the same bound Apps Script project as Code.gs.
 */

const DALLY_CASH = Object.freeze({
  expenseSheet: 'Dépenses',
  transferSheet: 'Transferts caisse',
  firstRow: 3,
  expense: Object.freeze({
    key: 1, date: 2, category: 3, description: 4, beneficiary: 5,
    gilles: 6, alain: 7, dalanda: 8, total: 9, currency: 10,
    totalEur: 11, totalXof: 12, method: 13, reference: 14, state: 15,
    comment: 16, syncStatus: 17, odooId: 18, lastSync: 19, syncMessage: 20,
  }),
  transfer: Object.freeze({
    key: 1, date: 2, fromActor: 3, toActor: 4, amount: 5, currency: 6,
    totalEur: 7, totalXof: 8, reason: 9, method: 10, state: 11, comment: 12,
    syncStatus: 13, odooId: 14, lastSync: 15, syncMessage: 16,
  }),
  stateCodes: Object.freeze({
    'Validé': 'validated', 'Valide': 'validated',
    'À vérifier': 'review', 'A verifier': 'review', 'A vérifier': 'review',
    'Annulé': 'cancelled', 'Annule': 'cancelled',
  }),
});

function dallyCashSetup() {
  ensureCashOutputHeaders_();
  installCashTriggers_();
  SpreadsheetApp.getActive().toast('Synchronisation Dépenses / Transferts caisse initialisée.', 'Dally Caisse', 7);
}

function dallyCashOnOpen_() {
  SpreadsheetApp.getUi()
    .createMenu('Dally Caisse')
    .addItem('Initialiser les déclencheurs caisse', 'dallyCashSetup')
    .addSeparator()
    .addItem('Synchroniser les écritures en attente', 'dallyCashSyncPending')
    .addItem('Synchroniser la ligne sélectionnée', 'dallyCashSyncSelected')
    .addItem('Marquer toutes les écritures', 'dallyCashMarkAll')
    .addToUi();
}

function installCashTriggers_() {
  const ss = SpreadsheetApp.getActive();
  const handlers = new Set(['dallyMarkCashEdited_', 'dallyScheduledCashSync_', 'dallyCashOnOpen_']);
  ScriptApp.getProjectTriggers().forEach(t => {
    if (handlers.has(t.getHandlerFunction())) ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('dallyMarkCashEdited_').forSpreadsheet(ss).onEdit().create();
  ScriptApp.newTrigger('dallyCashOnOpen_').forSpreadsheet(ss).onOpen().create();
  ScriptApp.newTrigger('dallyScheduledCashSync_').timeBased().everyMinutes(1).create();
}

function ensureCashOutputHeaders_() {
  const ss = SpreadsheetApp.getActive();
  const expense = ss.getSheetByName(DALLY_CASH.expenseSheet);
  const transfer = ss.getSheetByName(DALLY_CASH.transferSheet);
  if (expense) {
    expense.getRange(2, 17, 1, 4).setValues([[
      'Statut synchro CRM', 'Odoo Expense ID', 'Dernière synchro CRM', 'Message synchro CRM'
    ]]);
  }
  if (transfer) {
    transfer.getRange(2, 13, 1, 4).setValues([[
      'Statut synchro CRM', 'Odoo Transfer ID', 'Dernière synchro CRM', 'Message synchro CRM'
    ]]);
  }
}

function dallyMarkCashEdited_(e) {
  if (!e || !e.range) return;
  const sh = e.range.getSheet();
  const name = sh.getName();
  const schema = name === DALLY_CASH.expenseSheet ? DALLY_CASH.expense :
    (name === DALLY_CASH.transferSheet ? DALLY_CASH.transfer : null);
  if (!schema) return;
  if (e.range.getLastRow() < DALLY_CASH.firstRow) return;
  // Ignore edits made only inside CRM output columns.
  if (e.range.getColumn() >= schema.syncStatus && e.range.getLastColumn() <= schema.syncMessage) return;
  const first = Math.max(DALLY_CASH.firstRow, e.range.getRow());
  for (let row = first; row <= e.range.getLastRow(); row++) {
    if (String(sh.getRange(row, schema.key).getDisplayValue() || '').trim()) {
      sh.getRange(row, schema.syncStatus).setValue('À synchroniser');
      sh.getRange(row, schema.syncMessage).clearContent();
    }
  }
}

function dallyScheduledCashSync_() {
  const cfg = readConfig_();
  if (!cfg.autoSync) return;
  withScriptLock_(() => syncCashPending_(cfg, false));
}

function dallyCashSyncPending() {
  withScriptLock_(() => syncCashPending_(readConfig_(), true));
}

function dallyCashMarkAll() {
  const ss = SpreadsheetApp.getActive();
  [
    [DALLY_CASH.expenseSheet, DALLY_CASH.expense],
    [DALLY_CASH.transferSheet, DALLY_CASH.transfer],
  ].forEach(([name, schema]) => {
    const sh = ss.getSheetByName(name);
    if (!sh || sh.getLastRow() < DALLY_CASH.firstRow) return;
    for (let r = DALLY_CASH.firstRow; r <= sh.getLastRow(); r++) {
      if (String(sh.getRange(r, schema.key).getDisplayValue() || '').trim()) {
        sh.getRange(r, schema.syncStatus).setValue('À synchroniser');
      }
    }
  });
  ss.toast('Toutes les écritures de caisse renseignées sont marquées.', 'Dally Caisse', 6);
}

function dallyCashSyncSelected() {
  withScriptLock_(() => {
    const sh = SpreadsheetApp.getActiveSheet();
    const row = SpreadsheetApp.getActiveRange().getRow();
    if (row < DALLY_CASH.firstRow) throw new Error('Sélectionnez une ligne de données.');
    if (sh.getName() === DALLY_CASH.expenseSheet) syncExpenseRow_(sh, row, readConfig_());
    else if (sh.getName() === DALLY_CASH.transferSheet) syncTransferRow_(sh, row, readConfig_());
    else throw new Error('Sélectionnez une ligne dans Dépenses ou Transferts caisse.');
  });
}

function syncCashPending_(cfg, manual) {
  const ss = SpreadsheetApp.getActive();
  let remaining = Math.max(1, Number(cfg.maxDossiers || 10));
  let count = 0;
  const expense = ss.getSheetByName(DALLY_CASH.expenseSheet);
  const transfer = ss.getSheetByName(DALLY_CASH.transferSheet);
  if (expense) {
    for (let r = DALLY_CASH.firstRow; r <= expense.getLastRow() && remaining > 0; r++) {
      if (expense.getRange(r, DALLY_CASH.expense.syncStatus).getDisplayValue() !== 'À synchroniser') continue;
      try { syncExpenseRow_(expense, r, cfg); count++; } catch (err) { cashError_(expense, r, DALLY_CASH.expense, err); }
      remaining--;
    }
  }
  if (transfer) {
    for (let r = DALLY_CASH.firstRow; r <= transfer.getLastRow() && remaining > 0; r++) {
      if (transfer.getRange(r, DALLY_CASH.transfer.syncStatus).getDisplayValue() !== 'À synchroniser') continue;
      try { syncTransferRow_(transfer, r, cfg); count++; } catch (err) { cashError_(transfer, r, DALLY_CASH.transfer, err); }
      remaining--;
    }
  }
  if (manual) ss.toast(count + ' écriture(s) de caisse synchronisée(s).', 'Dally Caisse', 6);
}

function syncExpenseRow_(sh, row, cfg) {
  const c = DALLY_CASH.expense;
  const values = sh.getRange(row, 1, 1, c.comment).getValues()[0];
  const display = sh.getRange(row, 1, 1, c.comment).getDisplayValues()[0];
  const get = col => values[col - 1];
  const text = col => String(display[col - 1] || '').trim();
  const key = text(c.key);
  if (!key) throw new Error('ID dépense manquant');
  const allocations = [];
  [[c.gilles, 'Gilles'], [c.alain, 'Alain'], [c.dalanda, 'Dalanda']].forEach(([col, actor]) => {
    const amount = Number(get(col) || 0);
    if (amount > 0) allocations.push({actor: actor, amount: amount});
  });
  if (!allocations.length) throw new Error('Aucun montant saisi pour Gilles, Alain ou Dalanda');
  const payload = {
    external_expense_key: key,
    expense_date: dateIso_(get(c.date)),
    category: text(c.category),
    description: text(c.description),
    beneficiary: text(c.beneficiary),
    currency_code: cashCurrency_(text(c.currency)),
    total_eur_snapshot: numberOrNull_(get(c.totalEur)),
    total_xof_snapshot: numberOrNull_(get(c.totalXof)),
    payment_method: text(c.method),
    reference: text(c.reference),
    state: cashState_(text(c.state)),
    comment: text(c.comment),
    source: cfg.migrationMode ? 'legacy_xlsx' : 'google_sheets',
    allocations: allocations,
  };
  const data = apiPost_('/api/v1/freight/expense', 'DALLY_FREIGHT_BILLING_API_KEY', payload, cfg);
  sh.getRange(row, c.syncStatus).setValue('Synchronisé');
  sh.getRange(row, c.odooId).setValue(data.expense_id || '');
  sh.getRange(row, c.lastSync).setValue(new Date());
  sh.getRange(row, c.syncMessage).setValue('CRM OK • ' + data.state + ' • ' + data.total_amount + ' ' + data.currency);
  return data;
}

function syncTransferRow_(sh, row, cfg) {
  const c = DALLY_CASH.transfer;
  const values = sh.getRange(row, 1, 1, c.comment).getValues()[0];
  const display = sh.getRange(row, 1, 1, c.comment).getDisplayValues()[0];
  const get = col => values[col - 1];
  const text = col => String(display[col - 1] || '').trim();
  const key = text(c.key);
  if (!key) throw new Error('ID transfert manquant');
  const payload = {
    external_transfer_key: key,
    transfer_date: dateIso_(get(c.date)),
    from_actor: text(c.fromActor),
    to_actor: text(c.toActor),
    amount: Number(get(c.amount) || 0),
    currency_code: cashCurrency_(text(c.currency)),
    total_eur_snapshot: numberOrNull_(get(c.totalEur)),
    total_xof_snapshot: numberOrNull_(get(c.totalXof)),
    reason: text(c.reason),
    payment_method: text(c.method),
    state: cashState_(text(c.state)),
    comment: text(c.comment),
    source: cfg.migrationMode ? 'legacy_xlsx' : 'google_sheets',
  };
  const data = apiPost_('/api/v1/freight/cash-transfer', 'DALLY_FREIGHT_BILLING_API_KEY', payload, cfg);
  sh.getRange(row, c.syncStatus).setValue('Synchronisé');
  sh.getRange(row, c.odooId).setValue(data.transfer_id || '');
  sh.getRange(row, c.lastSync).setValue(new Date());
  sh.getRange(row, c.syncMessage).setValue('CRM OK • ' + data.state + ' • ' + data.amount + ' ' + data.currency);
  return data;
}

function cashError_(sh, row, schema, err) {
  sh.getRange(row, schema.syncStatus).setValue('Erreur');
  sh.getRange(row, schema.lastSync).setValue(new Date());
  sh.getRange(row, schema.syncMessage).setValue(errorText_(err).slice(0, 500));
}

function cashCurrency_(label) {
  const value = String(label || '').trim().toUpperCase();
  if (value === 'EUR') return 'EUR';
  if (value === 'FCFA' || value === 'XOF' || value === 'CFA') return 'XOF';
  throw new Error('Devise caisse non mappée: ' + label);
}

function cashState_(label) {
  if (!label) return 'review';
  const code = DALLY_CASH.stateCodes[String(label).trim()];
  if (!code) throw new Error('Statut caisse non mappé: ' + label);
  return code;
}
