'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');

class FakeRange {
  constructor(sheet, row, col) { this.sheet = sheet; this.row = row; this.col = col; }
  getDisplayValue() { const value = this.sheet.cell(this.row, this.col); return value == null ? '' : String(value); }
  setValue(value) { this.sheet.setCell(this.row, this.col, value); return this; }
}
class FakeSheet {
  constructor(width) { this.row = Array(width).fill(''); }
  cell(row, col) { return this.row[col - 1] ?? ''; }
  setCell(row, col, value) { this.row[col - 1] = value; }
  getRange(row, col) { return new FakeRange(this, row, col); }
}

const sandbox = {console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const {DALLY} = vm.runInContext('({DALLY})', sandbox);

assert.strictEqual(
  typeof sandbox.applyReturnedPlannedRef_,
  'function',
  'applyReturnedPlannedRef_ must exist'
);

const historical = new FakeSheet(DALLY.maxColumn);
historical.setCell(3, DALLY.columns.plannedConsolidation, 'AIR-DSS-CDG-2026-001');
sandbox.applyReturnedPlannedRef_(historical, 3, {planned_consolidation_ref: false});
assert.strictEqual(
  historical.cell(3, DALLY.columns.plannedConsolidation),
  'AIR-DSS-CDG-2026-001',
  'CRM false must not erase a historical visible planned consolidation'
);

sandbox.applyReturnedPlannedRef_(historical, 3, {planned_consolidation_ref: 'AIR-CRM-OPEN'});
assert.strictEqual(
  historical.cell(3, DALLY.columns.plannedConsolidation),
  'AIR-CRM-OPEN',
  'a non-empty authoritative CRM planned consolidation must still be applied'
);

const blank = new FakeSheet(DALLY.maxColumn);
sandbox.applyReturnedPlannedRef_(blank, 3, {planned_consolidation_ref: false});
assert.strictEqual(
  blank.cell(3, DALLY.columns.plannedConsolidation),
  '',
  'CRM false must leave an already blank planned cell blank'
);

console.log('SYNC_PLANNED_RESPONSE_GUARD=PASS');
