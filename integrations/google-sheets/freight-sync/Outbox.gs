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
  goodsCategories: Object.freeze([
    'Cartons', 'Sacs', 'Effets personnels', 'Vetements', 'Vêtements',
    'Meubles', 'Electromenager', 'Fragile', 'Autres', 'Alimentaires',
    'Non Alimentaires', 'Produits halieutiques', 'Miel',
  ]),
  goodsCategoryAliases: Object.freeze({
    'alimentaire': 'Alimentaires',
    'alimentaires': 'Alimentaires',
    'non alimentaire': 'Non Alimentaires',
    'non alimentaires': 'Non Alimentaires',
    'effet personnel': 'Effets personnels',
    'effets personnels': 'Effets personnels',
    'vetement': 'Vêtements',
    'vetements': 'Vêtements',
    'electromenager': 'Electromenager',
    'produit halieutique': 'Produits halieutiques',
    'produits halieutiques': 'Produits halieutiques',
    'halieutique': 'Produits halieutiques',
    'halieutiques': 'Produits halieutiques',
    'miel': 'Miel',
  }),
  goodsCategoryByFamily: Object.freeze({
    food: 'Alimentaires',
    seafood: 'Produits halieutiques',
    honey: 'Miel',
    clothing: 'Vêtements',
    non_food: 'Non Alimentaires',
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

/**
 * Applique un lot Outbox, confirme les écritures et accuse chaque projection.
 *
 * @return {{count: number, results: !Array<!Object>}} Résultat du passage.
 */
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
    // `setValue()` peut être différé par Apps Script. Ne jamais annoncer à
    // Odoo qu'une projection est livrée avant que Google n'ait confirmé les
    // écritures. Si le flush échoue, un rejeu est sûr : les UPSERT sont fondés
    // sur les clés métier et ne créent donc pas de doublon.
    let flushConfirmed = true;
    if (results.some(result => result.ok)) {
      try {
        SpreadsheetApp.flush();
      } catch (err) {
        flushConfirmed = false;
        const message = ('Écriture Google Sheets non confirmée : ' + errorText_(err)).slice(0, 200);
        results.forEach(result => {
          if (!result.ok) return;
          result.ok = false;
          result.permanent = false;
          result.error = message;
        });
      }
    }

    if (flushConfirmed) {
      projections.forEach((projection, index) => {
        const result = results[index];
        if (!result || !result.ok) return;

        try {
          verifyCommittedProjection_(SpreadsheetApp.getActive(), projection);
        } catch (err) {
          result.ok = false;
          result.permanent = false;
          result.error = (
            'Projection Sheet incomplète après flush: ' + errorText_(err)
          ).slice(0, 200);
        }
      });
    }

    // L'accusé part seulement après la confirmation des écritures. L'inverse
    // ferait perdre une projection dès la première erreur différée de Sheets.
    apiPost_(DALLY_OUTBOX.ackPath, DALLY_OUTBOX.property, {results: results}, cfg);
    return {count: projections.length, results: results};
  });
}

/** Une erreur de forme ne se réessaie pas : elle se corrige. */
function isPermanentProjectionError_(err) {
  const text = errorText_(err);
  return /onglet introuvable|projection inconnue|identité absente|aucune ligne libre/i
    .test(text) ||
    /identité (?:article|paiement) contradictoire|catégorie article non mappée/i
      .test(text) ||
    /validation de (?:catégorie|consolidation) incompatible|reprise partielle ambiguë/i
      .test(text);
}

function applyProjection_(spreadsheet, projection) {
  const type = projection && projection.projection_type;
  if (type === 'freight_dossier') return applyDossierProjection_(spreadsheet, projection);
  if (type === 'cash_expense') return applyExpenseProjection_(spreadsheet, projection);
  if (type === 'cash_transfer') return applyTransferProjection_(spreadsheet, projection);
  throw new Error('Projection inconnue : ' + String(type));
}

/**
 * Vérifie l'état relu après le flush, sans réutiliser le cache d'écriture.
 *
 * @param {!Object} spreadsheet Classeur relu après le flush global.
 * @param {!Object} projection Projection Odoo attendue.
 * @return {boolean} Vrai lorsque le type projeté est confirmé ou inchangé.
 */
function verifyCommittedProjection_(spreadsheet, projection) {
  const type = projection && projection.projection_type;
  if (type === 'freight_dossier') {
    return verifyDossierProjectionCommitted_(spreadsheet, projection);
  }
  // Les projections Cash conservent leur contrat actuel. Leur vérification
  // pourra être ajoutée séparément sans élargir ce correctif Freight.
  return true;
}

