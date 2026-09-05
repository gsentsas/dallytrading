'use strict';
/*
 * Le contrat « complément » côté connecteur, éprouvé sur le vrai `Code.gs`.
 *
 * Deux risques, tous deux silencieux :
 *
 *  1. `prepareInvoice_` écrivait les références de facture sur TOUTES les
 *     lignes du dossier. Avec une pièce complémentaire, cela ferait dire au
 *     classeur que d'anciens colis appartiennent à une facture qui ne les
 *     contient pas — et personne ne s'en apercevrait avant le rapprochement.
 *
 *  2. `syncPayments_` supprimait toute valeur vide du payload. Or `invoice_id`
 *     vide n'est pas une absence : c'est l'instruction « efface la cible et
 *     reviens à la principale ». La supprimer laissait le serveur conserver
 *     l'ancien complément, et l'encaissement partait sur la mauvaise pièce.
 *
 * Ce harnais charge le connecteur sans Google et observe ce qui part et ce qui
 * s'écrit. Il ne contacte ni Odoo, ni le classeur.
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const racine = path.join(__dirname, '..', 'integrations', 'google-sheets', 'freight-sync');
const code = fs.readFileSync(path.join(racine, 'Code.gs'), 'utf8');

let uuidsDemandes = 0;
const sandbox = {
  console, Date, Map, Set, Object, String, Number, Math, JSON, RegExp, Error, Array,
  Utilities: {
    formatDate: () => '2026-09-05',
    getUuid: () => { uuidsDemandes++; return 'uuid-fabrique-' + uuidsDemandes; },
  },
  PropertiesService: {
    getScriptProperties: () => ({getProperty: () => 'clef-de-banc'}),
  },
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);

const expose = vm.runInContext('({DALLY, prepareInvoice_, syncPayments_})', sandbox);
const DALLY = expose.DALLY;
const C = DALLY.columns;

let appels = [];
let reponseFacture = null;
sandbox.apiPost_ = function (chemin, _propriete, charge) {
  appels.push({chemin, charge: JSON.parse(JSON.stringify(charge))});
  if (chemin === '/api/v1/freight/invoice') return reponseFacture;
  if (chemin === '/api/v1/freight/payment') {
    return {collection_state: 'pending', amount: charge.amount,
            currency: charge.currency_code, invoice_id: 54,
            invoice_number: 'INV/2026/00001'};
  }
  return {cancelled_payment_keys: [], blocked_registered_payment_keys: [],
          already_cancelled_payment_keys: []};
};

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
        setValue(value) { cellules.set(row + ':' + col, value); ecritures.push({row, col, value}); },
      };
    },
    ecritures,
    ecrituresSur: col => ecritures.filter(e => e.col === col),
  };
}

function ligne(numero, cellules) {
  const display = Array(DALLY.maxColumn).fill('');
  const values = Array(DALLY.maxColumn).fill('');
  for (const [colonne, valeur] of Object.entries(cellules)) {
    display[colonne - 1] = valeur == null ? '' : String(valeur);
    values[colonne - 1] = valeur;
  }
  return {row: numero, display, values};
}

const cfg = {migrationMode: false, baseUrl: 'https://odoo.invalid'};
const K1 = 'AIR-DSS-CDG-2026-002-A050|A|1';
const K2 = 'AIR-DSS-CDG-2026-002-A050|A|2';

/** Une ligne article facturable, déjà porteuse de sa clé. */
function ligneArticle(numero, cle, refFacture) {
  return ligne(numero, {
    [C.depositDate]: '2026-09-05',
    [C.dossier]: 'A050',
    [C.client]: 'Client A050',
    [C.shipmentId]: 700,
    [C.globalExternalReference]: 'AIR-DSS-CDG-2026-002-A050',
    [C.articleKey]: cle,
    [C.billingMethod]: 'Réel',
    [C.billableWeight]: 10,
    [C.appliedPrice]: 3.5,
    [C.saleOrderId]: refFacture ? refFacture.so : '',
    [C.invoiceId]: refFacture ? refFacture.inv : '',
    [C.invoiceNumber]: refFacture ? refFacture.num : '',
  });
}

/* =================================================================
 * A. Un complément n'écrit que sur les lignes qu'il couvre
 * ================================================================= */
{
  const rows = [
    ligneArticle(DALLY.firstDataRow, K1, {so: 50, inv: 54, num: 'INV/2026/00001'}),
    ligneArticle(DALLY.firstDataRow + 1, K2, null),
  ];
  reponseFacture = {
    invoice_kind: 'supplement',
    covered_line_keys: [K2],
    sale_order_id: 51, invoice_id: 55, invoice_number: 'INV/2026/00002',
    invoice_state: 'draft', amount_total: 21.0, currency: 'EUR',
  };
  appels = [];
  const onglet = fauxOnglet();
  expose.prepareInvoice_(onglet, rows, cfg, false);

  const surInvoiceId = onglet.ecrituresSur(C.invoiceId);
  assert.strictEqual(surInvoiceId.length, 1,
    'une seule ligne doit recevoir la référence du complément');
  assert.strictEqual(surInvoiceId[0].row, DALLY.firstDataRow + 1,
    'ce doit être la ligne du colis tardif, pas celle du colis historique');
  assert.strictEqual(surInvoiceId[0].value, 55);

  const lignesTouchees = new Set(onglet.ecritures.map(e => e.row));
  assert.ok(!lignesTouchees.has(DALLY.firstDataRow),
    'la ligne couverte par la principale ne doit jamais être réécrite');

  const surSO = onglet.ecrituresSur(C.saleOrderId);
  assert.strictEqual(surSO.length, 1);
  assert.strictEqual(surSO[0].value, 51,
    'la commande rendue est la complémentaire, pas la principale');
  console.log('  OK  A. le complément n\'écrit que sur covered_line_keys');
}

