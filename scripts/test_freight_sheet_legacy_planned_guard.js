'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');

class FakeRange {
  constructor(sheet, row, col, numRows = 1, numCols = 1) { this.sheet = sheet; this.row = row; this.col = col; this.numRows = numRows; this.numCols = numCols; }
  matrix() { return Array.from({length: this.numRows}, (_, r) => Array.from({length: this.numCols}, (_, c) => this.sheet.cell(this.row + r, this.col + c))); }
  getDisplayValues() { return this.matrix().map(row => row.map(value => value == null ? '' : String(value))); }
  getDisplayValue() { const value = this.sheet.cell(this.row, this.col); return value == null ? '' : String(value); }
  setValue(value) { this.sheet.setCell(this.row, this.col, value); return this; }
}

class FakeSheet {
  constructor(rows, width) { this.rows = rows.map(row => row.slice()); this.width = width; this.rows.forEach(row => { while (row.length < width) row.push(''); }); }
  getLastRow() { return this.rows.length; }
  cell(row, col) { return (this.rows[row - 1] || [])[col - 1] ?? ''; }
  setCell(row, col, value) { this.rows[row - 1][col - 1] = value; }
  getRange(row, col, numRows = 1, numCols = 1) { return new FakeRange(this, row, col, numRows, numCols); }
}

const sandbox = {console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const {DALLY, applySheetBindings_} = vm.runInContext('({DALLY, applySheetBindings_})', sandbox);
const blank = () => Array(DALLY.maxColumn).fill('');
const row = (planned, status, shipment, message = '') => {
  const value = blank();
  value[DALLY.columns.plannedConsolidation - 1] = planned;
  value[DALLY.columns.syncStatus - 1] = status;
  value[DALLY.columns.shipmentId - 1] = String(shipment);
  value[DALLY.columns.dossier - 1] = 'A002';
  value[DALLY.columns.syncMessage - 1] = message;
  return value;
};

const operationalMessage = 'Correction utilisateur 22/08/2026 : paiement à synchroniser CRM.';
const sheet = new FakeSheet([blank(), blank(), row('AIR-DSS-CDG-2026-001', 'À synchroniser', 678, operationalMessage)], DALLY.maxColumn);
applySheetBindings_(sheet, {'678': {shipment_id: 678, planned_consolidation_ref: false, requires_replan: false}});
assert.strictEqual(sheet.cell(3, DALLY.columns.plannedConsolidation), 'AIR-DSS-CDG-2026-001');
assert.strictEqual(sheet.cell(3, DALLY.columns.syncMessage), operationalMessage, 'historical refresh must preserve an operational sync message when CRM planned assignment is blank');

const explicit = new FakeSheet([blank(), blank(), row('AIR-NEW', 'À synchroniser', 679, DALLY.replanIntentMarker)], DALLY.maxColumn);
applySheetBindings_(explicit, {'679': {shipment_id: 679, planned_consolidation_ref: false, requires_replan: false}});
assert.match(String(explicit.cell(3, DALLY.columns.syncMessage)), /Replanification demandée depuis la feuille\./, 'explicit replan intent must remain visible');
assert.match(String(explicit.cell(3, DALLY.columns.syncMessage)), /Consolidation en attente/, 'explicit replan must still surface the pending CRM mismatch');

// Mixed blank/nonblank rows must not be mistaken for one coherent legacy assignment.
// The existing pending logic must harmonize the dossier instead of returning early.
const mixed = new FakeSheet([
  blank(),
  blank(),
  row('AIR-DSS-CDG-2026-001', 'À synchroniser', 680, 'Message opérationnel'),
  row('', 'À synchroniser', 680, '')
], DALLY.maxColumn);

applySheetBindings_(mixed, {
  '680': {
    shipment_id: 680,
    planned_consolidation_ref: false,
    requires_replan: false
  }
});

assert.strictEqual(
  mixed.cell(3, DALLY.columns.plannedConsolidation),
  'AIR-DSS-CDG-2026-001'
);
assert.strictEqual(
  mixed.cell(4, DALLY.columns.plannedConsolidation),
  'AIR-DSS-CDG-2026-001',
  'mixed blank/nonblank dossier must be harmonized by pending logic'
);

const authoritative = new FakeSheet([blank(), blank(), row('AIR-OLD', 'Synchronisé', 999)], DALLY.maxColumn);
applySheetBindings_(authoritative, {'999': {shipment_id: 999, planned_consolidation_ref: 'AIR-CRM', requires_replan: false}});
assert.strictEqual(authoritative.cell(3, DALLY.columns.plannedConsolidation), 'AIR-CRM');

console.log('LEGACY_PLANNED_REFRESH_GUARD=PASS');