/**
 * Vérifie qu'une ligne relue porte l'identité canonique du dossier.
 *
 * @param {!Object} grid Grille fraîche construite après le flush.
 * @param {number} row Numéro de la ligne à contrôler.
 * @param {!Object} projection Projection Odoo attendue.
 * @return {void}
 */
function verifyCommittedDossierRow_(grid, row, projection) {
  const c = DALLY.columns;
  const identity = projection.identity || {};
  const dossier = projection.dossier || {};
  const expected = [
    ['plannedConsolidation', c.plannedConsolidation, dossier.planned_consolidation],
    ['dossier', c.dossier, dossier.reference],
    ['shipmentId', c.shipmentId, identity.shipment_id],
    ['syncSourceKey', c.syncSourceKey, identity.sync_source_key],
    ['globalExternalReference', c.globalExternalReference,
      identity.global_external_reference],
  ];

  expected.forEach(([label, column, value]) => {
    if (grid.text(row, column) !== String(value == null ? '' : value).trim()) {
      throw new Error('ligne ' + row + ' : identité ' + label + ' absente ou différente');
    }
  });

  if (grid.text(row, c.syncStatus) !== 'Synchronisé') {
    throw new Error('ligne ' + row + ' : statut de synchronisation absent');
  }
  if (!grid.text(row, c.lastSync)) {
    throw new Error('ligne ' + row + ' : dernière synchronisation absente');
  }
}

/**
 * Vérifie un nombre métier relu, avec la tolérance de son unité.
 *
 * @param {!Object} grid Grille fraîche construite après le flush.
 * @param {number} row Numéro de la ligne à contrôler.
 * @param {string} label Libellé utilisé dans le diagnostic.
 * @param {number} column Colonne contenant la valeur.
 * @param {*} value Valeur attendue de la projection.
 * @param {number} tolerance Écart maximal accepté.
 * @return {void}
 */
function verifyCommittedNumber_(grid, row, label, column, value, tolerance) {
  const expected = Number(value || 0);
  const actual = committedSheetNumber_(grid.text(row, column));
  if (
    !Number.isFinite(expected) ||
    !Number.isFinite(actual) ||
    Math.abs(actual - expected) > tolerance
  ) {
    throw new Error('ligne ' + row + ' : ' + label + ' : valeur différente');
  }
}

/**
 * Vérifie les données métier réellement commises pour un article.
 *
 * @param {!Object} grid Grille fraîche construite après le flush.
 * @param {number} row Numéro de la ligne article.
 * @param {!Object} article Article Odoo attendu.
 * @param {!Object} projection Projection Odoo attendue.
 * @return {void}
 */
function verifyCommittedArticle_(grid, row, article, projection) {
  const c = DALLY.columns;
  const prepared = prepareDossierRowWrite_(
    grid, row, projection, article, null);
  verifyCommittedDossierRow_(grid, row, projection);

  const textFields = [
    ['catégorie article', c.goodsCategory, prepared.goodsCategory],
    ['description article', c.description, article.description],
    ['mode de facturation', c.billingMethod,
      DALLY_OUTBOX.billingLabels[article.billing_method] || ''],
    ['famille tarifaire', c.tariffFamily, prepared.tariffFamily],
  ];
  textFields.forEach(([label, column, value]) => {
    if (grid.text(row, column) !== String(value == null ? '' : value).trim()) {
      throw new Error('ligne ' + row + ' : ' + label + ' : valeur différente');
    }
  });

  [
    ['quantité', c.quantity, article.quantity, 0.0005],
    ['longueur', c.length, article.length_cm, 0.0005],
    ['largeur', c.width, article.width_cm, 0.0005],
    ['hauteur', c.height, article.height_cm, 0.0005],
    ['volume unitaire', c.unitVolume, article.unit_volume_cbm, 0.0000005],
    ['volume total', c.totalVolume, article.total_volume_cbm, 0.0000005],
    ['poids annoncé', c.announcedWeight, article.announced_weight_kg, 0.0005],
    ['poids exact', c.exactWeight, article.exact_weight_kg, 0.0005],
    ['poids facturable', c.billableWeight, article.billable_weight_kg, 0.0005],
    ['prix unitaire appliqué', c.appliedPrice,
      article.applied_unit_price_eur, 0.0005],
    ['montant transport', c.totalEur, article.transport_amount_eur, 0.005],
    ['valeur douanière', c.customsValue, article.customs_value_xof, 0.5],
  ].forEach(([label, column, value, tolerance]) => {
    verifyCommittedNumber_(grid, row, label, column, value, tolerance);
  });
}

/**
 * Convertit un nombre affiché par un classeur fr_FR en valeur comparable.
 *
 * @param {*} value Valeur affichée par Google Sheets.
 * @return {number} Nombre normalisé, zéro pour une cellule vide ou NaN.
 */
