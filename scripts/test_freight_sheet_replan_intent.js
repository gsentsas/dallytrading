'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');

class FakeRange {
  constructor(sheet, row, col, numRows = 1, numCols = 1) {
    this.sheet = sheet;
    this.row = row;
    this.col = col;
    this.numRows = numRows;
    this.numCols = numCols;
  }

  matrix() {
    const out = [];
    for (let r = 0; r < this.numRows; r++) {
      const current = [];
      for (let c = 0; c < this.numCols; c++) current.push(this.sheet.cell(this.row + r, this.col + c));
      out.push(current);
    }
    return out;
  }

  getDisplayValues() { return this.matrix().map(row => row.map(value => value == null ? '' : String(value))); }
  getValues() { return this.matrix(); }
  getValue() { return this.sheet.cell(this.row, this.col); }
  getDisplayValue() { const value = this.getValue(); return value == null ? '' : String(value); }
  setValue(value) { this.sheet.setCell(this.row, this.col, value); return this; }
  clearContent() { this.sheet.setCell(this.row, this.col, ''); return this; }
}

class FakeSheet {
  constructor(width = 63, rows = 3, name = 'Saisie maritime') {
    this.width = width;
    this.name = name;
    this.rows = Array.from({length: rows}, () => Array(width).fill(''));
  }

  getName() { return this.name; }
  getMaxColumns() { return this.width; }
  getLastRow() { return this.rows.length; }
  cell(row, col) { return (this.rows[row - 1] || [])[col - 1] ?? ''; }
  setCell(row, col, value) { this.rows[row - 1][col - 1] = value; }
  getRange(row, col, numRows = 1, numCols = 1) { return new FakeRange(this, row, col, numRows, numCols); }
}

class EventRange {
  constructor(sheet, row, col, numRows = 1, numCols = 1) {
    this.sheet = sheet;
    this.row = row;
    this.col = col;
    this.numRows = numRows;
    this.numCols = numCols;
  }

  getSheet() { return this.sheet; }
  getRow() { return this.row; }
  getLastRow() { return this.row + this.numRows - 1; }
  getColumn() { return this.col; }
  getLastColumn() { return this.col + this.numCols - 1; }
}

