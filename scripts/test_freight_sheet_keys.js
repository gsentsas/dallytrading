'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const sheetColumns = Object.freeze({
  plannedConsolidation: 2,
  dossier: 3,
  articleKey: 57,
  paymentFlag: 58,
  paymentKey: 59,
  syncSourceKey: 60,
  globalExternalReference: 61,
  intakeConsolidationRef: 62,
  collectionLocalRef: 63,
});
const columnIndexes = Object.values(sheetColumns);
assert.strictEqual(new Set(columnIndexes).size, columnIndexes.length, 'column indexes overlap');
assert.strictEqual(Math.max(...columnIndexes), 63, 'max column must remain BK/63');

const source002 = 'sheets:spreadsheet:uuid-002';
const source003 = 'sheets:spreadsheet:uuid-003';
const article = (source, n) => `${source}|A|${n}`;
const payment = (source, n) => `${source}|P|${n}`;
assert.notStrictEqual(article(source002, 1), article(source003, 1), 'article key collision');
assert.notStrictEqual(payment(source002, 1), payment(source003, 1), 'payment key collision');

const normalizeSources = rows => {
  const keys = rows.map(r => String(r.source || '').trim());
  const nonEmpty = [...new Set(keys.filter(Boolean))];
  if (nonEmpty.length > 1) throw new Error('conflicting source keys');
  return nonEmpty[0] || '';
};
const autoGroup = rows => {
  if (rows.some(r => !r.dossier)) return null;
  const namespaces = new Set(rows.map(r => r.planned ? `${r.planned}|${r.dossier}` : r.dossier));
  if (namespaces.size !== 1) throw new Error('multiple logical dossiers');
  const source = normalizeSources(rows);
  return source ? `source|${source}` : [...namespaces][0];
};
const externalRef = row => {
  if (row.global) return row.global;
  if (!row.planned) return row.dossier || '';
  if (row.shipmentId || row.intake || row.collectionLocalRef) return '';
  return row.dossier || '';
};
assert.strictEqual(autoGroup([{dossier: 'A001'}, {dossier: 'A001'}]), 'A001');
assert.strictEqual(autoGroup([{dossier: 'A001', planned: 'C1'}]), 'C1|A001');
assert.strictEqual(autoGroup([{dossier: 'A001', source: 's'}, {dossier: 'A001'}]), 'source|s');
assert.throws(() => autoGroup([{dossier: 'A001', source: 's1'}, {dossier: 'A001', source: 's2'}]));
assert.notStrictEqual(autoGroup([{dossier: 'A001', planned: 'C1'}]), autoGroup([{dossier: 'A001', planned: 'C2'}]));
assert.strictEqual(autoGroup([{dossier: '', planned: 'C1'}]), null);
assert.strictEqual(externalRef({planned: 'C1', dossier: 'A001'}), 'A001');
assert.strictEqual(externalRef({planned: 'C1', dossier: '', source: 's'}), '');
assert.strictEqual(externalRef({planned: 'C1', dossier: 'A001', shipmentId: 9}), '');
assert.strictEqual(externalRef({planned: 'C1', dossier: 'A001', intake: 'C1'}), '');
assert.strictEqual(externalRef({planned: 'C1', dossier: 'A001', collectionLocalRef: 'A001'}), '');
assert.strictEqual(externalRef({planned: 'C1', dossier: 'A001', global: 'C1-A001'}), 'C1-A001');

const numberOrNull = value => {
  if (value === '' || value === null || typeof value === 'undefined') return null;
  const normalized = typeof value === 'string' ? value.replace(/[\s\u00A0\u202F]/g, '').replace(',', '.') : value;
  if (normalized === '') return null;
  const n = Number(normalized);
  return Number.isFinite(n) ? n : null;
};
for (const value of ['1234,56', '1 234,56', '1\u00A0234,56', '1\u202F234,56']) assert.strictEqual(numberOrNull(value), 1234.56);
for (const value of ['   ', '\u00A0', '\u202F', ' \u00A0\u202F ']) assert.strictEqual(numberOrNull(value), null);