function committedSheetNumber_(value) {
  let text = String(value == null ? '' : value)
    .replace(/[\s\u00A0\u202F]/g, '')
    .replace(/[^0-9,.-]/g, '');
  if (!text) return 0;

  const comma = text.lastIndexOf(',');
  const dot = text.lastIndexOf('.');
  if (comma > dot) {
    text = text.replace(/\./g, '').replace(',', '.');
  } else if (dot > comma) {
    text = text.replace(/,/g, '');
  }
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : NaN;
}

/**
 * Vérifie l'état persistant d'un paiement actif ou annulé.
 *
 * @param {!Object} grid Grille fraîche construite après le flush.
 * @param {number} row Numéro de la ligne paiement.
 * @param {!Object} payment Paiement Odoo attendu.
 * @param {!Object} projection Projection Odoo attendue.
 * @return {void}
 */
function verifyCommittedPayment_(grid, row, payment, projection) {
  const c = DALLY.columns;
  const cancelled = paymentIsCancelled_(payment);
  verifyCommittedDossierRow_(grid, row, projection);

  if (cancelled) {
    if (
      grid.text(row, c.paymentEur) ||
      grid.text(row, c.paymentXof) ||
      grid.text(row, c.paymentMethod) ||
      grid.text(row, c.collectedBy) ||
      grid.text(row, c.paymentFlag) !== '0'
    ) {
      throw new Error('ligne ' + row + ' : paiement annulé non neutralisé');
    }
    return;
  }

  if (grid.text(row, c.paymentFlag) !== '1') {
    throw new Error('ligne ' + row + ' : paiement actif non comptabilisé');
  }

  const expectedEur = Number(payment.amount_eur || 0);
  const expectedXof = Number(payment.amount_xof || 0);
  const actualEur = committedSheetNumber_(grid.text(row, c.paymentEur));
  const actualXof = committedSheetNumber_(grid.text(row, c.paymentXof));
  if (
    !Number.isFinite(actualEur) || Math.abs(actualEur - expectedEur) > 0.005 ||
    !Number.isFinite(actualXof) || Math.abs(actualXof - expectedXof) > 0.5
  ) {
    throw new Error('ligne ' + row + ' : montant du paiement différent');
  }

  const method = DALLY_OUTBOX.paymentLabels[payment.payment_method] || '';
  if (grid.text(row, c.paymentMethod) !== method) {
    throw new Error('ligne ' + row + ' : mode de paiement différent');
  }
  if (grid.text(row, c.collectedBy) !== String(payment.collected_by || '').trim()) {
    throw new Error('ligne ' + row + ' : encaisseur différent');
  }
}

/**
 * Relit le dossier depuis Google et refuse toute projection partielle.
 *
 * Chaque clé attendue doit être unique, chaque ligne B/C doit être expliquée,
 * et aucune identité en mémoire pendant l'écriture ne vaut preuve de commit.
 *
 * @param {!Object} spreadsheet Classeur relu après le flush global.
 * @param {!Object} projection Projection Freight Odoo attendue.
 * @return {boolean} Vrai lorsque toutes les lignes commises sont cohérentes.
 */
