#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const code = fs.readFileSync(
  path.join(root, 'integrations/google-sheets/freight-sync/Code.gs'),
  'utf8'
);

const context = vm.createContext({console});
vm.runInContext(code, context, {filename: 'Code.gs'});

function buildLineWithFamily(label) {
  context.__familyLabel = label;
  return vm.runInContext(`(() => {
    const row = {values: Array(63).fill(''), display: Array(63).fill('')};
    row._syncArticleKey = 'test-line';
    row.display[7] = 'Article test';
    row.values[8] = 1;
    row.values[15] = 1;
    row.display[18] = 'Poids reel';
    row.display[41] = 'Standard';
    row.display[46] = __familyLabel;
    return buildLine_(row);
  })()`, context);
}

const cases = new Map([
  ['Alimentaire standard', 'food'],
  ['Halieutiques', 'seafood'],
  ['Miel', 'honey'],
  ['Habits / Vêtements', 'clothing'],
  ['Non alimentaire', 'non_food'],
  ['  Alimentaire   standard  ', 'food'],
  ['Habits\u00a0/\u202fVêtements', 'clothing'],
  ['non_food', 'non_food'],
]);

for (const [label, expected] of cases) {
  const payload = buildLineWithFamily(label);
  assert.strictEqual(
    payload.tariff_family_code,
    expected,
    `tariff family ${JSON.stringify(label)} must map to ${expected}`
  );
}

assert.throws(
  () => buildLineWithFamily('Famille inconnue'),
  /Famille tarifaire non mappée/i,
  'an unknown non-empty tariff family must block sync instead of being silently dropped'
);

console.log('TARIFF_FAMILY_PAYLOAD=PASS');
