/* DallyTrading Freight — projection CRM → classeur.
 *
 * Ce fichier ne fait circuler l'information que dans un sens : Odoo décide,
 * le classeur reçoit. Il complète — sans le remplacer — le sens historique
 * `Code.gs` / `Cash.gs`, où c'est la feuille qui pousse vers Odoo.
 *
 * ## Pourquoi c'est le classeur qui va chercher
 *
 * Toute l'autorisation Google vit ici : les portées d'`appsscript.json` et les
 * clés d'API Odoo en Script Properties. Odoo n'a aucun identifiant Google, et
 * en fabriquer un pour cette projection créerait un secret de production là où
 * il n'y en avait pas. Le transport part donc d'ici — ce qui ne déplace
 * l'autorité métier nulle part.
 *
 * ## La règle qui gouverne toutes les écritures
 *
 * On cherche l'identité, **puis** on décide. Jamais d'ajout sans recherche
 * préalable : un `appendRow` aveugle transformerait chaque reprise en
 * doublon, et un accusé de réception perdu suffit à provoquer une reprise.
 */

const DALLY_OUTBOX = Object.freeze({
  batchPath: '/api/v1/freight/sheet-outbox',
  ackPath: '/api/v1/freight/sheet-outbox/ack',
  property: 'DALLY_FREIGHT_SHEET_API_KEY',
  // Les libellés du classeur, dans le sens code → texte affiché. L'inverse
  // vit déjà dans `Code.gs` ; les deux tables doivent rester cohérentes.
  familyLabels: Object.freeze({
    food: 'Alimentaire standard', seafood: 'Halieutiques', honey: 'Miel',
    clothing: 'Habits / Vêtements', non_food: 'Non alimentaire',
  }),
  stateLabels: Object.freeze({
    request_received: 'Annonce', goods_received: 'Depose', preparing: 'Pese',
    ready: 'Charge', in_transit: 'Expedie', arrived: 'Arrive',
    delivered: 'Retire', cancelled: 'Annulé',
  }),
  billingLabels: Object.freeze({
    real: 'Poids reel', volumetric: 'Poids volumetrique', quote: 'Sur devis',
  }),
  paymentLabels: Object.freeze({
    cash: 'Espèces', wave: 'Wave', bank_transfer: 'Virement', bank: 'Virement',
    other: 'Autre',
  }),
  cashStateLabels: Object.freeze({
    review: 'À vérifier', validated: 'Validé', cancelled: 'Annulé',
  }),
});

/* ------------------------------------------------------------------ *
 * Déclenchement.
 * ------------------------------------------------------------------ */

/**
 * Installe le minuteur de projection.
 *
 * Séparé du minuteur de `dallySetup()`, qui pousse la feuille **vers** Odoo :
 * les deux sens ont des raisons différentes de tourner, et les mêler
 * empêcherait d'arrêter l'un sans l'autre. Il n'y a pas pour autant de second
 * ordonnanceur ailleurs : le « cron » de projection vit ici, côté Apps Script,
 * parce que c'est ici que vit l'autorisation Google.
 */
function dallySheetProjectionSetup() {
  const existants = ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'dallySheetProjectionTick_');
  existants.forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('dallySheetProjectionTick_').timeBased().everyMinutes(5).create();
  SpreadsheetApp.getActive().toast(
    'Projection CRM → classeur installée (toutes les 5 minutes).', 'Dally CRM', 7);
}

function dallySheetProjectionTick_() {
  try {
    dallySheetProjectionPull();
  } catch (err) {
    // Un passage manqué n'est jamais une perte : les intentions restent dans
    // la boîte d'envoi d'Odoo et le passage suivant les reprendra.
    console.error('Projection CRM → classeur : ' + errorText_(err));
  }
}

/** L'action manuelle du menu. */
function dallySheetProjectionRun() {
  const resultat = dallySheetProjectionPull();
  const echecs = resultat.results.filter(r => !r.ok).length;
  SpreadsheetApp.getActive().toast(
    resultat.count + ' projection(s) traitée(s), ' + echecs + ' en erreur.',
    'Dally CRM', 7);
}

/* ------------------------------------------------------------------ *
 * Entrée : un passage complet du transport.
 * ------------------------------------------------------------------ */

