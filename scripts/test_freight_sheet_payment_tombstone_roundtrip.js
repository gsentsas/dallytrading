'use strict';
/*
 * La pierre tombale d'un encaissement, éprouvée dans le sens du retour.
 *
 * `Outbox.gs` neutralise la ligne d'un paiement annulé : la clé reste, le
 * montant part. Reste à prouver que le sens historique — la feuille qui
 * pousse vers Odoo — ne ressuscite pas ce paiement au passage suivant.
 *
 * C'est le vrai risque de la pierre tombale : une ligne qui porte encore une
 * identité de paiement pourrait très bien être renvoyée comme un encaissement
 * actif, et recréditer dans Odoo de l'argent que la maison a désavoué.
 *
 * Ce harnais charge le vrai `Code.gs`, sans Google, et observe exactement ce
 * que `syncPayments_` envoie.
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const racine = path.join(__dirname, '..', 'integrations', 'google-sheets', 'freight-sync');
const code = fs.readFileSync(path.join(racine, 'Code.gs'), 'utf8');

/* --- Le contexte : le vrai connecteur, sans Google ----------------- */

let uuidsDemandes = 0;

const sandbox = {
  console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error, Array,
  Utilities: {
    formatDate: () => '2026-08-29',
    getUuid: () => { uuidsDemandes++; return 'uuid-fabrique-' + uuidsDemandes; },
  },
  PropertiesService: {
    getScriptProperties: () => ({getProperty: () => 'clef-de-banc'}),
  },
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

// `const` au niveau d'un script ne se pose pas sur l'objet global du
// contexte : on le relit par une expression, comme les autres harnais.
const expose = vm.runInContext('({DALLY, syncPayments_})', sandbox);
const DALLY = expose.DALLY;
const C = DALLY.columns;

// L'appel réseau est remplacé après chargement : on veut lire ce qui part,
// pas contacter Odoo.
let appels = [];
sandbox.apiPost_ = function (chemin, _propriete, charge) {
  appels.push({chemin, charge: JSON.parse(JSON.stringify(charge))});
  if (chemin === '/api/v1/freight/payment') {
    return {collection_state: 'pending', amount: charge.amount,
            currency: charge.currency_code};
  }
  return {cancelled_payment_keys: [], blocked_registered_payment_keys: [],
          already_cancelled_payment_keys: []};
};

/* --- Un onglet simulé --------------------------------------------- */

function fauxOnglet() {
  const cellules = new Map();
  const ecritures = [];
  return {
    getRange(row, col) {
      return {
        getDisplayValue() {
          const v = cellules.get(row + ':' + col);
          return v == null ? '' : String(v);
        },
        setValue(value) {
          cellules.set(row + ':' + col, value);
          ecritures.push({row, col, value});
        },
      };
    },
    ecritures,
    ecrituresSur: col => ecritures.filter(e => e.col === col),
  };
}

/** Une ligne du classeur, à la forme que `Code.gs` consomme. */
function ligne(numero, cellules) {
  const display = Array(DALLY.maxColumn).fill('');
  const values = Array(DALLY.maxColumn).fill('');
  for (const [colonne, valeur] of Object.entries(cellules)) {
    display[colonne - 1] = valeur == null ? '' : String(valeur);
    values[colonne - 1] = valeur;
  }
  return {row: numero, display, values};
}

const CLE = 'A012|P|1';
const cfg = {migrationMode: false, baseUrl: 'https://odoo.invalid'};

/** Une ligne article portant la pierre tombale d'un paiement annulé. */
function ligneTombale(numero) {
  return ligne(numero || DALLY.firstDataRow, {
    [C.depositDate]: '2026-08-29',
    [C.dossier]: 'A012',
    [C.client]: 'Client A012',
    [C.shipmentId]: 688,
    [C.globalExternalReference]: 'AIR-DSS-CDG-2026-002-A012',
    [C.syncSourceKey]: 'ops:uuid-a012',
    [C.articleKey]: 'AIR-DSS-CDG-2026-002-A012|A|1',
    // Ce que la projection a écrit : la clé survit, le montant est parti.
    [C.paymentKey]: CLE,
    [C.paymentEur]: '',
    [C.paymentXof]: '',
    [C.paymentMethod]: '',
    [C.collectedBy]: '',
    [C.paymentFlag]: 0,
  });
}

function passage(rows) {
  appels = [];
  uuidsDemandes = 0;
  const onglet = fauxOnglet();
  const resultat = expose.syncPayments_(onglet, rows, cfg, false);
  return {onglet, resultat, appels};
}

const paiements = () => appels.filter(a => a.chemin === '/api/v1/freight/payment');
const reconcile = () => appels.find(a => a.chemin === '/api/v1/freight/payment/reconcile');

/* --- 1. La pierre tombale ne repart jamais comme encaissement ------ */
{
  const {onglet} = passage([ligneTombale()]);

  assert.strictEqual(paiements().length, 0,
                     'aucun paiement ne doit être renvoyé pour une ligne annulée');
  assert.ok(reconcile(), 'le rapprochement doit tout de même avoir lieu');
  assert.deepStrictEqual(reconcile().charge.active_payment_keys, [],
                         'la clé annulée ne doit jamais être déclarée active');
  assert.strictEqual(uuidsDemandes, 0,
                     'aucune clé ne doit être fabriquée pour une ligne annulée');
  assert.strictEqual(onglet.ecrituresSur(C.paymentKey).length, 0,
                     'la clé historique ne doit pas être réécrite');
  assert.strictEqual(onglet.ecrituresSur(C.paymentFlag).length, 0,
                     'le drapeau de règlement ne doit pas repasser à 1');
}

/* --- 2. Rejouer le passage laisse la pierre tombale intacte -------- */
{
  const rows = [ligneTombale()];
  passage(rows);
  const second = passage(rows);

  assert.strictEqual(paiements().length, 0, 'toujours aucun paiement au rejeu');
  assert.deepStrictEqual(second.appels.map(a => a.chemin),
                         ['/api/v1/freight/payment/reconcile'],
                         'le rejeu n’émet que le rapprochement');
  assert.strictEqual(rows[0].display[C.paymentKey - 1], CLE,
                     'la clé reste exactement celle d’origine');
}

/* --- 3. Une pierre tombale n'éteint pas les paiements voisins ------ */
{
  const active = 'A012|P|2';
  const {onglet} = passage([
    ligneTombale(DALLY.firstDataRow),
    ligne(DALLY.firstDataRow + 1, {
      [C.depositDate]: '2026-08-29',
      [C.dossier]: 'A012',
      [C.shipmentId]: 688,
      [C.globalExternalReference]: 'AIR-DSS-CDG-2026-002-A012',
      [C.paymentKey]: active,
      [C.paymentXof]: 50000,
      [C.paymentMethod]: 'Wave',
      [C.collectedBy]: 'Gilles',
    }),
  ]);

  assert.strictEqual(paiements().length, 1, 'seul le paiement vivant part');
  assert.strictEqual(paiements()[0].charge.external_payment_key, active);
  assert.deepStrictEqual(reconcile().charge.active_payment_keys, [active],
                         'la clé annulée reste hors des actives');
  assert.strictEqual(onglet.ecrituresSur(C.paymentFlag).length, 1,
                     'seule la ligne vivante voit son drapeau écrit');
  assert.strictEqual(onglet.ecrituresSur(C.paymentFlag)[0].row,
                     DALLY.firstDataRow + 1);
}

/* --- 4. Une réactivation légitime reste possible ------------------- *
 *
 * Le modèle de facturation autorise la reprise d'une collecte annulée sans
 * écriture comptable, sur sa clé d'origine. La pierre tombale ne doit pas
 * fermer cette porte : c'est la ligne vide qui vaut annulation, pas la clé.
 */
{
  const reprise = ligneTombale();
  // Le logisticien ressaisit le montant sur la même ligne, même clé.
  reprise.display[C.paymentXof - 1] = '50000';
  reprise.values[C.paymentXof - 1] = 50000;
  reprise.display[C.paymentMethod - 1] = 'Wave';
  reprise.values[C.paymentMethod - 1] = 'Wave';
  reprise.display[C.collectedBy - 1] = 'Gilles';
  reprise.values[C.collectedBy - 1] = 'Gilles';

  const {onglet} = passage([reprise]);

  assert.strictEqual(paiements().length, 1, 'la réactivation doit repartir');
  assert.strictEqual(paiements()[0].charge.external_payment_key, CLE,
                     'elle reprend la clé d’origine, jamais une nouvelle');
  assert.strictEqual(paiements()[0].charge.amount, 50000);
  assert.strictEqual(paiements()[0].charge.currency_code, 'XOF');
  assert.deepStrictEqual(reconcile().charge.active_payment_keys, [CLE],
                         'la clé redevient active');
  assert.strictEqual(uuidsDemandes, 0, 'aucune clé fabriquée : celle-ci existe');
  assert.strictEqual(onglet.ecrituresSur(C.paymentFlag).length, 1,
                     'le drapeau de règlement revient à 1');
  assert.strictEqual(onglet.ecrituresSur(C.paymentFlag)[0].value, 1);
}

/* --- 5. Une ligne sans clé ni montant reste ignorée ---------------- */
{
  const vide = ligne(DALLY.firstDataRow, {
    [C.dossier]: 'A012', [C.shipmentId]: 688,
    [C.globalExternalReference]: 'AIR-DSS-CDG-2026-002-A012',
  });
  const {onglet} = passage([vide]);

  assert.strictEqual(paiements().length, 0);
  assert.deepStrictEqual(reconcile().charge.active_payment_keys, []);
  assert.strictEqual(uuidsDemandes, 0,
                     'une ligne sans encaissement ne se voit pas attribuer de clé');
  assert.strictEqual(onglet.ecrituresSur(C.paymentKey).length, 0);
}

console.log('PAYMENT_TOMBSTONE_ROUNDTRIP=PASS');
