# DallyTrading Freight — Google Sheets connector

Bound Apps Script connector for `FActuration COntainer 2`.

## Purpose

Synchronise the operational Google Sheet with the validated Odoo Freight billing API without making the spreadsheet the accounting source of truth.

The connector covers all transactional source tabs:

1. `Saisie maritime` / `Saisie aérien` → customer, shipment and freight articles;
2. invoice creation → native Odoo sale order + **draft invoice only**;
3. customer payments → Freight collection then native `account.payment` when accounting prerequisites exist;
4. `Dépenses` → internal expense with actor allocations;
5. `Transferts caisse` → internal cash transfer.

Dashboard, synthesis, invoice-print and customs-print tabs remain derived/reporting views and are not pushed as independent records.

## Freight API flow

For one dossier the connector performs, in order:

1. `POST /api/v1/freight/sync`;
2. optional `POST /api/v1/freight/invoice`;
3. one `POST /api/v1/freight/payment` per row carrying a `BF` payment key.

Internal cash uses:

- `POST /api/v1/freight/expense`
- `POST /api/v1/freight/cash-transfer`

## Spreadsheet output columns

The existing unused sync columns `AF:AM` are used as CRM outputs on the Freight entry tabs:

| Column | Meaning |
| --- | --- |
| AF | Sync status (`À synchroniser`, `Synchronisé`, `Erreur`) |
| AG | `res.partner` ID |
| AH | `dally.shipment` ID |
| AI | Last CRM sync timestamp |
| AJ | `sale.order` ID |
| AK | `account.move` invoice ID |
| AL | Odoo invoice number / draft marker |
| AM | Sync / pricing / payment message |

Cash output columns are:

- `Dépenses` `Q:T`: sync status, Odoo Expense ID, last sync, message
- `Transferts caisse` `M:P`: sync status, Odoo Transfer ID, last sync, message

The workbook business idempotency keys are preserved:

- `BD`: freight article key (`<dossier>|A|<n>`)
- `BF`: payment key (`<dossier>|P|<n>`)
- `Dépenses!A`: expense key (`DEP-...`)
- `Transferts caisse!A`: transfer key (`TRF-...`)

A row with a payment key but no article key (for example a complementary payment row) is **not** sent as a freight article.

## Security

Never write API keys in cells, source-controlled files or Apps Script source.

Create these **Script Properties** in the bound Apps Script project:

- `DALLY_FREIGHT_SYNC_API_KEY`
- `DALLY_FREIGHT_BILLING_API_KEY`

The first key must use the dedicated Freight Sync integration identity and carry:

- `freight:write`

The second key must use the dedicated Freight Billing integration identity and carry:

- `freight:invoice`
- `freight:payment`
- `freight:cash`

Requests use `X-API-Key` and a fresh UUID. Odoo additionally enforces object-level idempotency using dossier, article, payment, expense and transfer business keys.

## Installation

1. Upload `FActuration COntainer 2 - CRM SYNC.xlsx` to Google Drive and open it as Google Sheets.
2. Open **Extensions → Apps Script**.
3. Copy `Code.gs` and `Cash.gs` into the bound project.
4. Enable the manifest file in Apps Script project settings and use `appsscript.json` from this directory.
5. Add the two Script Properties above.
6. Execute `dallySetup()` once and approve the requested scopes.
7. Execute `dallyCashSetup()` once to install the independent expense/transfer triggers.
8. Reload the spreadsheet. Menus **Dally CRM** and **Dally Caisse** appear.
9. Run **Dally CRM → Diagnostic configuration** before any write operation.

## Migration mode

The `Synchronisation CRM` sheet starts with:

- automatic sync: `OUI`
- automatic draft invoice: `NON`
- payment sync: `OUI`
- initial migration mode: `OUI`

While migration mode is `OUI`, all API payloads use source `legacy_xlsx`.
After the historical data has been compared against Odoo, switch it to `NON`; new edits then use source `google_sheets`.

Keep automatic draft invoice set to `NON` during the first historical import. Enable it only after dossier totals have been reconciled.

## Triggers

`dallySetup()` installs:

- installable `onEdit` that only marks an edited dossier `À synchroniser`;
- one-minute time trigger that groups dirty rows by dossier and sends dossier requests.

`dallyCashSetup()` installs independent triggers for `Dépenses` and `Transferts caisse`.

No edit trigger performs HTTP calls. This prevents one API request per edited cell and avoids sending a half-completed row while the operator is typing.

The maximum number of operations processed per minute uses the `Dossiers max par cycle` setting (default: 10), staying below the API backstop rate limit.

## Freight mapping highlights

- `A`: goods/deposit date → `goods_received_on`
- `B`: dossier → `external_reference`
- `C/D/AU/AV`: customer name, phone, address, email → `res.partner`
- `E`: Particulier/Professionnel → individual/business
- `G/H/I/J/K/N/O`: freight article/package facts
- `R`: real / volumetric / quote billing method
- `T`: historical/manual unit price, if present
- `V`: dossier fee — **first value only per dossier**
- `W`: other fees — summed across article rows of the dossier
- `AD`: workbook parcel state → Dally shipment workflow state
- `AT`: tariff family → `food`, `seafood`, `honey`, `clothing`, `non_food`
- `AQ`: declared customs value in XOF
- `AW/AX`: payment amount EUR/XOF
- `BB/BC`: payment method and collector

## Internal expense mapping

`Dépenses` preserves the workbook structure:

- `A`: external expense key
- `B:E`: date/category/description/beneficiary
- `F:H`: allocations paid by Gilles, Alain and Dalanda
- `J`: source currency (`EUR` or `FCFA` → API `XOF`)
- `K:L`: historical workbook EUR/XOF snapshots
- `M:P`: payment method, reference, status, comment

The expense is operational cash tracking; it is **not** converted into an accounting vendor bill by this connector.

## Cash transfer mapping

`Transferts caisse` maps the sender, recipient, amount/currency, EUR/XOF snapshots, reason, handover method, status and comment into `dally.cash.transfer`.

A transfer never affects customer invoices or customer payments.

## Route configuration

Route metadata is read from the `Synchronisation CRM` routing table, not hard-coded into the API payload builder. The prepared workbook contains:

- `Saisie maritime`: sea / export / SN Dakar → FR Paris
- `Saisie aérien`: air / export / SN Dakar → FR Paris

Change the routing table before using the same connector for another corridor.

## Accounting boundary

The connector never posts an invoice. `/api/v1/freight/invoice` creates or retrieves the native **draft** invoice. Posting remains a Finance action in Odoo.

Payments entered before invoice posting remain visible as pending Freight collections. When a posted invoice and a matching configured payment channel exist, Odoo promotes them to native `account.payment` records.