function dallySheetProjectionPull() {
  return withScriptLock_(function () {
    const cfg = readConfig_();
    const batch = apiGet_(DALLY_OUTBOX.batchPath, DALLY_OUTBOX.property, cfg);
    const projections = (batch && batch.projections) || [];
    if (!projections.length) return {count: 0, results: []};

    const results = [];
    for (const projection of projections) {
      // Une projection invalide n'empêche jamais les suivantes d'aboutir.
      try {
        applyProjection_(SpreadsheetApp.getActive(), projection);
        results.push({outbox_id: projection.outbox_id, ok: true});
      } catch (err) {
        results.push({
          outbox_id: projection.outbox_id,
          ok: false,
          permanent: isPermanentProjectionError_(err),
          error: errorText_(err).slice(0, 200),
        });
      }
    }
    // L'accusé part **après** l'écriture. L'inverse ferait perdre une
    // projection dès la première coupure entre les deux.
    apiPost_(DALLY_OUTBOX.ackPath, DALLY_OUTBOX.property, {results: results}, cfg);
    return {count: projections.length, results: results};
  });
}

/** Une erreur de forme ne se réessaie pas : elle se corrige. */
function isPermanentProjectionError_(err) {
  const text = errorText_(err);
  return /onglet introuvable|projection inconnue|identité absente|identité paiement contradictoire|aucune ligne libre/i.test(text);
}

function applyProjection_(spreadsheet, projection) {
  const type = projection && projection.projection_type;
  if (type === 'freight_dossier') return applyDossierProjection_(spreadsheet, projection);
  if (type === 'cash_expense') return applyExpenseProjection_(spreadsheet, projection);
  if (type === 'cash_transfer') return applyTransferProjection_(spreadsheet, projection);
  throw new Error('Projection inconnue : ' + String(type));
}

/* ------------------------------------------------------------------ *
 * Dossiers de fret.
 * ------------------------------------------------------------------ */

/**
 * Écrit — ou met à jour — les lignes d'un dossier.
 *
 * Une ligne par article, retrouvée par sa clé d'article. Une identité déjà
 * présente est mise à jour sur place ; seule une identité réellement absente
 * ajoute une ligne.
 */
function applyDossierProjection_(spreadsheet, projection) {
  const grid = sheetGrid_(spreadsheet, projection.sheet);
  const identity = projection.identity || {};
  const c = DALLY.columns;

  if (!identity.sync_source_key && !identity.global_external_reference) {
    throw new Error('Identité absente : impossible de retrouver la ligne.');
  }

  const articles = projection.articles || [];
  const payments = projection.payments || [];
  const written = [];

  // Les paiements possèdent leur propre identité métier. L'ordre du tableau
  // n'a aucune signification et ne doit jamais décider de la ligne Sheet.
  const paymentByKey = new Map();

  for (const payment of payments) {
    const key = paymentProjectionKey_(payment);

    if (paymentByKey.has(key)) {
      throw new Error(
        'Identité paiement contradictoire : clé dupliquée dans la projection : ' +
        key
      );
    }

    paymentByKey.set(key, payment);
  }

  // Protection contre une réécriture silencieuse d'une ancienne identité.
  // Une clé déjà présente sur ce dossier doit être explicitement portée par
  // l'état Odoo projeté.
  for (let row = grid.firstRow; row <= grid.lastRow(); row++) {
    if (!dossierRowMatches_(grid, row, identity)) continue;

    const existingPaymentKey = grid.text(row, c.paymentKey);

    if (existingPaymentKey && !paymentByKey.has(existingPaymentKey)) {
      throw new Error(
        'Identité paiement contradictoire : clé existante absente de la projection : ' +
        existingPaymentKey
      );
    }
  }

  // Les articles restent retrouvés uniquement par article_key.
  const articleRows = [];
  const articleByRow = new Map();

  for (const article of articles) {
    const row = findOrCreateDossierRow_(
      grid,
      identity,
      article.article_key
    );

    writeDossierRow_(grid, row, projection, article, null);

    articleRows.push(row);
    articleByRow.set(row, article);

    if (!written.includes(row)) written.push(row);
  }

  // Les paiements sont maintenant projetés indépendamment des articles.
  // 1. Une payment_key existante retrouve toujours sa ligne.
  // 2. Une nouvelle payment_key utilise d'abord une ligne article libre.
  // 3. Les paiements supplémentaires utilisent une ligne administrative.
  const usedPaymentRows = new Set();

  for (const payment of payments) {
    const key = paymentProjectionKey_(payment);

    let row = findDossierPaymentRow_(grid, identity, key);

    if (!row) {
      row = articleRows.find(candidate =>
        !usedPaymentRows.has(candidate) &&
        !grid.text(candidate, c.paymentKey)
      ) || 0;
    }

    if (!row) {
      row = findOrCreateDossierPaymentRow_(
        grid,
        identity,
        usedPaymentRows
      );
    }

    const article = articleByRow.get(row) || null;

    writeDossierRow_(
      grid,
      row,
      projection,
      article,
      payment
    );

    usedPaymentRows.add(row);

    if (!written.includes(row)) written.push(row);
  }

  return written;
}

