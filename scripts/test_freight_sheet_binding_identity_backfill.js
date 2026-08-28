'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');

class FakeRange {
  constructor(sheet, row, col, numRows = 1, numCols = 1) {
    this.sheet = sheet; this.row = row; this.col = col; this.numRows = numRows; this.numCols = numCols;
  }
  matrix() {
    return Array.from({length: this.numRows}, (_, r) =>
      Array.from({length: this.numCols}, (_, c) => this.sheet.cell(this.row + r, this.col + c))
    );
  }
  getDisplayValues() { return this.matrix().map(row => row.map(value => value == null ? '' : String(value))); }
  getDisplayValue() { const value = this.sheet.cell(this.row, this.col); return value == null ? '' : String(value); }
  setValue(value) { this.sheet.setCell(this.row, this.col, value); return this; }
}

class FakeSheet {
  constructor(rows, width) {
    this.rows = rows.map(row => row.slice());
    this.width = width;
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
const {DALLY, applySheetBindings_} = vm.runInContext('({DALLY, applySheetBindings_})', sandbox);

const blank = () => Array(DALLY.maxColumn).fill('');
const makeRow = ({planned = 'AIR-DSS-CDG-2026-001', status = 'À synchroniser', shipment = 672, global = '', source = '', message = ''} = {}) => {
  const value = blank();
  value[DALLY.columns.plannedConsolidation - 1] = planned;
  value[DALLY.columns.dossier - 1] = 'A001';
  value[DALLY.columns.syncStatus - 1] = status;
  value[DALLY.columns.shipmentId - 1] = String(shipment);
  value[DALLY.columns.globalExternalReference - 1] = global;
  value[DALLY.columns.syncSourceKey - 1] = source;
  value[DALLY.columns.syncMessage - 1] = message;
  return value;
};

const correction = 'Correction utilisateur 28/08/2026 : A001 déjà payé. Paiement client de 23 EUR à conserver.';
const sheet = new FakeSheet([
  blank(),
  blank(),
  makeRow({source: 'sheets:local-a001', message: correction})
], DALLY.maxColumn);

applySheetBindings_(sheet, {
  '672': {
    shipment_id: 672,
    sync_source_key: false,
    external_reference: 'AIR-LEGACY-672',
    collection_local_ref: false,
    intake_consolidation_ref: false,
    planned_consolidation_ref: false,
    requires_replan: false
  }
});

assert.strictEqual(
  sheet.cell(3, DALLY.columns.globalExternalReference),
  'AIR-LEGACY-672',
  'refresh must backfill the authoritative CRM external_reference for an existing shipment'
);
assert.strictEqual(
  sheet.cell(3, DALLY.columns.syncSourceKey),
  'sheets:local-a001',
  'a locally generated source key must be preserved when CRM has no source key yet'
);
assert.strictEqual(
  sheet.cell(3, DALLY.columns.plannedConsolidation),
  'AIR-DSS-CDG-2026-001',
  'identity backfill must not erase the historical planned consolidation'
);
assert.strictEqual(
  sheet.cell(3, DALLY.columns.syncMessage),
  correction,
  'identity backfill must not overwrite the user correction message'
);

const conflict = new FakeSheet([
  blank(),
  blank(),
  makeRow({shipment: 673, global: 'WRONG-LOCAL', message: correction})
], DALLY.maxColumn);

applySheetBindings_(conflict, {
  '673': {
    shipment_id: 673,
    external_reference: 'CRM-673',
    planned_consolidation_ref: false,
    requires_replan: false
  }
});

assert.strictEqual(
  conflict.cell(3, DALLY.columns.globalExternalReference),
  'WRONG-LOCAL',
  'refresh must never silently overwrite a conflicting non-empty external_reference'
);
assert.strictEqual(
  conflict.cell(3, DALLY.columns.syncStatus),
  'Erreur',
  'identity disagreement must block synchronisation'
);
assert.match(
  String(conflict.cell(3, DALLY.columns.syncMessage)),
  /Conflit identité CRM\/Sheet/,
  'identity disagreement must be visible to the operator'
);

console.log('BINDING_IDENTITY_BACKFILL=PASS');
