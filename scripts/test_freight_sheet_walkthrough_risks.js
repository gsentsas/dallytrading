'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');
const sandbox = {console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const expose = vm.runInContext('({DALLY, buildFreightPayload_, syncDossier_})', sandbox);
const DALLY = expose.DALLY;
const columns = DALLY.columns;
const width = DALLY.maxColumn;

function freightRow({planned = '', message = '', shipmentId = 42, sourceKey = 'SRC-42'} = {}) {
  const display = Array(width).fill('');
  const values = Array(width).fill('');
  const put = (column, value) => {
    display[column - 1] = value == null ? '' : String(value);
    values[column - 1] = value;
  };
  put(columns.plannedConsolidation, planned);
  put(columns.dossier, 'A001');
  put(columns.client, 'Client test');
  put(columns.description, 'Colis test');
  put(columns.quantity, 1);
  put(columns.shipmentId, shipmentId);
  put(columns.syncSourceKey, sourceKey);
  put(columns.globalExternalReference, 'EXT-42');
  put(columns.syncMessage, message);
  put(columns.articleKey, 'AK-1');
  return {row: DALLY.firstDataRow, display, values, _syncArticleKey: 'AK-1'};
}

const cfg = {
  migrationMode: false,
  autoInvoice: false,
  syncPayments: false,
  routes: {
    'Saisie maritime': {
      mode: 'sea', direction: 'export',
      originCountry: 'SN', originCity: 'Dakar',
      destinationCountry: 'FR', destinationCity: 'Paris',
    },
  },
};

const clearedReplan = freightRow({planned: '', message: DALLY.replanIntentMarker});
assert.throws(
  () => expose.buildFreightPayload_('Saisie maritime', 'A001', [clearedReplan], [clearedReplan], cfg),
  /vider la colonne B n’est pas une désaffectation valide/,
  'explicit replan to an empty planned consolidation must be rejected before CRM sync'
);

const row = freightRow({planned: 'SEA-OLD', message: DALLY.replanIntentMarker});
const writes = [];
const fakeSheet = {
  getName() { return 'Saisie maritime'; },
};

sandbox.ensureSourceKey_ = () => 'SRC-42';
sandbox.prepareArticleRows_ = (_sheet, _dossier, rows) => rows;
sandbox.buildFreightPayload_ = () => ({external_reference: 'EXT-42'});
sandbox.apiPost_ = () => ({
  planned_consolidation_ref: 'SEA-OLD',
  partner_id: 7,
  shipment_id: 42,
  external_reference: 'EXT-42',
  sync_source_key: 'SRC-42',
  collection_local_ref: 'A001',
  intake_consolidation_ref: 'SEA-OLD',
  requires_replan: true,
  sync_message: 'Départ clôturé — replanification requise',
  lines: [{external_line_key: 'AK-1', pricing_status: 'priced'}],
});
sandbox.articleKey_ = () => 'AK-1';
sandbox.setCell_ = (_sheet, rowNumber, column, value) => writes.push({rowNumber, column, value});
sandbox.sourceKey_ = () => 'SRC-42';
sandbox.logicalDossierKey_ = () => 'source|SRC-42';
sandbox.rowsForDossier_ = () => [row];
sandbox.invoiceReady_ = () => false;
sandbox.dossierHasPayments_ = () => false;

expose.syncDossier_(fakeSheet, 'A001', [row], cfg);

const messageWrite = writes.find(write => write.column === columns.syncMessage);
assert.ok(messageWrite, 'sync did not write a status message');
assert.match(
  String(messageWrite.value),
  /Départ clôturé — replanification requise/,
  'sync hid the authoritative CRM replan warning'
);
const messageIndex = writes.findIndex(write => write.column === columns.syncMessage);
const statusIndex = writes.findIndex(write => write.column === columns.syncStatus);
assert.ok(statusIndex > messageIndex, 'Synchronisé status was written before authoritative CRM output completed');

console.log('EMPTY_EXPLICIT_REPLAN_REJECTED=PASS');
console.log('AUTHORITATIVE_REPLAN_WARNING_PRESERVED=PASS');
console.log('SYNC_STATUS_WRITTEN_LAST=PASS');