/**
 * Première ligne métier réellement libre.
 *
 * `getLastRow()` n'est pas la dernière ligne métier du classeur : les feuilles
 * de production sont préformatées avec des formules jusqu'en bas. On cherche
 * donc d'abord une ligne dont les colonnes métier sont vides.
 */
function findFreeProjectionRow_(grid, columns) {
  const uniques = [...new Set((columns || []).filter(Boolean))];
  const last = grid.lastRow();

  for (let row = grid.firstRow; row <= last; row++) {
    if (uniques.every(column => !grid.text(row, column))) {
      return row;
    }
  }

  // Cas d'une feuille neuve/non préformatée : la prochaine ligne physique
  // reste utilisable tant qu'elle ne dépasse pas getMaxRows().
  const next = grid.nextRow();
  if (
    next &&
    uniques.every(column => !grid.text(next, column))
  ) {
    return next;
  }

  return 0;
}

function noFreeProjectionRow_() {
  throw new Error(
    'Aucune ligne libre dans le modèle du classeur pour cette projection.'
  );
}

/**
 * Identité canonique d'un paiement projeté.
 */
function paymentProjectionKey_(payment) {
  const key = String(
    payment && payment.payment_key || ''
  ).trim();

  if (!key) {
    throw new Error(
      'Identité absente : clé de paiement manquante.'
    );
  }

  return key;
}

/**
 * Retrouve une ligne par payment_key.
 *
 * La clé est globale : la trouver sur un autre dossier est une corruption,
 * pas une raison de réutiliser cette ligne.
 */
function findDossierPaymentRow_(grid, identity, paymentKey) {
  const c = DALLY.columns;
  let found = 0;

  for (let row = grid.firstRow; row <= grid.lastRow(); row++) {
    if (grid.text(row, c.paymentKey) !== paymentKey) continue;

    if (found) {
      throw new Error(
        'Identité paiement contradictoire : clé dupliquée dans le classeur : ' +
        paymentKey
      );
    }

    found = row;
  }

  if (found && !dossierRowMatches_(grid, found, identity)) {
    throw new Error(
      'Identité paiement contradictoire : la clé ' +
      paymentKey +
      ' appartient à un autre dossier.'
    );
  }

  return found;
}

/**
 * Ligne administrative disponible pour un paiement sans article associé.
 */
function findOrCreateDossierPaymentRow_(grid, identity, reservedRows) {
  const c = DALLY.columns;

  const free = grid.findRow(row =>
    dossierRowMatches_(grid, row, identity) &&
    !grid.text(row, c.articleKey) &&
    !grid.text(row, c.paymentKey) &&
    !reservedRows.has(row)
  );

  if (free) return free;

  const template = findFreeProjectionRow_(grid, [
    c.plannedConsolidation,
    c.dossier,
    c.client,
    c.goodsCategory,
    c.description,
    c.paymentEur,
    c.paymentXof,
    c.articleKey,
    c.paymentKey,
    c.syncSourceKey,
    c.globalExternalReference,
    c.shipmentId,
  ]);

  return template || noFreeProjectionRow_();
}

/**
 * La ligne d'un article, retrouvée par identité — jamais par numéro de ligne.
 *
 * Priorité identique à celle du connecteur historique : clé de source, puis
 * référence globale, puis identifiant de dossier. Le numéro de ligne, lui,
 * change dès qu'on trie le classeur.
 */