/* =================================================================
 * A bis. Une facture principale garde le comportement historique
 * ================================================================= */
{
  const rows = [
    ligneArticle(DALLY.firstDataRow, K1, null),
    ligneArticle(DALLY.firstDataRow + 1, K2, null),
  ];
  reponseFacture = {
    invoice_kind: 'primary',
    covered_line_keys: [K1, K2],
    sale_order_id: 50, invoice_id: 54, invoice_number: 'INV/2026/00001',
    invoice_state: 'draft', amount_total: 35.0, currency: 'EUR',
  };
  const onglet = fauxOnglet();
  expose.prepareInvoice_(onglet, rows, cfg, false);
  assert.strictEqual(onglet.ecrituresSur(C.invoiceId).length, 2,
    'une principale écrit sur toutes les lignes du dossier, comme avant');
  console.log('  OK  A bis. la facture principale reste inchangée');
}

/* =================================================================
 * A ter. Un complément sans covered_line_keys refuse d'écrire
 * ================================================================= */
{
  const rows = [
    ligneArticle(DALLY.firstDataRow, K1, {so: 50, inv: 54, num: 'INV/2026/00001'}),
    ligneArticle(DALLY.firstDataRow + 1, K2, null),
  ];
  reponseFacture = {
    invoice_kind: 'supplement', covered_line_keys: [],
    sale_order_id: 51, invoice_id: 55, invoice_number: 'INV/2026/00002',
    invoice_state: 'draft', amount_total: 21.0, currency: 'EUR',
  };
  const onglet = fauxOnglet();
  assert.throws(
    () => expose.prepareInvoice_(onglet, rows, cfg, false),
    /covered_line_keys/,
    'sans la liste, écrire partout serait pire que ne rien écrire');
  assert.strictEqual(onglet.ecrituresSur(C.invoiceId).length, 0,
    'aucune référence ne doit avoir été posée avant l\'erreur');
  console.log('  OK  A ter. complément sans covered_line_keys => refus explicite');
}

/* =================================================================
 * B, C, D. La cible de paiement part toujours, vide comprise
 * ================================================================= */
function lignePaiement(numero, invoiceIdCellule) {
  return ligne(numero, {
    [C.depositDate]: '2026-09-05',
    [C.dossier]: 'A050',
    [C.client]: 'Client A050',
    [C.shipmentId]: 700,
    [C.globalExternalReference]: 'AIR-DSS-CDG-2026-002-A050',
    [C.articleKey]: K1,
    [C.paymentKey]: 'A050|P|1',
    [C.paymentEur]: 6,
    [C.paymentXof]: '',
    [C.paymentMethod]: 'Wave',
    [C.collectedBy]: 'Gilles',
    [C.paymentFlag]: 0,
    [C.invoiceId]: invoiceIdCellule,
  });
}

function paiementsEnvoyes(rows) {
  appels = [];
  expose.syncPayments_(fauxOnglet(), rows, cfg, false);
  return appels.filter(a => a.chemin === '/api/v1/freight/payment').map(a => a.charge);
}

{
  const charges = paiementsEnvoyes([lignePaiement(DALLY.firstDataRow, 55)]);
  assert.strictEqual(charges.length, 1);
  assert.strictEqual(charges[0].invoice_id, '55',
    'la cellule renseignée doit voyager jusqu\'au serveur');
  console.log('  OK  B. cellule renseignée => invoice_id transmis');
}

{
  const charges = paiementsEnvoyes([lignePaiement(DALLY.firstDataRow, '')]);
  assert.strictEqual(charges.length, 1);
  assert.ok('invoice_id' in charges[0],
    'la clé doit survivre au nettoyage : vide signifie « efface la cible »');
  assert.strictEqual(charges[0].invoice_id, '',
    'et sa valeur doit rester la chaîne vide, pas une absence');
  console.log('  OK  C. cellule vidée => invoice_id: "" explicite');
}

{
  // D. Le nettoyage générique reste en vigueur pour les autres champs.
  const ligneSansCollecteur = lignePaiement(DALLY.firstDataRow, '');
  ligneSansCollecteur.display[C.collectedBy - 1] = '';
  ligneSansCollecteur.values[C.collectedBy - 1] = '';
  const charges = paiementsEnvoyes([ligneSansCollecteur]);
  assert.ok(!('collected_by' in charges[0]),
    'un autre champ vide doit toujours être supprimé');
  assert.ok('invoice_id' in charges[0],
    'seul invoice_id échappe à la règle');
  console.log('  OK  D. le nettoyage épargne invoice_id et lui seul');
}

console.log('\nTOUS LES CONTRATS COMPLEMENT SONT TENUS');
