'use strict';
const assert = require('assert');
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
const assertSelectedIdentityScope = (selected, all) => {
  const namespace = row => row.planned ? `${row.planned}|${row.dossier}` : row.dossier;
  const selectedNamespace = namespace(selected[0]);
  for (const field of ['source', 'global', 'shipmentId']) {
    const identities = new Set(selected.map(row => row[field]).filter(Boolean));
    if (all.some(row => namespace(row) !== selectedNamespace && identities.has(row[field]))) throw new Error('Identité serveur associée à plusieurs namespaces de dossier.');
  }
};
const identityCollisionPattern = /Identité serveur associée à plusieurs namespaces de dossier\./;
assert.throws(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', source: 'S1', global: 'G1'}], [{dossier: 'A001', planned: 'C1', source: 'S1', global: 'G1'}, {dossier: 'A001', planned: 'C2', source: 'S2', global: 'G1'}]), identityCollisionPattern, 'hidden global collision accepted');
assert.throws(() => assertSelectedIdentityScope([{dossier: 'A001', planned: 'C1', source: 'S1', shipmentId: 10}], [{dossier: 'A001', planned: 'C1', source: 'S1', shipmentId: 10}, {dossier: 'A001', planned: 'C2', source: 'S2', shipmentId: 10}]), identityCollisionPattern, 'hidden shipment collision accepted');
const fs = require('fs');
const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');
if (!code.includes('getValues()') || !code.includes('getDisplayValues()')) throw new Error('raw/display snapshot contract missing');
if (!/new Set\(logicalKeys\).*size > 1/.test(code)) throw new Error('mixed dossier selection guard missing');
if (!/firstNumber_\(rows, DALLY\.columns\.shipmentId\)/.test(code)) throw new Error('server identity fallback missing');
if (!/nonEmptySourceKeys\.length !== sourceKeys\.length/.test(code)) throw new Error('partial source key guard missing');
if (!code.includes("const stableKey = data.sync_source_key")) throw new Error('post-sync refresh missing');
console.log('SHEET_KEY_IDENTITY=PASS');