function findOrCreateDossierRow_(grid, identity, articleKey) {
  const c = DALLY.columns;
  if (articleKey) {
    const parKey = grid.findRow(row => grid.text(row, c.articleKey) === articleKey);
    if (parKey) return parKey;
  }
  // Un dossier déjà lié mais dont l'article n'a pas encore sa clé : on prend
  // la première ligne du dossier restée sans clé, plutôt que d'en ajouter une.
  const libre = grid.findRow(row =>
    dossierRowMatches_(grid, row, identity) && !grid.text(row, c.articleKey));
  if (libre) return libre;

  const template = findFreeProjectionRow_(grid, [
    c.plannedConsolidation,
    c.dossier,
    c.client,
    c.goodsCategory,
    c.description,
    c.paymentEur,
    c.paymentXof,
    c.articleKey,
    c.paymentKey,
    c.syncSourceKey,
    c.globalExternalReference,
    c.shipmentId,
  ]);

  return template || noFreeProjectionRow_();
}

function dossierRowMatches_(grid, row, identity) {
  const c = DALLY.columns;
  const source = grid.text(row, c.syncSourceKey);
  if (identity.sync_source_key && source) return source === identity.sync_source_key;
  const global = grid.text(row, c.globalExternalReference);
  if (identity.global_external_reference && global) {
    return global === identity.global_external_reference;
  }
  const shipment = grid.text(row, c.shipmentId);
  return !!identity.shipment_id && shipment === String(identity.shipment_id);
}

function writeDossierRow_(grid, row, projection, article, payment) {
  const c = DALLY.columns;
  const identity = projection.identity || {};
  const dossier = projection.dossier || {};
  const client = dossier.customer || {};

  // La clé de paiement est une identité métier, pas une valeur calculée.
  // Une projection n'a jamais le droit d'écraser silencieusement une clé
  // existante par une autre.
  const paymentKey = payment
    ? paymentProjectionKey_(payment)
    : '';

  if (payment) {
    const existingPaymentKey = grid.text(row, c.paymentKey);

    if (existingPaymentKey && existingPaymentKey !== paymentKey) {
      throw new Error(
        'Identité paiement contradictoire : ' +
        existingPaymentKey + ' != ' + paymentKey
      );
    }
  }

  grid.set(row, c.depositDate, dossier.deposit_date || '');
  grid.set(row, c.plannedConsolidation, sheetLiteralText_(dossier.planned_consolidation));
  grid.set(row, c.dossier, sheetLiteralText_(dossier.reference));
  grid.set(row, c.client, sheetLiteralText_(client.name));
  grid.set(row, c.phone, sheetLiteralText_(client.phone));
  grid.set(row, c.address, sheetLiteralText_(client.address));
  grid.set(row, c.email, sheetLiteralText_(client.email));

  grid.set(row, c.parcelState, DALLY_OUTBOX.stateLabels[dossier.state] || '');

  if (article) {
    grid.set(row, c.goodsCategory, sheetLiteralText_(article.goods_category));
    grid.set(row, c.description, sheetLiteralText_(article.description));
    grid.set(row, c.quantity, article.quantity || 0);
    grid.set(row, c.length, article.length_cm || '');
    grid.set(row, c.width, article.width_cm || '');
    grid.set(row, c.height, article.height_cm || '');
    grid.set(row, c.unitVolume, article.unit_volume_cbm || '');
    grid.set(row, c.totalVolume, article.total_volume_cbm || '');
    grid.set(row, c.announcedWeight, article.announced_weight_kg || '');
    grid.set(row, c.exactWeight, article.exact_weight_kg || '');
    grid.set(row, c.billableWeight, article.billable_weight_kg || '');
    grid.set(
      row,
      c.billingMethod,
      DALLY_OUTBOX.billingLabels[article.billing_method] || ''
    );
    grid.set(row, c.appliedPrice, article.applied_unit_price_eur || '');
    grid.set(row, c.totalEur, article.transport_amount_eur || '');
    grid.set(row, c.customsValue, article.customs_value_xof || '');

    // Le libellé attendu par le classeur, jamais le code brut.
    grid.set(
      row,
      c.tariffFamily,
      tariffFamilyLabel_(article.tariff_family_code)
    );

    grid.set(
      row,
      c.articleKey,
      sheetLiteralText_(article.article_key)
    );
  }

  if (payment) {
    grid.set(row, c.paymentEur, payment.amount_eur || '');
    grid.set(row, c.paymentXof, payment.amount_xof || '');
    grid.set(row, c.paymentMethod,
             DALLY_OUTBOX.paymentLabels[payment.payment_method] || '');
    grid.set(row, c.collectedBy, sheetLiteralText_(payment.collected_by));
    grid.set(row, c.paymentFlag, 1);
    grid.set(row, c.paymentKey, sheetLiteralText_(paymentKey));
  }

  grid.set(row, c.partnerId, identity.partner_id || '');
  grid.set(row, c.shipmentId, identity.shipment_id || '');
  grid.set(row, c.saleOrderId, identity.sale_order_id || '');
  grid.set(row, c.invoiceId, identity.invoice_id || '');
  grid.set(row, c.invoiceNumber, sheetLiteralText_(identity.invoice_number));
  grid.set(row, c.syncSourceKey, sheetLiteralText_(identity.sync_source_key));
  grid.set(row, c.globalExternalReference,
           sheetLiteralText_(identity.global_external_reference));
  grid.set(row, c.intakeConsolidationRef,
           sheetLiteralText_(identity.intake_consolidation_ref));
  grid.set(row, c.collectionLocalRef, sheetLiteralText_(identity.collection_local_ref));

  grid.set(row, c.syncStatus, 'Synchronisé');
  grid.set(row, c.lastSync, new Date());
  // Une replanification demandée à la main reste lisible : la projection dit
  // ce qu'Odoo affirme, elle n'efface pas une décision en attente.
  const message = grid.text(row, c.syncMessage);
  grid.set(row, c.syncMessage,
           preserveReplanIntentMessage_(message, 'Projeté depuis le CRM.'));
}