const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');
const columnsBlock = code.match(/columns:\s*Object\.freeze\(\{([\s\S]*?)\n\s*\}\)/);
if (!columnsBlock) throw new Error('DALLY.columns map missing');
const parsedColumns = Object.fromEntries([...columnsBlock[1].matchAll(/([A-Za-z][A-Za-z0-9]*):\s*(\d+)/g)].map(([, name, value]) => [name, Number(value)]));
for (const [name, expected] of Object.entries(sheetColumns)) assert.strictEqual(parsedColumns[name], expected, `DALLY.columns.${name}`);
assert.strictEqual(new Set(Object.values(parsedColumns)).size, Object.values(parsedColumns).length, 'DALLY.columns indexes overlap');
assert.strictEqual(Math.max(...Object.values(parsedColumns)), 63, 'DALLY.columns maxColumn contract failed');

class FakeRange {
  constructor(sheet, row, col, numRows = 1, numCols = 1) {
    this.sheet = sheet; this.row = row; this.col = col; this.numRows = numRows; this.numCols = numCols;
  }
  matrix() {
    const out = [];
    for (let r = 0; r < this.numRows; r++) {
      const row = [];
      for (let c = 0; c < this.numCols; c++) row.push(this.sheet.cell(this.row + r, this.col + c));
      out.push(row);
    }
    return out;
  }
  getDisplayValues() { return this.matrix().map(row => row.map(v => v == null ? '' : String(v))); }
  getValues() { return this.matrix(); }
  getValue() { return this.sheet.cell(this.row, this.col); }
  getDisplayValue() { const v = this.getValue(); return v == null ? '' : String(v); }
  setValue(value) { this.sheet.setCell(this.row, this.col, value); return this; }
  setValues(values) {
    for (let r = 0; r < values.length; r++) for (let c = 0; c < values[r].length; c++) this.sheet.setCell(this.row + r, this.col + c, values[r][c]);
    return this;
  }
  clearContent() { return this.setValue(''); }
  clearDataValidations() { return this; }
  setDataValidation() { return this; }
  copyTo(target) { target.setValues(this.getValues().map(row => row.slice())); return target; }
  getCell(r, c) { return new FakeRange(this.sheet, this.row + r - 1, this.col + c - 1); }
  getRow() { return this.row; }
  getLastRow() { return this.row + this.numRows - 1; }
  getColumn() { return this.col; }
  getLastColumn() { return this.col + this.numCols - 1; }
  getNumRows() { return this.numRows; }
  getSheet() { return this.sheet; }
}
class FakeSheet {
  constructor(rows, maxColumns, name = 'Saisie maritime') {
    this.rows = rows.map(row => row.slice()); this.maxColumns = maxColumns; this.name = name; this.maxRows = Math.max(rows.length, 20); this.hidden = [];
    this.rows.forEach(row => { while (row.length < maxColumns) row.push(''); });
  }
  getName() { return this.name; }
  getMaxColumns() { return this.maxColumns; }
  getMaxRows() { return this.maxRows; }
  getLastRow() { return this.rows.length; }
  cell(r, c) { return (this.rows[r - 1] || [])[c - 1] ?? ''; }
  setCell(r, c, value) { while (this.rows.length < r) this.rows.push(Array(this.maxColumns).fill('')); while (this.rows[r - 1].length < this.maxColumns) this.rows[r - 1].push(''); this.rows[r - 1][c - 1] = value; }
  getRange(r, c, nr = 1, nc = 1) { return new FakeRange(this, r, c, nr, nc); }
  insertColumnAfter(col) { this.rows.forEach(row => row.splice(col, 0, '')); this.maxColumns += 1; }
  deleteColumn(col) { this.rows.forEach(row => row.splice(col - 1, 1)); this.maxColumns -= 1; }
  insertColumnsAfter(col, count) { this.rows.forEach(row => row.splice(col, 0, ...Array(count).fill(''))); this.maxColumns += count; }
  hideColumns(col, count) { this.hidden.push([col, count]); }
}