function verifyDossierProjectionCommitted_(spreadsheet, projection) {
  const grid = sheetGrid_(spreadsheet, projection.sheet);
  const c = DALLY.columns;
  const dossier = projection.dossier || {};
  const articles = projection.articles || [];
  const payments = projection.payments || [];
  const articleByKey = new Map();
  const paymentByKey = new Map();

  articles.forEach(article => {
    const key = String(article && article.article_key || '').trim();
    if (!key) throw new Error('clé article attendue absente');
    if (articleByKey.has(key)) throw new Error('clé article attendue dupliquée : ' + key);
    articleByKey.set(key, article);
  });

  payments.forEach(payment => {
    const key = paymentProjectionKey_(payment);
    if (paymentByKey.has(key)) throw new Error('clé paiement attendue dupliquée : ' + key);
    paymentByKey.set(key, payment);
  });

  articleByKey.forEach((article, key) => {
    const rows = grid.findRows(row => grid.text(row, c.articleKey) === key);
    if (rows.length !== 1) {
      throw new Error('clé article ' + key + ' présente ' + rows.length + ' fois');
    }
    verifyCommittedArticle_(grid, rows[0], article, projection);
  });

  paymentByKey.forEach((payment, key) => {
    const rows = grid.findRows(row => grid.text(row, c.paymentKey) === key);
    if (paymentIsCancelled_(payment) && rows.length === 0) return;
    if (rows.length !== 1) {
      throw new Error('clé paiement ' + key + ' présente ' + rows.length + ' fois');
    }
    verifyCommittedPayment_(grid, rows[0], payment, projection);
  });

  const planned = String(dossier.planned_consolidation || '').trim();
  const reference = String(dossier.reference || '').trim();
  const dossierRows = grid.findRows(row =>
    grid.text(row, c.plannedConsolidation) === planned &&
    grid.text(row, c.dossier) === reference
  );

  dossierRows.forEach(row => {
    const articleKey = grid.text(row, c.articleKey);
    const paymentKey = grid.text(row, c.paymentKey);
    if (articleKey && !articleByKey.has(articleKey)) {
      throw new Error('ligne ' + row + ' : clé article parasite');
    }
    if (paymentKey && !paymentByKey.has(paymentKey)) {
      throw new Error('ligne ' + row + ' : clé paiement parasite');
    }
    if (!articleKey && !paymentKey) {
      throw new Error('ligne ' + row + ' : ligne partielle résiduelle');
    }
    verifyCommittedDossierRow_(grid, row, projection);
  });

  return true;
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
  const articleByKey = new Map();

  // Toutes les identités sont validées avant la première écriture. Une erreur
  // de payload ne doit jamais laisser un nouveau squelette de ligne derrière
  // elle.
  for (const article of articles) {
    const key = String(article && article.article_key || '').trim();
    if (!key) {
      throw new Error('Identité absente : clé article manquante.');
    }
    if (articleByKey.has(key)) {
      throw new Error(
        'Identité article contradictoire : clé dupliquée dans la projection : ' +
        key
      );
    }
    articleByKey.set(key, article);
  }

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

  const articlePlans = planDossierArticleRows_(grid, projection, articles);
  const articleRows = articlePlans.map(plan => plan.row);
  const articleByRow = new Map();
  articlePlans.forEach(plan => articleByRow.set(plan.row, plan.article));

  // Les paiements sont maintenant projetés indépendamment des articles.
  // 1. Une payment_key existante retrouve toujours sa ligne.
  // 2. Une nouvelle payment_key utilise d'abord une ligne article libre.
  // 3. Les paiements supplémentaires utilisent une ligne administrative.
  const usedPaymentRows = new Set();
  const reservedRows = new Set(articleRows);
  const paymentPlans = [];

  for (const payment of payments) {
    const key = paymentProjectionKey_(payment);

    let row = findDossierPaymentRow_(grid, projection, key);

    // Une annulation neutralise une ligne existante ; elle n'en ouvre jamais.
    // Sans ligne, cet encaissement n'a jamais atteint le classeur : lui en
    // allouer une y inscrirait un paiement qui n'y a jamais figuré.
    if (!row && paymentIsCancelled_(payment)) continue;

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
        usedPaymentRows,
        reservedRows
      );
    }

    const article = articleByRow.get(row) || null;
    paymentPlans.push({row: row, article: article, payment: payment});
    usedPaymentRows.add(row);
    reservedRows.add(row);
    grid.reserve(row);
  }

  // Catégories, validations et valeurs dérivées de toutes les lignes sont
  // prêtes avant la première écriture métier.
  articlePlans.forEach(plan => {
    plan.prepared = prepareDossierRowWrite_(
      grid, plan.row, projection, plan.article, null);
  });
  paymentPlans.forEach(plan => {
    plan.prepared = prepareDossierRowWrite_(
      grid, plan.row, projection, plan.article, plan.payment);
  });

  articlePlans.forEach(plan => {
    writeDossierRow_(
      grid, plan.row, projection, plan.article, null, plan.prepared);
    if (!written.includes(plan.row)) written.push(plan.row);
  });

  paymentPlans.forEach(plan => {
    writeDossierRow_(
      grid, plan.row, projection, plan.article, plan.payment, plan.prepared);
    if (!written.includes(plan.row)) written.push(plan.row);
  });

  return written;
}

/**
 * Première ligne métier réellement libre.
 *
 * `getLastRow()` n'est pas la dernière ligne métier du classeur : les feuilles
 * de production sont préformatées avec des formules jusqu'en bas. On cherche
 * donc d'abord une ligne dont les colonnes métier sont vides.
 */
