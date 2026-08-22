/* DallyTrading — PDF export for the selected invoice.
 * Loaded in the same bound Apps Script project as Code.gs.
 * There is deliberately NO second onOpen(): Code.gs calls dallyPdfOnOpen_().
 */

function dallyPdfOnOpen_() {
  SpreadsheetApp.getUi()
    .createMenu('Factures DallyTrading')
    .addItem('Exporter la facture en PDF', 'exporterFacturePDF')
    .addToUi();
}

function exporterFacturePDF() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName('Facture impression');
  if (!sh) {
    SpreadsheetApp.getUi().alert("L'onglet 'Facture impression' est introuvable.");
    return;
  }

  const dossier = String(sh.getRange('K3').getDisplayValue() || '').trim();
  if (!dossier) {
    SpreadsheetApp.getUi().alert('Veuillez sélectionner un numéro de dossier en K3.');
    return;
  }

  SpreadsheetApp.flush();

  const params = [
    'format=pdf',
    'size=A4',
    'portrait=true',
    'fitw=true',
    'sheetnames=false',
    'printtitle=false',
    'pagenumbers=false',
    'gridlines=false',
    'fzr=false',
    'top_margin=0.30',
    'bottom_margin=0.30',
    'left_margin=0.25',
    'right_margin=0.25',
    'gid=' + sh.getSheetId(),
    'range=A1:H47',
  ];

  const url = 'https://docs.google.com/spreadsheets/d/' + ss.getId() + '/export?' + params.join('&');
  const response = UrlFetchApp.fetch(url, {
    headers: {Authorization: 'Bearer ' + ScriptApp.getOAuthToken()},
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) {
    throw new Error('Export PDF impossible (HTTP ' + response.getResponseCode() + ').');
  }

  const filename = 'Facture_DallyTrading_' + dossier.replace(/[^A-Za-z0-9_-]/g, '_') + '.pdf';
  const blob = response.getBlob().setName(filename);
  const file = DriveApp.createFile(blob);

  const safeName = filename.replace(/[<>&"']/g, '_');
  const safeUrl = String(file.getUrl()).replace(/"/g, '&quot;');
  const html = HtmlService.createHtmlOutput(
    '<div style="font-family:Arial,sans-serif;padding:18px">' +
      '<h3 style="color:#0B3B6E;margin:0 0 10px">Facture PDF créée</h3>' +
      '<p>Le fichier <b>' + safeName + '</b> a été créé dans votre Google Drive.</p>' +
      '<p><a href="' + safeUrl + '" target="_blank" ' +
      'style="display:inline-block;background:#0A8F3C;color:white;padding:10px 16px;text-decoration:none;border-radius:6px">Ouvrir la facture PDF</a></p>' +
    '</div>'
  ).setWidth(430).setHeight(190);

  SpreadsheetApp.getUi().showModalDialog(html, 'DallyTrading - Export PDF');
}
