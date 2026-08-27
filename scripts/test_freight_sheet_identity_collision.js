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

  getDisplayValues() {
    const out = [];
    for (let r = 0; r < this.numRows; r++) {
      const current = [];
      for (let c = 0; c < this.numCols; c++) {
        const value = this.sheet.cell(this.row + r, this.col + c);
        current.push(value == null ? '' : String(value));
      }
      out.push(current);
    }
    return out;
  }
}

class FakeSheet {
  constructor(rows, width, name = 'Saisie maritime') {
    this.rows = rows.map(row => row.slice());
    this.width = width;
    this.name = name;
    this.rows.forEach(row => {
      while (row.length < width) row.push('');
    });
  }

  getName() {
    return this.name;
  }

  getMaxColumns() {
    return this.width;
  }

  getLastRow() {
    return this.rows.length;
  }

  cell(row, col) {
    return (this.rows[row - 1] || [])[col - 1] ?? '';
  }

  getRange(row, col, numRows = 1, numCols = 1) {
    return new FakeRange(this, row, col, numRows, numCols);
  }
}

const sandbox = {
  console,
  Date,
  Map,
  Set,
  Object,
  String,
  Number,
  Math,
  JSON,
  RegExp,
  Error,
  Utilities: {
    getUuid: () => 'uuid-test',
    formatDate: () => '2099-01-01',
  },
  LockService: {
    getScriptLock: () => ({
      tryLock: () => true,
      releaseLock: () => {},
    }),
  },
};

vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const expose = vm.runInContext('({DALLY, assertNoSelectedIdentityCollision_, dallyInvoiceSelectedDossier, dallyPaymentsSelectedDossier})', sandbox);
const columns = expose.DALLY.columns;
const width = expose.DALLY.maxColumn;

function blankRow() {
  return Array(width).fill('');
}

function setIdentity(row, sourceKey) {
  row[columns.plannedConsolidation - 1] = 'AIR-DSS-CDG-2099-X';
  row[columns.dossier - 1] = 'A001';
  row[columns.shipmentId - 1] = '42';
  row[columns.syncSourceKey - 1] = sourceKey;
}

const selected = blankRow();
const conflicting = blankRow();
setIdentity(selected, 'SOURCE-A');
setIdentity(conflicting, 'SOURCE-B');

const collisionSheet = new FakeSheet([blankRow(), blankRow(), selected, conflicting], width);
const selectedRows = [{
  row: 3,
  display: collisionSheet.getRange(3, 1, 1, width).getDisplayValues()[0],
}];

assert.throws(
  () => expose.assertNoSelectedIdentityCollision_(collisionSheet, selectedRows),
  /Identité serveur associée à plusieurs namespaces de dossier\./,
  'same shipment/planned/dossier across distinct syncSourceKey namespaces must be rejected',
);

const sameNamespace = blankRow();
setIdentity(sameNamespace, 'SOURCE-A');
const allowedSheet = new FakeSheet([blankRow(), blankRow(), selected, sameNamespace], width);
const allowedSelectedRows = [{
  row: 3,
  display: allowedSheet.getRange(3, 1, 1, width).getDisplayValues()[0],
}];
assert.doesNotThrow(
  () => expose.assertNoSelectedIdentityCollision_(allowedSheet, allowedSelectedRows),
  'same server identity inside the same logical namespace must remain allowed',
);

const legacyHeader = blankRow();
legacyHeader[0] = 'Date depot';
legacyHeader[1] = 'N dossier';
legacyHeader[55] = 'Clé article facture';
legacyHeader[56] = 'Flag règlement facture';
legacyHeader[57] = 'Clé règlement facture';
const legacySheet = new FakeSheet([blankRow(), legacyHeader, blankRow()], width);
let activeRangeReached = false;
sandbox.SpreadsheetApp = {
  getActiveSheet: () => legacySheet,
  getActiveRange: () => {
    activeRangeReached = true;
    throw new Error('canonical-index read reached');
  },
};

assert.throws(
  () => expose.dallyInvoiceSelectedDossier(),
  /Disposition ancienne/,
  'invoice entry path must reject a legacy layout after acquiring the real script lock',
);
assert.throws(
  () => expose.dallyPaymentsSelectedDossier(),
  /Disposition ancienne/,
  'payment entry path must reject a legacy layout after acquiring the real script lock',
);
assert.strictEqual(activeRangeReached, false, 'invoice/payment read canonical indexes before the legacy-layout guard');

console.log('IDENTITY_COLLISION_CROSS_SOURCE_GUARD=PASS');
console.log('INVOICE_PAYMENT_LAYOUT_GUARD_WITH_LOCK=PASS');
