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

  getDisplayValues() {
    const snapshot = this.matrix().map(row => row.map(value => value == null ? '' : String(value)));
    if (this.row === 3 && this.col === 1 && this.numCols === 63 && !this.sheet.raceInjected) {
      this.sheet.raceInjected = true;
      this.sheet.setCell(3, 2, 'AIR-USER');
    }
    return snapshot;
  }

  getDisplayValue() {
    const value = this.sheet.cell(this.row, this.col);
    return value == null ? '' : String(value);
  }

  setValue(value) {
    this.sheet.setCell(this.row, this.col, value);
    return this;
  }
}

class FakeSheet {
  constructor(rows, width) {
    this.rows = rows.map(row => row.slice());
    this.width = width;
    this.raceInjected = false;
    this.rows.forEach(row => { while (row.length < width) row.push(''); });
  }

  getLastRow() { return this.rows.length; }
  cell(row, col) { return (this.rows[row - 1] || [])[col - 1] ?? ''; }
  setCell(row, col, value) { this.rows[row - 1][col - 1] = value; }
  getRange(row, col, numRows = 1, numCols = 1) { return new FakeRange(this, row, col, numRows, numCols); }
}

const sandbox = {console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const expose = vm.runInContext('({DALLY, applySheetBindings_})', sandbox);
const columns = expose.DALLY.columns;
const width = expose.DALLY.maxColumn;
const blank = () => Array(width).fill('');
const row = blank();
row[columns.plannedConsolidation - 1] = 'AIR-OLD';
row[columns.dossier - 1] = 'DOS-RACE';
row[columns.syncStatus - 1] = 'Synchronisé';
row[columns.shipmentId - 1] = '42';
row[columns.syncSourceKey - 1] = 'SRC-RACE';

const sheet = new FakeSheet([blank(), blank(), row], width);
expose.applySheetBindings_(sheet, {
  '42': {shipment_id: 42, planned_consolidation_ref: 'AIR-CRM', requires_replan: false},
});

assert.strictEqual(sheet.cell(3, columns.plannedConsolidation), 'AIR-USER', 'refresh overwrote a Sheet edit made after its snapshot');
assert.strictEqual(sheet.cell(3, columns.syncStatus), 'Synchronisé', 'test must not rely on onEdit having updated sync status');
assert.match(String(sheet.cell(3, columns.syncMessage)), /Modification Sheet détectée/, 'refresh must surface the concurrent edit instead of silently overwriting it');

console.log('REFRESH_CONCURRENT_EDIT_PRESERVED=PASS');