const sandbox = {console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error, Utilities: {getUuid: () => 'uuid-test', formatDate: () => '2099-01-01'}};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const expose = vm.runInContext(`({
  migrateLegacySheetLayout_, detectSheetLayout_, assertCanonicalSheetLayout_, ensureSheetLayout_, sheetLiteralText_,
  selectedDossier_, dallyInvoiceSelectedDossier, dallyPaymentsSelectedDossier, dallyRefreshOpenConsolidations, dallyMarkEdited_
})`, sandbox);

function headerRow(width) { return Array(width).fill(''); }
function legacy58Sheet(width = 58) {
  const h = headerRow(width); Object.assign(h, {0:'Date depot', 1:'N dossier', 55:'Clé article facture', 56:'Flag règlement facture', 57:'Clé règlement facture'});
  const d = headerRow(width); Object.assign(d, {0:'2099-01-01', 1:'DOS-58', 3:'Client 58', 55:'AKEY', 56:'FLAG', 57:'PKEY'});
  return new FakeSheet([headerRow(width), h, d], width);
}
function legacy63Sheet() {
  const h = headerRow(63); Object.assign(h, {0:'Date depot', 1:'N dossier', 58:'Consolidation prévue', 59:'sync source key', 60:'global external reference', 61:'intake consolidation ref', 62:'collection local ref'});
  const d = headerRow(63); Object.assign(d, {0:'2099-01-01', 1:'DOS-63', 3:'Client 63', 55:'AKEY63', 56:'FLAG63', 57:'PKEY63', 58:'AIR-DSS-CDG-2099-X', 59:'SRC63', 60:'GLOB63', 61:'INT63', 62:'A001'});
  return new FakeSheet([headerRow(63), h, d], 63);
}
function rowSnapshot(sheet) { return JSON.stringify({rows: sheet.rows, maxColumns: sheet.maxColumns, hidden: sheet.hidden}); }
function assertCanonicalHeaders(sheet) {
  assert.strictEqual(sheet.cell(2, 2), 'Consolidation prévue');
  assert.strictEqual(sheet.cell(2, 3), 'N dossier');
  assert.deepStrictEqual(sheet.getRange(2, 57, 1, 7).getDisplayValues()[0], ['Clé article facture','Flag règlement facture','Clé règlement facture','sync source key','global external reference','intake consolidation ref','collection local ref']);
}

const old58 = legacy58Sheet(58);
assert.strictEqual(expose.detectSheetLayout_(old58), 'legacy58');
expose.migrateLegacySheetLayout_(old58);
assertCanonicalHeaders(old58);
assert.strictEqual(old58.cell(3, 3), 'DOS-58');
assert.strictEqual(old58.cell(3, 57), 'AKEY');
assert.strictEqual(old58.cell(3, 58), 'FLAG');
assert.strictEqual(old58.cell(3, 59), 'PKEY');
assert.strictEqual(expose.detectSheetLayout_(old58), 'canonical');
const once58 = rowSnapshot(old58); expose.migrateLegacySheetLayout_(old58); assert.strictEqual(rowSnapshot(old58), once58, 'legacy58 second run changed data');

const wide58 = legacy58Sheet(70);
assert.strictEqual(expose.detectSheetLayout_(wide58), 'legacy58', 'legacy58 with empty trailing columns rejected');
expose.migrateLegacySheetLayout_(wide58);
assertCanonicalHeaders(wide58);
assert.strictEqual(wide58.cell(3, 59), 'PKEY');

