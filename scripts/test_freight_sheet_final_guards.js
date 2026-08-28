'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');
const sandbox = {console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const expose = vm.runInContext('({DALLY, dallyRefreshOpenConsolidations, selectedDossier_})', sandbox);
const DALLY = expose.DALLY;
const columns = DALLY.columns;
const width = DALLY.maxColumn;

class NoopRange {
  clearContent() { return this; }
  setValues() { return this; }
  clearDataValidations() { return this; }
  setDataValidation() { return this; }
  getDisplayValues() { return []; }
}

class RefreshSheet {
  constructor(name) { this.name = name; }
  getName() { return this.name; }
  getLastRow() { return DALLY.firstDataRow - 1; }
  getMaxRows() { return 20; }
  getRange() { return new NoopRange(); }
}

const refreshSheets = Object.fromEntries(DALLY.dataSheets.map(name => [name, new RefreshSheet(name)]));
const configSheet = {
  getMaxRows() { return 40; },
  getRange() { return new NoopRange(); },
};
let lockDepth = 0;
const trace = [];

sandbox.assertCanonicalSheetLayout_ = () => true;
sandbox.withScriptLock_ = fn => {
  assert.strictEqual(lockDepth, 0, 'refresh nested the script lock');
  lockDepth++;
  try { return fn(); }
  finally { lockDepth--; }
};
sandbox.readConfig_ = () => {
  trace.push(['readConfig', lockDepth]);
  return {routes: {}};
};
sandbox.apiGet_ = path => {
  trace.push([path, lockDepth]);
  return {consolidations: []};
};
sandbox.fetchSheetBindings_ = () => {
  trace.push(['sheetBindings', lockDepth]);
  return {};
};
sandbox.ensureConfigSheet_ = () => configSheet;
sandbox.applySheetBindings_ = () => trace.push(['applyBindings', lockDepth]);
sandbox.SpreadsheetApp = {
  getActive() {
    return {
      getSheetByName(name) { return refreshSheets[name] || null; },
      toast() { trace.push(['toast', lockDepth]); },
    };
  },
};

expose.dallyRefreshOpenConsolidations();
for (const name of ['readConfig', '/api/v1/freight/consolidations/open', 'sheetBindings', 'applyBindings']) {
  const hit = trace.find(entry => entry[0] === name);
  assert.ok(hit, 'missing refresh trace: ' + name);
  assert.strictEqual(hit[1], 1, name + ' ran outside the script lock');
}
assert.strictEqual(trace.find(entry => entry[0] === 'toast')[1], 0, 'toast should run after releasing the script lock');

class MatrixRange {
  constructor(rows) { this.rows = rows; }
  getValues() { return this.rows.map(row => row.slice()); }
  getDisplayValues() { return this.rows.map(row => row.map(value => value == null ? '' : String(value))); }
}

function row(planned) {
  const out = Array(width).fill('');
  out[columns.plannedConsolidation - 1] = planned;
  out[columns.dossier - 1] = 'A001';
  out[columns.client - 1] = 'Client test';
  out[columns.shipmentId - 1] = '42';
  out[columns.syncSourceKey - 1] = 'SRC-42';
  return out;
}

const divergentRows = [row('SEA-A'), row('SEA-B')];
const selectionSheet = {
  getName() { return 'Saisie maritime'; },
  getLastRow() { return DALLY.firstDataRow + divergentRows.length - 1; },
  getRange(rowNumber, column, numRows, numCols) {
    assert.strictEqual(column, 1);
    assert.strictEqual(numCols, width);
    assert.strictEqual(rowNumber, DALLY.firstDataRow);
    assert.strictEqual(numRows, divergentRows.length);
    return new MatrixRange(divergentRows);
  },
};

sandbox.SpreadsheetApp = {
  getActiveSheet() { return selectionSheet; },
  getActiveRange() {
    return {
      getRow() { return DALLY.firstDataRow; },
      getNumRows() { return divergentRows.length; },
    };
  },
};
sandbox.assertCanonicalSheetLayout_ = () => true;

assert.throws(
  () => expose.selectedDossier_(),
  /Les lignes du dossier ont des consolidations prévues différentes\./,
  'manual dossier sync accepted divergent planned consolidations'
);

console.log('REFRESH_CRM_READS_LOCKED=PASS');
console.log('SELECTED_DOSSIER_PLANNED_CONSISTENCY=PASS');
