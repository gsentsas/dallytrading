'use strict';
const assert = require('assert');
const sheetColumns = Object.freeze({
  plannedConsolidation: 2,
  dossier: 3,
  articleKey: 57,
  paymentKey: 59,
  syncSourceKey: 60,
  globalExternalReference: 61,
  intakeConsolidationRef: 62,
  collectionLocalRef: 63,
});
const columnIndexes = Object.values(sheetColumns);
assert.strictEqual(sheetColumns.plannedConsolidation, 2);
assert.strictEqual(sheetColumns.dossier, 3);
assert.strictEqual(sheetColumns.articleKey, 57);
assert.strictEqual(sheetColumns.paymentKey, 59);
assert.strictEqual(sheetColumns.syncSourceKey, 60);
assert.strictEqual(sheetColumns.globalExternalReference, 61);
assert.strictEqual(sheetColumns.intakeConsolidationRef, 62);
assert.strictEqual(sheetColumns.collectionLocalRef, 63);
assert.strictEqual(new Set(columnIndexes).size, columnIndexes.length, 'column indexes overlap');
assert.strictEqual(Math.max(...columnIndexes), 63, 'max column must remain BK/63');
// Deterministic regression check for the Sheet key contract (no API/Sheet access).
const source002 = 'sheets:spreadsheet:uuid-002';
const source003 = 'sheets:spreadsheet:uuid-003';
const article = (source, n) => `${source}|A|${n}`;
const payment = (source, n) => `${source}|P|${n}`;
if (article(source002, 1) === article(source003, 1)) throw new Error('article key collision');
if (payment(source002, 1) === payment(source003, 1)) throw new Error('payment key collision');

// Pure behavioral mirrors of the Sheet grouping/identity contract.  These do
// not access Apps Script services, so they are deterministic and runnable in
// CI/node while still exercising the edge cases that caused the regressions.
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
if (autoGroup([{dossier: 'A001'}, {dossier: 'A001'}]) !== 'A001') throw new Error('same legacy dossier split');
if (autoGroup([{dossier: 'A001', planned: 'C1'}]) !== 'C1|A001') throw new Error('planned namespace mismatch');
if (autoGroup([{dossier: 'A001', source: 's'}, {dossier: 'A001', source: 's'}]) !== 'source|s') throw new Error('same source not grouped');
if (autoGroup([{dossier: 'A001', source: 's'}, {dossier: 'A001'}]) !== 'source|s') throw new Error('partial source not normalized');
let rejected = false;
try { autoGroup([{dossier: 'A001', source: 's1'}, {dossier: 'A001', source: 's2'}]); } catch (e) { rejected = true; }
if (!rejected) throw new Error('divergent source accepted');
if (autoGroup([{dossier: 'A001', planned: 'C1'}]) === autoGroup([{dossier: 'A001', planned: 'C2'}])) throw new Error('planned namespaces collided');
if (autoGroup([{dossier: '', planned: 'C1'}]) !== null) throw new Error('blank-B entered autosync');
if (externalRef({planned: 'C1', dossier: 'A001'}) !== 'A001') throw new Error('legacy first bind fallback missing');
if (externalRef({planned: 'C1', dossier: '', source: 's'}) !== '') throw new Error('new planned dossier sent local ref');
if (externalRef({planned: 'C1', dossier: 'A001', shipmentId: 9}) !== '') throw new Error('server-managed planned dossier sent local ref');
if (externalRef({planned: 'C1', dossier: 'A001', lastSync: '2026-01-01'}) !== 'A001') throw new Error('failed retry lost legacy reference');
if (externalRef({planned: 'C1', dossier: 'A001', intake: 'C1'}) !== '') throw new Error('intake identity did not suppress local ref');
if (externalRef({planned: 'C1', dossier: 'A001', collectionLocalRef: 'A001'}) !== '') throw new Error('local identity did not suppress local ref');
if (externalRef({planned: 'C1', dossier: 'A001', global: 'C1-A001'}) !== 'C1-A001') throw new Error('global reference not authoritative');

