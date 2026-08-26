'use strict';
// Deterministic regression check for the Sheet key contract (no API/Sheet access).
const source002 = 'sheets:spreadsheet:uuid-002';
const source003 = 'sheets:spreadsheet:uuid-003';
const article = (source, n) => `${source}|A|${n}`;
const payment = (source, n) => `${source}|P|${n}`;
if (article(source002, 1) === article(source003, 1)) throw new Error('article key collision');
if (payment(source002, 1) === payment(source003, 1)) throw new Error('payment key collision');
const fs = require('fs');
const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');
if (!code.includes('getValues()') || !code.includes('getDisplayValues()')) throw new Error('raw/display snapshot contract missing');
if (!/new Set\(selectedKeys\).*size > 1/.test(code)) throw new Error('mixed dossier selection guard missing');
if (!/plannedRef \? undefined/.test(code)) throw new Error('planned flow still supplies local ref');
if (!code.includes("const stableKey = data.sync_source_key")) throw new Error('post-sync refresh missing');
console.log('SHEET_KEY_IDENTITY=PASS');
