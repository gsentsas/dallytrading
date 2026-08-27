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
  setValues(values) {
    for (let r = 0; r < values.length; r++) {
      for (let c = 0; c < values[r].length; c++) this.sheet.setCell(this.row + r, this.col + c, values[r][c]);
    }
    return this;
  }
  getCell(r, c) { return new FakeRange(this.sheet, this.row + r - 1, this.col + c - 1); }
  clearContent() { return this; }
  clearDataValidations() { return this; }
  setDataValidation() { return this; }
}

class FakeSheet {
  constructor(width = 10, rows = 3, name = 'Saisie maritime') {
    this.maxColumns = width;
    this.maxRows = Math.max(rows, 20);
    this.name = name;
    this.rows = Array.from({length: rows}, () => Array(width).fill(''));
    this.hidden = [];
  }

  getName() { return this.name; }
  getMaxColumns() { return this.maxColumns; }
  getMaxRows() { return this.maxRows; }
  getLastRow() { return this.rows.length; }
  cell(row, col) { return (this.rows[row - 1] || [])[col - 1] ?? ''; }
  setCell(row, col, value) {
    while (this.rows.length < row) this.rows.push(Array(this.maxColumns).fill(''));
    while (this.rows[row - 1].length < this.maxColumns) this.rows[row - 1].push('');
    this.rows[row - 1][col - 1] = value;
  }
  getRange(row, col, numRows = 1, numCols = 1) { return new FakeRange(this, row, col, numRows, numCols); }
  insertColumnsAfter(col, count) {
    this.rows.forEach(row => row.splice(col, 0, ...Array(count).fill('')));
    this.maxColumns += count;
  }
  insertColumnAfter(col) {
    this.rows.forEach(row => row.splice(col, 0, ''));
    this.maxColumns += 1;
  }
  deleteColumn(col) {
    this.rows.forEach(row => row.splice(col - 1, 1));
    this.maxColumns -= 1;
  }
  hideColumns(col, count) { this.hidden.push([col, count]); }
}

const sandbox = {console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const expose = vm.runInContext('({DALLY, detectSheetLayout_, ensureSheetLayout_, dallyRefreshOpenConsolidations})', sandbox);
const columns = expose.DALLY.columns;

const emptySheet = new FakeSheet(10, 3);
assert.strictEqual(expose.detectSheetLayout_(emptySheet), 'empty', 'blank input must start as empty');
expose.ensureSheetLayout_(emptySheet);
assert.strictEqual(emptySheet.getMaxColumns(), expose.DALLY.maxColumn, 'empty sheet was not expanded to the canonical width');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.depositDate), 'Date depot');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.plannedConsolidation), 'Consolidation prévue');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.dossier), 'N dossier');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.articleKey), 'Clé article facture');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.paymentFlag), 'Flag règlement facture');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.paymentKey), 'Clé règlement facture');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.syncSourceKey), 'sync source key');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.globalExternalReference), 'global external reference');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.intakeConsolidationRef), 'intake consolidation ref');
assert.strictEqual(emptySheet.cell(expose.DALLY.headerRow, columns.collectionLocalRef), 'collection local ref');
assert.strictEqual(expose.detectSheetLayout_(emptySheet), 'canonical', 'setup left an empty sheet unusable');

const configRange = {
  clearContent() { return this; },
  setValues() { return this; },
};
const configSheet = {
  getMaxRows: () => 30,
  getRange: () => configRange,
};
const active = {
  getSheetByName: () => null,
  toast: () => {},
};
sandbox.SpreadsheetApp = {getActive: () => active};
vm.runInContext(`
  readConfig_ = () => ({routes: {}});
  apiGet_ = () => ({consolidations: []});
  fetchSheetBindings_ = () => ({});
  ensureConfigSheet_ = () => configSheetStub;
  withScriptLock_ = fn => fn();
`, vm.createContext ? sandbox : sandbox);
sandbox.configSheetStub = configSheet;
// Rebind after exposing the stub object to the context.
vm.runInContext('ensureConfigSheet_ = () => configSheetStub;', sandbox);

assert.doesNotThrow(
  () => expose.dallyRefreshOpenConsolidations(),
  'refresh must ignore optional data sheets that are currently absent',
);

console.log('EMPTY_LAYOUT_INITIALIZATION=PASS');
console.log('MISSING_SHEET_REFRESH_GUARD=PASS');