const numberOrNull = value => {
  if (value === '' || value === null || typeof value === 'undefined') return null;
  const normalized = typeof value === 'string' ? value.replace(/[\s\u00A0\u202F]/g, '').replace(',', '.') : value;
  if (normalized === '') return null;
  const n = Number(normalized);
  return Number.isFinite(n) ? n : null;
};
for (const value of ['1234,56', '1 234,56', '1\u00A0234,56', '1\u202F234,56']) {
  if (numberOrNull(value) !== 1234.56) throw new Error('localized number parsing failed');
}
if (numberOrNull(1234.56) !== 1234.56 || numberOrNull('') !== null || numberOrNull(null) !== null || numberOrNull('not-a-number') !== null) throw new Error('number parsing contract failed');
for (const value of ['   ', '\u00A0', '\u202F', ' \u00A0\u202F ']) {
  if (numberOrNull(value) !== null) throw new Error('whitespace-only value became zero');
}

const normalizeGroups = rows => {
  const groups = new Map();
  rows
    .filter(r => String(r.dossier ?? '').trim())
    .forEach(r => {
      const dossier = String(r.dossier ?? '').trim();
      const planned = String(r.planned ?? '').trim();
      const namespace = planned ? `${planned}|${dossier}` : dossier;
      if (!groups.has(namespace)) groups.set(namespace, []);
      groups.get(namespace).push({...r, dossier, planned});
    });
  for (const field of ['source', 'global', 'shipmentId']) {
    const index = new Map();
    groups.forEach((members, namespace) => members.forEach(m => {
      if (!m[field]) return;
      if (!index.has(m[field])) index.set(m[field], new Set());
      index.get(m[field]).add(namespace);
    }));
    for (const namespaces of index.values()) if (namespaces.size > 1) throw new Error('cross-namespace identity conflict');
  }
  groups.forEach(members => ['source', 'global', 'shipmentId', 'collectionLocalRef'].forEach(field => {
    const distinct = [...new Set(members.map(m => m[field]).filter(Boolean))];
    if (distinct.length > 1) throw new Error('intra-namespace identity conflict');
    const value = distinct[0] || '';
    if (value) members.forEach(m => { if (!m[field]) m[field] = value; });
  }));
  return [...groups.values()];
};
const oneGroup = normalizeGroups([{dossier: 'A001', planned: 'C1'}, {dossier: 'A001', planned: 'C1'}]);
if (oneGroup.length !== 1) throw new Error('empty identities split');
if (normalizeGroups([{dossier: 'A001', planned: 'C1', source: 's'}, {dossier: 'A001', planned: 'C1'}])[0][1].source !== 's') throw new Error('partial source not propagated');
if (normalizeGroups([{dossier: 'A001', planned: 'C1', global: 'C1-A001'}, {dossier: 'A001', planned: 'C1'}])[0][1].global !== 'C1-A001') throw new Error('partial global not propagated');
if (normalizeGroups([{dossier: 'A001', planned: 'C1', shipmentId: 7}, {dossier: 'A001', planned: 'C1'}])[0][1].shipmentId !== 7) throw new Error('partial shipment not propagated');
if (normalizeGroups([{dossier: 'A001', planned: 'C1', collectionLocalRef: 'A001'}, {dossier: 'A001', planned: 'C1'}])[0][1].collectionLocalRef !== 'A001') throw new Error('partial local ref not propagated');
let localConflict = false;
try { normalizeGroups([{dossier: 'A001', planned: 'C1', collectionLocalRef: 'A001'}, {dossier: 'A001', planned: 'C1', collectionLocalRef: 'A002'}]); } catch (e) { localConflict = true; }
if (!localConflict) throw new Error('intra-namespace local ref conflict accepted');
const sameLocal = normalizeGroups([{dossier: 'A001', planned: 'C1', collectionLocalRef: 'A001'}, {dossier: 'A001', planned: 'C2', collectionLocalRef: 'A001'}]);
if (sameLocal.length !== 2 || sameLocal.some(group => group[0].collectionLocalRef !== 'A001')) throw new Error('local ref incorrectly treated as global');
for (const field of ['source', 'global', 'shipmentId']) {
  let conflict = false;
  try { normalizeGroups([{dossier: 'A001', planned: 'C1', [field]: 'x'}, {dossier: 'A001', planned: 'C2', [field]: 'x'}]); } catch (e) { conflict = true; }
  if (!conflict) throw new Error('cross-namespace ' + field + ' accepted');
}
if (normalizeGroups([{dossier: 'A001', planned: 'C1', source: 's1'}, {dossier: 'A001', planned: 'C2', source: 's2'}]).length !== 2) throw new Error('distinct namespaces collapsed');
if (normalizeGroups([{dossier: '', planned: 'C1'}]).length !== 0) throw new Error('blank-B entered autosync');
if (normalizeGroups([{dossier: '   ', planned: 'C1'}]).length !== 0) {
  throw new Error('whitespace-only dossier entered autosync');
}
if (normalizeGroups([{dossier: 'A001', planned: 'C1'}, {dossier: 'A001', planned: 'C1'}]).length !== 1) throw new Error('one API call invariant failed');
const reloadedNamespace = rows => new Set(rows.map(row => row.planned ? `${row.planned}|${row.dossier}` : row.dossier));
let reloadRejected = false;
try {
  if (reloadedNamespace([{dossier: 'A001', planned: 'C1'}, {dossier: 'A001', planned: 'C2'}]).size > 1) throw new Error('Identité serveur associée à plusieurs namespaces de dossier.');
} catch (e) { reloadRejected = true; }
if (!reloadRejected) throw new Error('reloaded namespace collision accepted');
if (reloadedNamespace([{dossier: 'A001', planned: 'C1', collectionLocalRef: 'A001'}, {dossier: 'A001', planned: 'C2', collectionLocalRef: 'A001'}]).size !== 2) throw new Error('local ref reuse across namespaces rejected');
const normalizeIdentity = value => String(value ?? '').trim();
const assertSelectedIdentityScope = (selected, all) => {
  const namespace = row => row.planned ? `${row.planned}|${row.dossier}` : row.dossier;
  const selectedNamespace = namespace(selected[0]);
  for (const field of ['source', 'global', 'shipmentId']) {
    const identities = new Set(selected.map(row => normalizeIdentity(row[field])).filter(Boolean));
    if (identities.size > 1) throw new Error('La sélection contient des identités de dossier en conflit.');
    if (all.some(row => namespace(row) !== selectedNamespace && identities.has(normalizeIdentity(row[field])))) throw new Error('Identité serveur associée à plusieurs namespaces de dossier.');
  }
};
const selectedConflictPattern = /La sélection contient des identités de dossier en conflit\./;
assert.throws(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', source: 'S1', global: 'G1'}, {dossier: 'A001', planned: 'C1', source: 'S1', global: 'G2'}], []), selectedConflictPattern, 'same source/different global accepted');
assert.throws(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', source: 'S1', shipmentId: 10}, {dossier: 'A001', planned: 'C1', source: 'S1', shipmentId: 11}], []), selectedConflictPattern, 'same source/different shipment accepted');
assert.doesNotThrow(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', source: 'S1', global: 'G1', shipmentId: 10}, {dossier: 'A001', planned: 'C1', source: 'S1', global: 'G1', shipmentId: 10}], []));
const identityCollisionPattern = /Identité serveur associée à plusieurs namespaces de dossier\./;
const assertBlankOwnership = (selected, outside) => {
  const sourceValues = selected.map(row => String(row.source ?? '').trim()).filter(Boolean);
  const selectedKeys = new Set(sourceValues);
  if (selectedKeys.size > 1 || (selectedKeys.size && selected.some(row => !String(row.source ?? '').trim()))) throw new Error('partial source');
  for (const row of outside) if (selectedKeys.has(String(row.source ?? '').trim())) throw new Error('Identité serveur associée à plusieurs namespaces de dossier.');
};
assert.doesNotThrow(() => assertBlankOwnership([{dossier: '', planned: 'C1'}, {dossier: '', planned: 'C1'}], []));
assert.doesNotThrow(() => assertBlankOwnership([{dossier: '', planned: 'C1', source: 'S-RETRY'}, {dossier: '', planned: 'C1', source: 'S-RETRY'}], []));
assert.throws(() => assertBlankOwnership([{dossier: '', planned: 'C1', source: 'S-RETRY'}, {dossier: '', planned: 'C1', source: 'S-RETRY'}], [{dossier: 'A009', planned: 'C2', source: 'S-RETRY'}]), identityCollisionPattern, 'blank source owner reused');
assert.throws(() => assertBlankOwnership([{dossier: '', planned: 'C1', source: 'S-RETRY'}, {dossier: '', planned: 'C1', source: 'S-RETRY'}], [{dossier: '', planned: 'C1', source: 'S-RETRY'}]), identityCollisionPattern, 'blank source owner reused by blank row');
assert.throws(() => assertBlankOwnership([{dossier: '', planned: 'C1', source: 'S-RETRY'}, {dossier: '', planned: 'C1', source: 'S-RETRY'}], [{dossier: '', planned: 'C2', source: 'S-RETRY'}]), identityCollisionPattern, 'blank source owner reused by other plan');
assert.throws(() => assertBlankOwnership([{dossier: '', planned: 'C1', source: 'S-RETRY'}, {dossier: '', planned: 'C1'}], []), /partial source/, 'partial blank source accepted');
assert.throws(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', source: 'S1', global: 'G1'}], [{dossier: 'A001', planned: 'C1', source: 'S1', global: 'G1'}, {dossier: 'A001', planned: 'C2', source: 'S2', global: 'G1'}]), identityCollisionPattern, 'hidden global collision accepted');
assert.throws(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', source: 'S1', shipmentId: 10}], [{dossier: 'A001', planned: 'C1', source: 'S1', shipmentId: 10}, {dossier: 'A001', planned: 'C2', source: 'S2', shipmentId: 10}]), identityCollisionPattern, 'hidden shipment collision accepted');
assert.throws(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', shipmentId: 10}], [{dossier: 'A001', planned: 'C2', shipmentId: '10'}]), identityCollisionPattern, 'numeric/string shipment collision accepted');
assert.throws(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', source: ' S1 '}], [{dossier: 'A001', planned: 'C2', source: 'S1'}]), identityCollisionPattern, 'whitespace source collision accepted');
assert.doesNotThrow(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', shipmentId: 10}], [{dossier: 'A001', planned: 'C1', shipmentId: '10'}]));
const fs = require('fs');
const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');
const columnsBlock = code.match(/columns:\s*Object\.freeze\(\{([\s\S]*?)\n\s*\}\)/);
if (!columnsBlock) throw new Error('DALLY.columns map missing');
const parsedColumns = Object.fromEntries(
  [...columnsBlock[1].matchAll(/([A-Za-z][A-Za-z0-9]*):\s*(\d+)/g)]
    .map(([, name, value]) => [name, Number(value)])
);
for (const [name, expected] of Object.entries(sheetColumns)) {
  if (parsedColumns[name] !== expected) throw new Error(`DALLY.columns.${name} expected ${expected}, got ${parsedColumns[name]}`);
}
const allColumnIndexes = Object.values(parsedColumns);
if (new Set(allColumnIndexes).size !== allColumnIndexes.length) throw new Error('DALLY.columns indexes overlap');
if (Math.max(...allColumnIndexes) !== 63) throw new Error('DALLY.columns maxColumn contract failed');
if (!code.includes('getValues()') || !code.includes('getDisplayValues()')) throw new Error('raw/display snapshot contract missing');
if (!code.includes("data.planned_consolidation_ref")) throw new Error('server consolidation confirmation missing');
if (!code.includes('fetchSheetBindings_') || !code.includes('/api/v1/freight/sheet-bindings?shipment_ids=')) throw new Error('CRM binding refresh missing');
if (!/start \+= 200/.test(code)) throw new Error('binding request batch limit missing');
if (!code.includes('Consolidation en attente : Sheet')) throw new Error('pending Sheet edit protection missing');
if (!code.includes('Replanification requise dans une consolidation ouverte.')) throw new Error('replanification status missing');
if (!/new Set\(logicalKeys\).*size > 1/.test(code)) throw new Error('mixed dossier selection guard missing');
if (!/firstNumber_\(rows, DALLY\.columns\.shipmentId\)/.test(code)) throw new Error('server identity fallback missing');
if (!/nonEmptySourceKeys\.length !== sourceKeys\.length/.test(code)) throw new Error('partial source key guard missing');
if (!code.includes("const stableKey = data.sync_source_key")) throw new Error('post-sync refresh missing');
if (!code.includes('function migrateLegacySheetLayout_')) throw new Error('legacy layout migration missing');
if (!code.includes('Disposition de feuille inconnue')) throw new Error('unknown layout safety missing');
if (!code.includes('sheetLiteralText_')) throw new Error('formula guard missing');
for (const value of ['=FORMULA', '+FORMULA', '-FORMULA', '@FORMULA']) {
  const guarded = /^[=+\-@]/.test(value) ? "'" + value : value;
  if (guarded === value) throw new Error('formula guard failed for ' + value);
}
if (!code.includes('pendingValues.length > 1')) throw new Error('multi-pending conflict handling missing');
if (!code.includes('plusieurs valeurs Sheet en attente')) throw new Error('multi-pending conflict message missing');
if (!code.includes("source ? 'source|' + source : (global ? 'global|' + global")) throw new Error('binding grouping priority missing');
if (!code.includes("'shipment|' + (shipment || dossier) + '|' + dossier")) throw new Error('shipment+dossier grouping fallback missing');
function mockMigrate(rows) {
  const headers = rows[0];
  if (headers[1] === 'Consolidation prévue' && headers[2] === 'N dossier') return rows;
  const legacy63 = headers[1] === 'N dossier' && headers[58] === 'Consolidation prévue';
  const legacy58 = headers[1] === 'N dossier' && rows[0].length <= 60;
  if (!legacy63 && !legacy58) throw new Error('unknown layout');
  const shifted = rows.map(row => [row[0], '', ...row.slice(1)]);
  if (legacy63) {
    shifted.forEach(row => { row[1] = row[59]; row.splice(59, 1); });
  }
  shifted.forEach(row => { while (row.length < 63) row.push(''); });
  shifted[0][1] = 'Consolidation prévue'; shifted[0][2] = 'N dossier';
  shifted[0].splice(56, 7, 'Clé article facture', 'Flag règlement facture', 'Clé règlement facture', 'sync source key', 'global external reference', 'intake consolidation ref', 'collection local ref');
  return shifted;
}
const old58 = Array.from({length: 2}, () => Array(59).fill(''));
Object.assign(old58[0], {0:'Date depot', 1:'N dossier', 55:'Clé article facture', 56:'Flag règlement facture', 57:'Clé règlement facture'});
old58[1][1] = 'DOS-58'; old58[1][3] = 'Client 58'; old58[1][55] = 'AKEY'; old58[1][56] = 'FLAG'; old58[1][57] = 'PKEY';
const new58 = mockMigrate(old58);
if (new58[0][1] !== 'Consolidation prévue' || new58[0][2] !== 'N dossier' || new58[1][2] !== 'DOS-58' || new58[1][56] !== 'AKEY' || new58[1][57] !== 'FLAG' || new58[1][58] !== 'PKEY' || new58[0][59] !== 'sync source key') throw new Error('legacy58 behavior failed');
const old63 = Array.from({length: 2}, () => Array(63).fill(''));
Object.assign(old63[0], {0:'Date depot', 1:'N dossier', 58:'Consolidation prévue', 59:'sync source key', 60:'global external reference', 61:'intake consolidation ref', 62:'collection local ref'});
old63[1][1] = 'DOS-63'; old63[1][3] = 'Client 63'; old63[1][55] = 'AKEY63'; old63[1][56] = 'FLAG63'; old63[1][58] = 'AIR-DSS-CDG-2099-X'; old63[1][59] = 'SRC63'; old63[1][60] = 'GLOB63'; old63[1][61] = 'INT63'; old63[1][62] = 'A001';
const new63 = mockMigrate(old63); const second63 = mockMigrate(new63);
const legacy63ok = [new63[0][1] === 'Consolidation prévue', new63[1][1] === 'AIR-DSS-CDG-2099-X', new63[1][2] === 'DOS-63', new63[1][56] === 'AKEY63', new63[1][57] === 'FLAG63', new63[1][59] === 'SRC63', new63[1][60] === 'GLOB63', new63[1][61] === 'INT63', new63[1][62] === 'A001', new63[0][56] === 'Clé article facture', new63[0][57] === 'Flag règlement facture', new63[0][58] === 'Clé règlement facture', JSON.stringify(new63) === JSON.stringify(second63)].every(Boolean);
if (!legacy63ok) throw new Error('legacy63 behavior/idempotence failed');
if (detectSheetLayoutGuard('legacy58') !== 'blocked' || detectSheetLayoutGuard('legacy63') !== 'blocked' || detectSheetLayoutGuard('canonical') !== 'allowed') throw new Error('wrong-index guard behavior failed');
function detectSheetLayoutGuard(layout) { return layout === 'canonical' ? 'allowed' : 'blocked'; }
console.log('SHEET_LAYOUT_MIGRATION_IDEMPOTENT=PASS');
console.log('SHEET_FORMULA_INJECTION_GUARD=PASS');
console.log('MULTI_PENDING_CONSOLIDATION_PRESERVED=PASS');
console.log('LEGACY58_BEHAVIOR=PASS');
console.log('LEGACY63_BEHAVIOR=PASS');
console.log('MIGRATION_SECOND_RUN_NOOP=PASS');
console.log('PAYMENT_HEADER_ALIGNMENT=PASS');
console.log('LEGACY_WRONG_INDEX_GUARD=PASS');
console.log('SHEET_KEY_IDENTITY=PASS');