function findFreeProjectionRow_(grid, columns, reservedRows) {
  const uniques = [...new Set((columns || []).filter(Boolean))];
  const reserved = reservedRows || new Set();
  const last = grid.lastRow();

  for (let row = grid.firstRow; row <= last; row++) {
    if (!reserved.has(row) && uniques.every(column => !grid.text(row, column))) {
      return row;
    }
  }

  // Cas d'une feuille neuve/non préformatée : la prochaine ligne physique
  // reste utilisable tant qu'elle ne dépasse pas getMaxRows().
  const next = grid.nextRow();
  if (
    next &&
    !reserved.has(next) &&
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
 * Un paiement annulé — une identité qui subsiste, un encaissement qui non.
 *
 * C'est toute la différence que la garde d'identité doit savoir lire : une
 * clé qu'Odoo déclare annulée reste une clé qu'Odoo connaît, tandis qu'une
 * clé absente de la projection reste une contradiction.
 *
 * Un paiement sans état déclaré est actif : les projections antérieures à ce
 * champ décrivent toutes de l'argent reçu, et un doute sur un encaissement ne
 * doit jamais l'effacer du classeur.
 */
function paymentIsCancelled_(payment) {
  return String(payment && payment.state || '').trim() === 'cancelled';
}

/**
 * Retrouve une ligne par payment_key.
 *
 * La clé est globale : la trouver sur un autre dossier est une corruption,
 * pas une raison de réutiliser cette ligne.
 */
function findDossierPaymentRow_(grid, projection, paymentKey) {
  const c = DALLY.columns;
  const identity = projection.identity || {};
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

  if (
    found &&
    !dossierRowMatches_(grid, found, identity) &&
    !dossierRowCanAdoptIdentity_(grid, found, projection)
  ) {
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
function findOrCreateDossierPaymentRow_(
  grid,
  identity,
  usedPaymentRows,
  reservedRows
) {
  const c = DALLY.columns;

  const free = grid.findRow(row =>
    dossierRowMatches_(grid, row, identity) &&
    !grid.text(row, c.articleKey) &&
    !grid.text(row, c.paymentKey) &&
    !usedPaymentRows.has(row) &&
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
  ], reservedRows);

  return template || noFreeProjectionRow_();
}

/**
 * Prépare les lignes article sans écrire dans le classeur.
 *
 * Une ligne partielle créée par une ancienne erreur n'est récupérable que si
 * elle appartient sans ambiguïté au même dossier et ne porte encore aucune
 * identité ni donnée d'article ou de paiement. Des lignes partielles en excès
 * sont une anomalie explicite : les attribuer silencieusement détruirait leur
 * provenance.
 */
function planDossierArticleRows_(grid, projection, articles) {
  const c = DALLY.columns;
  const identity = projection.identity || {};
  const reservedRows = new Set();
  const plans = [];
  const unresolved = [];

  articles.forEach((article, index) => {
    const key = String(article.article_key || '').trim();
    const matches = grid.findRows(row => grid.text(row, c.articleKey) === key);

    if (matches.length > 1) {
      throw new Error(
        'Identité article contradictoire : clé dupliquée dans le classeur : ' +
        key
      );
    }

    if (matches.length === 1) {
      const row = matches[0];
      if (
        !dossierRowMatches_(grid, row, identity) &&
        !dossierRowCanAdoptIdentity_(grid, row, projection)
      ) {
        throw new Error(
          'Identité article contradictoire : la clé ' + key +
          ' appartient à un autre dossier.'
        );
      }
      reservedRows.add(row);
      plans[index] = {row: row, article: article};
    } else {
      unresolved.push({article: article, index: index});
    }
  });

  const linkedRows = grid.findRows(row =>
    dossierRowMatches_(grid, row, identity) &&
    !grid.text(row, c.articleKey) &&
    !grid.text(row, c.paymentKey) &&
    !reservedRows.has(row)
  );

  const partialRows = grid.findRows(row =>
    dossierPartialRowMatches_(grid, row, projection) &&
    !reservedRows.has(row)
  );

  if (linkedRows.length + partialRows.length > unresolved.length) {
    throw new Error(
      'Reprise partielle ambiguë : ' +
      (linkedRows.length + partialRows.length) +
      ' ligne(s) candidate(s) pour ' + unresolved.length +
      ' article(s) sans ligne.'
    );
  }

  const reusableRows = linkedRows.concat(partialRows);

  unresolved.forEach((entry, reusableIndex) => {
    let row = reusableRows[reusableIndex] || 0;

    if (!row) {
      row = findOrCreateDossierRow_(
        grid, identity, entry.article.article_key, reservedRows);
    }

    reservedRows.add(row);
    grid.reserve(row);
    plans[entry.index] = {row: row, article: entry.article};
  });

  return plans;
}

/**
 * La ligne d'un article, retrouvée par identité — jamais par numéro de ligne.
 */
function findOrCreateDossierRow_(grid, identity, articleKey, reservedRows) {
  const c = DALLY.columns;
  const reserved = reservedRows || new Set();
  if (articleKey) {
    const parKey = grid.findRow(row =>
      !reserved.has(row) && grid.text(row, c.articleKey) === articleKey);
    if (parKey) return parKey;
  }

  const libre = grid.findRow(row =>
    !reserved.has(row) &&
    dossierRowMatches_(grid, row, identity) &&
    !grid.text(row, c.articleKey) &&
    !grid.text(row, c.paymentKey));
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
  ], reserved);

  return template || noFreeProjectionRow_();
}

/** Une ancienne ligne interrompue, encore sans propriétaire ni contenu. */
function dossierPartialRowMatches_(grid, row, projection) {
  const c = DALLY.columns;
  const dossier = projection.dossier || {};
  const client = dossier.customer || {};
  const planned = String(dossier.planned_consolidation || '').trim();
  const reference = String(dossier.reference || '').trim();

  if (
    grid.text(row, c.plannedConsolidation) !== planned ||
    grid.text(row, c.dossier) !== reference
  ) {
    return false;
  }

  const ownership = [
    c.articleKey, c.paymentKey, c.syncSourceKey,
    c.globalExternalReference, c.shipmentId, c.partnerId,
    c.saleOrderId, c.invoiceId, c.invoiceNumber,
    c.intakeConsolidationRef, c.collectionLocalRef,
    c.syncStatus, c.lastSync,
  ];
  if (ownership.some(column => grid.text(row, column))) return false;

  const articleOrPayment = [
    c.goodsCategory, c.description, c.quantity, c.length, c.width, c.height,
    c.unitVolume, c.totalVolume, c.announcedWeight, c.exactWeight,
    c.billableWeight, c.appliedPrice, c.totalEur, c.customsValue,
    c.tariffFamily, c.paymentEur, c.paymentXof, c.paymentMethod,
    c.collectedBy,
  ];
  if (articleOrPayment.some(column => grid.text(row, column))) return false;
  const paymentFlag = grid.text(row, c.paymentFlag);
  if (paymentFlag && paymentFlag !== '0') return false;

  const expectedClient = String(client.name || '').trim();
  const expectedPhone = String(client.phone || '').trim();
  const rowClient = grid.text(row, c.client);
  const rowPhone = grid.text(row, c.phone);

  if (rowClient && rowClient !== expectedClient) return false;
  if (rowPhone && rowPhone !== expectedPhone) return false;
  return true;
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

/** Autorise une clé précoce à recevoir l'identité du dossier attendu. */
function dossierRowCanAdoptIdentity_(grid, row, projection) {
  const c = DALLY.columns;
  const dossier = projection.dossier || {};
  const client = dossier.customer || {};
  const ownership = [
    c.syncSourceKey, c.globalExternalReference, c.shipmentId, c.partnerId,
    c.saleOrderId, c.invoiceId, c.invoiceNumber,
    c.intakeConsolidationRef, c.collectionLocalRef,
  ];

  if (ownership.some(column => grid.text(row, column))) return false;

  const expected = [
    [c.plannedConsolidation, dossier.planned_consolidation],
    [c.dossier, dossier.reference],
    [c.client, client.name],
    [c.phone, client.phone],
  ];

  return expected.every(([column, value]) => {
    const existing = grid.text(row, column);
    return !existing || existing === String(value || '').trim();
  });
}

/** Valide et calcule toutes les valeurs fragiles avant la première écriture. */
function prepareDossierRowWrite_(grid, row, projection, article, payment) {
  const c = DALLY.columns;
  const identity = projection.identity || {};
  const dossier = projection.dossier || {};
  const plannedRaw = String(dossier.planned_consolidation || '').trim();
  const dossierReference = String(dossier.reference || '').trim();

  if (!plannedRaw) {
    throw new Error('Identité absente : consolidation planifiée manquante.');
  }
  if (!dossierReference) {
    throw new Error('Identité absente : référence dossier manquante.');
  }

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

  const plannedConsolidation = sheetLiteralText_(plannedRaw);
  assertExtendableStrictList_(
    grid.validation(row, c.plannedConsolidation),
    'Validation de consolidation incompatible'
  );

  let goodsCategory = '';
  let tariffFamily = '';

  if (article) {
    const validation = grid.validation(row, c.goodsCategory);
    const validationInfo = strictValidationInfo_(validation);

    if (validationInfo.strict && !validationInfo.list) {
      throw new Error(
        'Validation de catégorie incompatible : la colonne G n’est pas une liste.'
      );
    }

    const allowed = validationInfo.list
      ? validationInfo.allowed
      : DALLY_OUTBOX.goodsCategories.slice();
    goodsCategory = canonicalGoodsCategory_(article, allowed);

    if (
      validationInfo.list &&
      !validationInfo.allowed.some(value => String(value) === goodsCategory)
    ) {
      throw new Error(
        'Validation de catégorie incompatible : valeur non autorisée : ' +
        goodsCategory
      );
    }

    tariffFamily = tariffFamilyLabel_(article.tariff_family_code);
  }

  return {
    plannedConsolidation: plannedConsolidation,
    dossierReference: sheetLiteralText_(dossierReference),
    goodsCategory: goodsCategory,
    tariffFamily: tariffFamily,
    paymentKey: paymentKey,
  };
}

function writeDossierRow_(grid, row, projection, article, payment, prepared) {
  const c = DALLY.columns;
  const identity = projection.identity || {};
  const dossier = projection.dossier || {};
  const client = dossier.customer || {};
  const values = prepared || prepareDossierRowWrite_(
    grid, row, projection, article, payment);

  const validationChanged = grid.extendStrictListValidation(
    row,
    c.plannedConsolidation,
    values.plannedConsolidation
  );
  if (validationChanged) {
    SpreadsheetApp.flush();
  }

  // En cas d'erreur sur un champ métier ultérieur, le rejeu doit retrouver
  // cette même ligne au lieu d'en allouer une nouvelle.
  if (article) {
    grid.set(row, c.articleKey, sheetLiteralText_(article.article_key));
  }
  if (payment) {
    grid.set(row, c.paymentKey, sheetLiteralText_(values.paymentKey));
  }
  grid.set(row, c.shipmentId, identity.shipment_id || '');
  grid.set(row, c.syncSourceKey, sheetLiteralText_(identity.sync_source_key));
  grid.set(row, c.globalExternalReference,
           sheetLiteralText_(identity.global_external_reference));
  grid.set(row, c.intakeConsolidationRef,
           sheetLiteralText_(identity.intake_consolidation_ref));

  grid.set(row, c.depositDate, dossier.deposit_date || '');
  grid.set(row, c.plannedConsolidation, values.plannedConsolidation);
  grid.set(row, c.dossier, values.dossierReference);
  grid.set(row, c.client, sheetLiteralText_(client.name));
  grid.set(row, c.phone, sheetLiteralText_(client.phone));
  grid.set(row, c.address, sheetLiteralText_(client.address));
  grid.set(row, c.email, sheetLiteralText_(client.email));

  grid.set(row, c.parcelState, DALLY_OUTBOX.stateLabels[dossier.state] || '');

  if (article) {
    grid.set(row, c.goodsCategory, values.goodsCategory);
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
      values.tariffFamily
    );
  }

  if (payment) {
    // Un paiement annulé garde son identité et perd son montant : la ligne
    // cesse de compter comme encaissement sans cesser d'être reconnaissable.
    // Effacer la clé rendrait la ligne indistinguable d'une ligne parasite,
    // et la ligne métier elle-même n'est jamais supprimée.
    const cancelled = paymentIsCancelled_(payment);
    grid.set(row, c.paymentEur, cancelled ? '' : (payment.amount_eur || ''));
    grid.set(row, c.paymentXof, cancelled ? '' : (payment.amount_xof || ''));
    grid.set(row, c.paymentMethod, cancelled ? '' :
             (DALLY_OUTBOX.paymentLabels[payment.payment_method] || ''));
    grid.set(row, c.collectedBy, cancelled ? '' :
             sheetLiteralText_(payment.collected_by));
    grid.set(row, c.paymentFlag, cancelled ? 0 : 1);
  }

  grid.set(row, c.partnerId, identity.partner_id || '');
  grid.set(row, c.saleOrderId, identity.sale_order_id || '');
  grid.set(row, c.invoiceId, identity.invoice_id || '');
  grid.set(row, c.invoiceNumber, sheetLiteralText_(identity.invoice_number));
  grid.set(row, c.collectionLocalRef, sheetLiteralText_(identity.collection_local_ref));

  grid.set(row, c.syncStatus, 'Synchronisé');
  // Une replanification demandée à la main reste lisible : la projection dit
  // ce qu'Odoo affirme, elle n'efface pas une décision en attente.
  const message = grid.text(row, c.syncMessage);
  // Une ligne qui porte une clé sans montant doit dire pourquoi : sans cela,
  // elle se lit comme un encaissement perdu.
  grid.set(row, c.syncMessage, preserveReplanIntentMessage_(
    message,
    payment && paymentIsCancelled_(payment)
      ? 'Projeté depuis le CRM. Encaissement annulé.'
      : 'Projeté depuis le CRM.'));
  grid.set(row, c.lastSync, new Date());
}

/** Décrit une validation stricte sans la modifier. */
function strictValidationInfo_(validation) {
  if (!validation || validation.getAllowInvalid() !== false) {
    return {strict: false, list: false, allowed: []};
  }

  const criteria = validation.getCriteriaType();
  const criteriaName = String(criteria);
  if (criteriaName !== 'VALUE_IN_LIST' && criteriaName !== 'ONE_OF_LIST') {
    return {strict: true, list: false, allowed: []};
  }

  const criteriaValues = validation.getCriteriaValues();
  if (!Array.isArray(criteriaValues[0])) {
    return {strict: true, list: false, allowed: []};
  }

  return {strict: true, list: true, allowed: criteriaValues[0].slice()};
}

/** Refuse une validation stricte que la projection ne sait pas étendre. */
function assertExtendableStrictList_(validation, errorPrefix) {
  const info = strictValidationInfo_(validation);
  if (!info.strict || info.list) return;
  throw new Error(errorPrefix + ' : la cellule n’utilise pas une liste.');
}

/** Produit une clé stable pour les variantes typographiques de catégorie. */
function normalizeGoodsCategory_(value) {
  return String(value || '')
    .replace(/[\u00A0\u202F]/g, ' ')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

/** Choisit un libellé G autorisé, d'abord par valeur puis par famille tarifaire. */
function canonicalGoodsCategory_(article, allowedValues) {
  const raw = String(article && article.goods_category || '').trim();
  const allowed = (allowedValues || []).map(value => String(value));

  if (allowed.includes(raw)) return raw;

  const alias = DALLY_OUTBOX.goodsCategoryAliases[
    normalizeGoodsCategory_(raw)
  ];
  if (alias && allowed.includes(alias)) return alias;

  const family = DALLY_OUTBOX.goodsCategoryByFamily[
    String(article && article.tariff_family_code || '').trim().toLowerCase()
  ];
  if (family && allowed.includes(family)) return family;

  throw new Error(
    'Catégorie article non mappée : ' + raw +
    ' / famille ' + String(article && article.tariff_family_code || '')
  );
}

/**
 * Étend seulement une liste stricte déjà posée sur la cellule.
 *
 * La copie conserve le texte d'aide et les options de la règle. Les autres
 * types de validation restent intacts afin que leur rejet normal reste
 * visible au transport.
 */
function extendStrictListValidation_(range, value) {
  const validation = range.getDataValidation();
  if (!validation || validation.getAllowInvalid() !== false) return false;

  const projected = String(value);
  if (!projected) return false;

  const criteria = validation.getCriteriaType();
  const criteriaName = String(criteria);
  if (criteriaName !== 'VALUE_IN_LIST' && criteriaName !== 'ONE_OF_LIST') return false;

  const criteriaValues = validation.getCriteriaValues();
  if (!Array.isArray(criteriaValues[0])) return false;
  const allowed = criteriaValues[0].slice();

  if (allowed.some(existing => String(existing) === projected)) return false;

  const updatedCriteriaValues = criteriaValues.slice();
  updatedCriteriaValues[0] = allowed.concat([projected]);
  const extended = validation.copy()
    .withCriteria(criteria, updatedCriteriaValues)
    .setAllowInvalid(false)
    .build();
  range.setDataValidation(extended);
  return true;
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
  const initialLast = sheet.getLastRow();
  const width =
    typeof sheet.getMaxColumns === 'function'
      ? sheet.getMaxColumns()
      : DALLY.maxColumn;

  const count = Math.max(0, initialLast - start + 1);

  // One Google read for the complete useful grid.
  // Searches below operate only on this in-memory snapshot.
  const display = count
    ? sheet.getRange(start, 1, count, width).getDisplayValues()
    : [];

  let logicalLast = initialLast;

  function normalize_(value) {
    return String(value == null ? '' : value).trim();
  }

  function ensureRow_(row) {
    const index = row - start;
    if (index < 0) return -1;

    while (display.length <= index) {
      display.push(Array(width).fill(''));
    }

    return index;
  }

  return {
    sheet: sheet,
    firstRow: start,

    lastRow: function () {
      return logicalLast;
    },

    text: function (row, column) {
      const index = row - start;

      if (
        index < 0 ||
        column < 1 ||
        column > width ||
        !display[index]
      ) {
        return '';
      }

      return normalize_(display[index][column - 1]);
    },

    set: function (row, column, value) {
      sheet.getRange(row, column).setValue(value);

      const index = ensureRow_(row);

      if (index >= 0 && column >= 1 && column <= width) {
        display[index][column - 1] = value;
      }

      if (row > logicalLast) {
        logicalLast = row;
      }
    },

    extendStrictListValidation: function (row, column, value) {
      return extendStrictListValidation_(sheet.getRange(row, column), value);
    },

    validation: function (row, column) {
      return sheet.getRange(row, column).getDataValidation();
    },

    findRow: function (predicate) {
      for (let row = start; row <= logicalLast; row++) {
        if (predicate(row)) return row;
      }
      return 0;
    },

    findRows: function (predicate) {
      const rows = [];
      for (let row = start; row <= logicalLast; row++) {
        if (predicate(row)) rows.push(row);
      }
      return rows;
    },

    reserve: function (row) {
      ensureRow_(row);
      if (row > logicalLast) logicalLast = row;
    },

    nextRow: function () {
      const next = Math.max(logicalLast + 1, start);

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
