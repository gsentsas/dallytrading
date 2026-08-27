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
  constructor(rows, width) {
    this.rows = rows.map(row => row.slice());
    this.width = width;
    this.rows.forEach(row => {
      while (row.length < width) row.push('');
    });
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
};

vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const expose = vm.runInContext('({DALLY, assertNoSelectedIdentityCollision_})', sandbox);
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

console.log('IDENTITY_COLLISION_CROSS_SOURCE_GUARD=PASS');