const sandbox = {console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const expose = vm.runInContext('({DALLY, dallyMarkEdited_, buildFreightPayload_, applySheetBindings_})', sandbox);
const DALLY = expose.DALLY;
const columns = DALLY.columns;
const width = DALLY.maxColumn;

function setCanonicalHeader(sheet) {
  sheet.setCell(DALLY.headerRow, columns.depositDate, 'Date depot');
  sheet.setCell(DALLY.headerRow, columns.plannedConsolidation, 'Consolidation prévue');
  sheet.setCell(DALLY.headerRow, columns.dossier, 'N dossier');
  sheet.setCell(DALLY.headerRow, columns.articleKey, 'Clé article facture');
  sheet.setCell(DALLY.headerRow, columns.paymentFlag, 'Flag règlement facture');
  sheet.setCell(DALLY.headerRow, columns.paymentKey, 'Clé règlement facture');
  sheet.setCell(DALLY.headerRow, columns.syncSourceKey, 'sync source key');
  sheet.setCell(DALLY.headerRow, columns.globalExternalReference, 'global external reference');
  sheet.setCell(DALLY.headerRow, columns.intakeConsolidationRef, 'intake consolidation ref');
  sheet.setCell(DALLY.headerRow, columns.collectionLocalRef, 'collection local ref');
}

function makeRow({planned, dossier = 'A001', shipmentId = '', source = '', global = '', intake = '', local = '', message = ''}) {
  const values = Array(width).fill('');
  const display = Array(width).fill('');
  const put = (column, value, raw = value) => {
    values[column - 1] = raw;
    display[column - 1] = value == null ? '' : String(value);
  };
  put(columns.plannedConsolidation, planned || '');
  put(columns.dossier, dossier);
  put(columns.client, 'Client test');
  put(columns.description, 'Colis test');
  put(columns.quantity, '1', 1);
  put(columns.syncMessage, message);
  put(columns.syncSourceKey, source);
  put(columns.globalExternalReference, global);
  put(columns.intakeConsolidationRef, intake);
  put(columns.collectionLocalRef, local);
  put(columns.shipmentId, shipmentId ? String(shipmentId) : '', shipmentId || '');
  return {row: 3, values, display, _syncArticleKey: 'ART-1'};
}

const cfg = {
  migrationMode: false,
  routes: {
    'Saisie maritime': {
      mode: 'sea', direction: 'export',
      originCountry: 'SN', originCity: 'Dakar',
      destinationCountry: 'FR', destinationCity: 'Paris',
    },
  },
};

// An existing server-identified dossier must not send a visible planned value
// back to CRM after an unrelated edit. This is the stale-replan bounce guard.
const staleExisting = makeRow({
  planned: 'SEA-STALE', shipmentId: 42, source: 'SRC-42', global: 'GLOB-42',
});
const stalePayload = expose.buildFreightPayload_('Saisie maritime', 'A001', [staleExisting], [staleExisting], cfg);
assert.ok(!Object.prototype.hasOwnProperty.call(stalePayload, 'planned_consolidation_ref'), 'ordinary sync can still overwrite a newer CRM replan');

// Explicit column-B intent restores bidirectional replanning for an existing dossier.
const explicitExisting = makeRow({
  planned: 'SEA-USER', shipmentId: 42, source: 'SRC-42', global: 'GLOB-42',
  message: DALLY.replanIntentMarker,
});
const explicitPayload = expose.buildFreightPayload_('Saisie maritime', 'A001', [explicitExisting], [explicitExisting], cfg);
assert.strictEqual(explicitPayload.planned_consolidation_ref, 'SEA-USER', 'explicit Sheet replan was not sent to CRM');

// New/unbound planned dossiers must keep sending their selected consolidation.
const newDossier = makeRow({planned: 'SEA-NEW', dossier: 'A001', source: 'SRC-NEW'});
const newPayload = expose.buildFreightPayload_('Saisie maritime', 'A001', [newDossier], [newDossier], cfg);
assert.strictEqual(newPayload.planned_consolidation_ref, 'SEA-NEW', 'new planned dossier lost its initial consolidation');

// onEdit must create the explicit intent only when column B is actually edited,
// and a later unrelated edit must not erase that intent before sync.
const editSheet = new FakeSheet();
setCanonicalHeader(editSheet);
editSheet.setCell(3, columns.plannedConsolidation, 'SEA-USER');
editSheet.setCell(3, columns.dossier, 'A001');
editSheet.setCell(3, columns.shipmentId, '42');
editSheet.setCell(3, columns.syncSourceKey, 'SRC-42');
expose.dallyMarkEdited_({range: new EventRange(editSheet, 3, columns.plannedConsolidation)});
assert.strictEqual(editSheet.cell(3, columns.syncStatus), 'À synchroniser');
assert.strictEqual(editSheet.cell(3, columns.syncMessage), DALLY.replanIntentMarker, 'column-B edit did not mark explicit replan intent');
expose.dallyMarkEdited_({range: new EventRange(editSheet, 3, columns.client)});
assert.strictEqual(editSheet.cell(3, columns.syncMessage), DALLY.replanIntentMarker, 'unrelated edit erased explicit replan intent');

// A refresh while the explicit replan is pending may explain the CRM/Sheet
// mismatch, but it must retain the machine-readable intent prefix.
expose.applySheetBindings_(editSheet, {
  '42': {shipment_id: 42, planned_consolidation_ref: 'SEA-CRM', requires_replan: false},
});
assert.match(String(editSheet.cell(3, columns.syncMessage)), /^Replanification demandée depuis la feuille\./, 'refresh erased explicit replan intent');
assert.strictEqual(editSheet.cell(3, columns.plannedConsolidation), 'SEA-USER', 'refresh overwrote explicit pending replan');

console.log('STALE_CRM_REPLAN_BOUNCE_GUARD=PASS');
console.log('EXPLICIT_REPLAN_INTENT=PASS');
console.log('NEW_DOSSIER_PLANNED_REF=PASS');
console.log('REPLAN_INTENT_REFRESH_PRESERVED=PASS');