/**
 * Le libellé d'une famille tarifaire.
 *
 * Aucun repli : une famille absente de la table est une erreur de projection,
 * pas une case à laisser vide. La laisser passer ferait disparaître une
 * tarification sans que personne ne le remarque.
 */
function tariffFamilyLabel_(code) {
  const label = DALLY_OUTBOX.familyLabels[String(code || '')];
  if (!label) throw new Error('Famille tarifaire inconnue : ' + String(code));
  return label;
}

/* ------------------------------------------------------------------ *
 * Caisse.
 * ------------------------------------------------------------------ */

function applyExpenseProjection_(spreadsheet, projection) {
  const grid = sheetGrid_(spreadsheet, projection.sheet, DALLY_CASH.firstRow);
  const cols = DALLY_CASH.expense;
  const expense = projection.expense || {};
  const key = expense.external_expense_key;
  if (!key) throw new Error('Identité absente : clé de dépense manquante.');

  const row =
    grid.findRow(r => grid.text(r, cols.key) === key) ||
    findFreeProjectionRow_(grid, [
      cols.key,
      cols.date,
      cols.category,
      cols.description,
      cols.beneficiary,
      cols.gilles,
      cols.alain,
      cols.dalanda,
      cols.total,
      cols.currency,
      cols.reference,
      cols.odooId,
    ]) ||
    noFreeProjectionRow_();
  grid.set(row, cols.key, sheetLiteralText_(key));
  grid.set(row, cols.date, expense.date || '');
  grid.set(row, cols.category, sheetLiteralText_(expense.category));
  grid.set(row, cols.description, sheetLiteralText_(expense.description));
  grid.set(row, cols.beneficiary, sheetLiteralText_(expense.beneficiary));
  // Les trois colonnes d'acteurs du classeur restent la vérité de mise en
  // page : on y répartit ce que l'allocation d'Odoo dit, sans en inventer.
  const parActeur = {};
  (expense.allocations || []).forEach(a => {
    parActeur[String(a.actor || '').trim()] = a.amount || 0;
  });
  grid.set(row, cols.gilles, parActeur.Gilles || '');
  grid.set(row, cols.alain, parActeur.Alain || '');
  grid.set(row, cols.dalanda, parActeur.Dalanda || '');
  grid.set(row, cols.total, expense.total_amount || 0);
  grid.set(row, cols.currency, expense.currency_code === 'XOF' ? 'FCFA' : 'EUR');
  grid.set(row, cols.method, DALLY_OUTBOX.paymentLabels[expense.payment_method] || '');
  grid.set(row, cols.reference, sheetLiteralText_(expense.reference));
  grid.set(row, cols.state, DALLY_OUTBOX.cashStateLabels[expense.state] || '');
  grid.set(row, cols.comment, sheetLiteralText_(expense.comment));
  grid.set(row, cols.syncStatus, 'Synchronisé');
  grid.set(row, cols.odooId, expense.odoo_id || '');
  grid.set(row, cols.lastSync, new Date());
  grid.set(row, cols.syncMessage, 'Projeté depuis le CRM.');
  return row;
}