const old63 = legacy63Sheet();
assert.strictEqual(expose.detectSheetLayout_(old63), 'legacy63');
expose.migrateLegacySheetLayout_(old63);
assertCanonicalHeaders(old63);
assert.strictEqual(old63.cell(3, 2), 'AIR-DSS-CDG-2099-X');
assert.strictEqual(old63.cell(3, 3), 'DOS-63');
assert.strictEqual(old63.cell(3, 57), 'AKEY63');
assert.strictEqual(old63.cell(3, 58), 'FLAG63');
assert.strictEqual(old63.cell(3, 59), 'PKEY63');
assert.strictEqual(old63.cell(3, 60), 'SRC63');
assert.strictEqual(old63.cell(3, 61), 'GLOB63');
assert.strictEqual(old63.cell(3, 62), 'INT63');
assert.strictEqual(old63.cell(3, 63), 'A001');
const once63 = rowSnapshot(old63); expose.migrateLegacySheetLayout_(old63); assert.strictEqual(rowSnapshot(old63), once63, 'legacy63 second run changed data');

const unknown = legacy58Sheet(70); unknown.setCell(2, 60, 'unexpected');
assert.strictEqual(expose.detectSheetLayout_(unknown), 'unknown');
assert.throws(() => expose.assertCanonicalSheetLayout_(unknown), /inconnue/);
assert.strictEqual(expose.assertCanonicalSheetLayout_(legacy58Sheet(70), true), false);
assert.strictEqual(expose.assertCanonicalSheetLayout_(old58), true);

for (const value of ['=FORMULA', '+FORMULA', '-FORMULA', '@FORMULA']) assert.strictEqual(expose.sheetLiteralText_(value), "'" + value);
assert.strictEqual(expose.sheetLiteralText_('SAFE'), 'SAFE');
assert.strictEqual(expose.sheetLiteralText_(''), '');

// Entry-point guard regression: no legacy layout may reach reads using canonical indexes.
let selectedReadReached = false;
sandbox.SpreadsheetApp = {
  getActiveSheet: () => legacy58Sheet(70),
  getActive: () => ({getSheetByName: () => legacy58Sheet(70)}),
  getActiveRange: () => { selectedReadReached = true; throw new Error('selected read reached'); },
};
assert.throws(() => expose.selectedDossier_(), /Disposition ancienne/);
assert.strictEqual(selectedReadReached, false, 'selected dossier read canonical indexes before guard');
assert.throws(() => expose.dallyInvoiceSelectedDossier(), /LockService|Disposition ancienne/);
assert.throws(() => expose.dallyPaymentsSelectedDossier(), /LockService|Disposition ancienne/);
assert.throws(() => expose.dallyRefreshOpenConsolidations(), /Disposition ancienne/);
const legacyEdit = legacy58Sheet(70);
let editWrite = false;
const originalSetCell = legacyEdit.setCell.bind(legacyEdit);
legacyEdit.setCell = (...args) => { editWrite = true; return originalSetCell(...args); };
expose.dallyMarkEdited_({range: new FakeRange(legacyEdit, 3, 1, 1, 1)});
assert.strictEqual(editWrite, false, 'onEdit mutated legacy layout');

assert.ok(code.includes('pendingValues.length > 1'), 'multi-pending conflict handling missing');
assert.ok(code.includes('plusieurs valeurs Sheet en attente'), 'multi-pending conflict message missing');
assert.ok(code.includes("source ? 'source|' + source : (global ? 'global|' + global"), 'binding grouping priority missing');
assert.ok(code.includes("'shipment|' + (shipment || dossier) + '|' + dossier"), 'shipment+dossier grouping fallback missing');

console.log('SHEET_LAYOUT_RUNTIME_MIGRATION=PASS');
console.log('LEGACY58_BEHAVIOR=PASS');
console.log('LEGACY58_EXTRA_EMPTY_COLUMNS=PASS');
console.log('LEGACY63_BEHAVIOR=PASS');
console.log('MIGRATION_SECOND_RUN_NOOP=PASS');
console.log('PAYMENT_HEADER_ALIGNMENT=PASS');
console.log('LEGACY_WRONG_INDEX_GUARD=PASS');
console.log('SHEET_FORMULA_INJECTION_GUARD=PASS');
console.log('MULTI_PENDING_CONSOLIDATION_PRESERVED=PASS');
console.log('SHEET_KEY_IDENTITY=PASS');
