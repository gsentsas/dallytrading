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
const row = (planned, status, shipment) => { const value = blank(); value[DALLY.columns.plannedConsolidation - 1] = planned; value[DALLY.columns.syncStatus - 1] = status; value[DALLY.columns.shipmentId - 1] = String(shipment); value[DALLY.columns.dossier - 1] = 'A002'; return value; };

const sheet = new FakeSheet([blank(), blank(), row('AIR-DSS-CDG-2026-001', 'Synchronisé', 678)], DALLY.maxColumn);
sheet.rows[2][DALLY.columns.syncMessage - 1] = 'CRM OK • tarif automatic';
applySheetBindings_(sheet, {'678': {shipment_id: 678, planned_consolidation_ref: false, requires_replan: false}});
assert.strictEqual(sheet.cell(3, DALLY.columns.plannedConsolidation), 'AIR-DSS-CDG-2026-001');
assert.strictEqual(sheet.cell(3, DALLY.columns.syncMessage), 'CRM OK • tarif automatic');

const authoritative = new FakeSheet([blank(), blank(), row('AIR-OLD', 'Synchronisé', 999)], DALLY.maxColumn);
applySheetBindings_(authoritative, {'999': {shipment_id: 999, planned_consolidation_ref: 'AIR-CRM', requires_replan: false}});
assert.strictEqual(authoritative.cell(3, DALLY.columns.plannedConsolidation), 'AIR-CRM');

console.log('LEGACY_PLANNED_REFRESH_GUARD=PASS');