function applyTransferProjection_(spreadsheet, projection) {
  const grid = sheetGrid_(spreadsheet, projection.sheet, DALLY_CASH.firstRow);
  const cols = DALLY_CASH.transfer;
  const transfer = projection.transfer || {};
  const key = transfer.external_transfer_key;
  if (!key) throw new Error('Identité absente : clé de transfert manquante.');

  const row =
    grid.findRow(r => grid.text(r, cols.key) === key) ||
    findFreeProjectionRow_(grid, [
      cols.key,
      cols.date,
      cols.fromActor,
      cols.toActor,
      cols.amount,
      cols.currency,
      cols.reason,
      cols.odooId,
    ]) ||
    noFreeProjectionRow_();
  grid.set(row, cols.key, sheetLiteralText_(key));
  grid.set(row, cols.date, transfer.date || '');
  grid.set(row, cols.fromActor, sheetLiteralText_(transfer.from_actor));
  grid.set(row, cols.toActor, sheetLiteralText_(transfer.to_actor));
  grid.set(row, cols.amount, transfer.amount || 0);
  grid.set(row, cols.currency, transfer.currency_code === 'XOF' ? 'FCFA' : 'EUR');
  grid.set(row, cols.reason, sheetLiteralText_(transfer.reason));
  grid.set(row, cols.method, DALLY_OUTBOX.paymentLabels[transfer.payment_method] || '');
  grid.set(row, cols.state, DALLY_OUTBOX.cashStateLabels[transfer.state] || '');
  grid.set(row, cols.comment, sheetLiteralText_(transfer.comment));
  grid.set(row, cols.syncStatus, 'Synchronisé');
  grid.set(row, cols.odooId, transfer.odoo_id || '');
  grid.set(row, cols.lastSync, new Date());
  grid.set(row, cols.syncMessage, 'Projeté depuis le CRM.');
  return row;
}

/* ------------------------------------------------------------------ *
 * L'accès à la feuille, isolé pour être éprouvable hors de Google.
 * ------------------------------------------------------------------ */

/**
 * Une vue minimale sur un onglet.
 *
 * Toute écriture passe par ici, ce qui permet à un harnais Node de rejouer
 * exactement la même logique d'UPSERT sans Google — et donc de prouver
 * qu'un rejeu n'ajoute pas de ligne.
 */
function sheetGrid_(spreadsheet, name, firstRow) {
  const sheet = spreadsheet.getSheetByName(name);
  if (!sheet) throw new Error('Onglet introuvable : ' + String(name));
  const start = firstRow || DALLY.firstDataRow;
  return {
    sheet: sheet,
    firstRow: start,
    lastRow: function () { return sheet.getLastRow(); },
    text: function (row, column) {
      const value = sheet.getRange(row, column).getDisplayValue();
      return String(value == null ? '' : value).trim();
    },
    set: function (row, column, value) { sheet.getRange(row, column).setValue(value); },
    findRow: function (predicate) {
      const last = sheet.getLastRow();
      for (let row = start; row <= last; row++) {
        if (predicate(row)) return row;
      }
      return 0;
    },
    nextRow: function () {
      const next = Math.max(sheet.getLastRow() + 1, start);

      if (
        typeof sheet.getMaxRows === 'function' &&
        next > sheet.getMaxRows()
      ) {
        return 0;
      }

      return next;
    },
  };
}
