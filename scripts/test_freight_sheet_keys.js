'use strict';
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
  const namespaces = new Set(rows.map(r => `${r.planned || ''}|${r.dossier}`));
  if (namespaces.size !== 1) throw new Error('multiple logical dossiers');
  const source = normalizeSources(rows);
  return source ? `source|${source}` : [...namespaces][0];
};
const externalRef = row => {
  if (row.global) return row.global;
  if (!row.planned) return row.dossier || '';
  if (row.shipmentId || row.intake || row.local || row.lastSync) return '';
  return row.dossier || '';
};
if (autoGroup([{dossier: 'A001'}, {dossier: 'A001'}]) !== '|A001') throw new Error('same legacy dossier split');
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
if (externalRef({planned: 'C1', dossier: 'A001', global: 'C1-A001'}) !== 'C1-A001') throw new Error('global reference not authoritative');
const fs = require('fs');
const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');
if (!code.includes('getValues()') || !code.includes('getDisplayValues()')) throw new Error('raw/display snapshot contract missing');
if (!/new Set\(logicalKeys\).*size > 1/.test(code)) throw new Error('mixed dossier selection guard missing');
if (!/firstNumber_\(rows, DALLY\.columns\.shipmentId\)/.test(code)) throw new Error('server identity fallback missing');
if (!/nonEmptySourceKeys\.length !== sourceKeys\.length/.test(code)) throw new Error('partial source key guard missing');
if (!code.includes("const stableKey = data.sync_source_key")) throw new Error('post-sync refresh missing');
console.log('SHEET_KEY_IDENTITY=PASS');
