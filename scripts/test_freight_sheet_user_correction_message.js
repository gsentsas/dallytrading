'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync('integrations/google-sheets/freight-sync/Code.gs', 'utf8');
const sandbox = {console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

assert.strictEqual(
  typeof sandbox.preserveUserCorrectionMessage_,
  'function',
  'preserveUserCorrectionMessage_ must exist'
);

const correction = 'Correction utilisateur 22/08/2026 : A001 impayé. CRM à réaligner.';
const crm = 'CRM OK • tarif automatic';

assert.strictEqual(
  sandbox.preserveUserCorrectionMessage_(correction, crm),
  correction + ' | ' + crm,
  'user correction must be retained before the CRM result'
);

assert.strictEqual(
  sandbox.preserveUserCorrectionMessage_('CRM ancien', crm),
  crm,
  'ordinary/stale CRM messages must remain replaceable'
);

assert.strictEqual(
  sandbox.preserveUserCorrectionMessage_(correction + ' | ' + crm, crm),
  correction + ' | ' + crm,
  'CRM result must not be duplicated when already present'
);

assert.match(
  code,
  /setCell_\(sheet, row\.row, DALLY\.columns\.syncMessage, preserveUserCorrectionMessage_\(previousMessage, msg\)\)/,
  'syncDossier_ must use the preservation helper when writing syncMessage'
);

console.log('USER_CORRECTION_MESSAGE_PRESERVED=PASS');
