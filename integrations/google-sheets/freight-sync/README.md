# DallyTrading Freight — Google Sheets connector

Bound Apps Script connector for `FActuration COntainer 2`.

## Purpose

Synchronise the operational Google Sheet with the validated Odoo Freight billing API without making the spreadsheet the accounting source of truth.

The connector groups all rows of one dossier and performs, in order:

1. `POST /api/v1/freight/sync` — customer, shipment and freight article upsert;
2. optional `POST /api/v1/freight/invoice` — native Odoo sale order + **draft invoice only**;
3. `POST /api/v1/freight/payment` — customer collections, idempotent with the workbook `BF` key.

## Spreadsheet output columns

The existing unused sync columns `AF:AM` are used as CRM outputs:

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

The workbook business idempotency keys are preserved:

- `BD`: freight article key (`<dossier>|A|<n>`)
- `BF`: payment key (`<dossier>|P|<n>`)

A row with a payment key but no article key (for example a complementary payment row) is **not** sent as a freight article.

## Security

Never write API keys in cells, source-controlled files or the Apps Script source.

Create these **Script Properties** in the bound Apps Script project:

- `DALLY_FREIGHT_SYNC_API_KEY`
- `DALLY_FREIGHT_BILLING_API_KEY`

The first key must use the dedicated Freight Sync integration identity and carry `freight:write`.
The second key must use the dedicated Freight Billing integration identity and carry `freight:invoice` + `freight:payment`.

Requests use the `X-API-Key` header and a fresh UUID. Odoo also enforces object-level idempotency using dossier, article and payment business keys.

## Installation

1. Upload `FActuration COntainer 2 - CRM SYNC.xlsx` to Google Drive and open it as Google Sheets.
2. Open **Extensions → Apps Script**.
3. Copy `Code.gs` into the bound project.
4. Enable the manifest file in Apps Script project settings and use `appsscript.json` from this directory.
5. Add the two Script Properties above.
6. Execute `dallySetup()` once and approve the requested scopes.
7. Reload the spreadsheet. A **Dally CRM** menu appears.
8. Run **Dally CRM → Diagnostic configuration** before any write operation.

## Migration mode

The `Synchronisation CRM` sheet starts with:

- automatic sync: `OUI`
- automatic draft invoice: `NON`
- payment sync: `OUI`
- initial migration mode: `OUI`

While migration mode is `OUI`, API payloads use source `legacy_xlsx`.
After the historical dossiers have been compared against Odoo, switch it to `NON`; new edits then use source `google_sheets`.

Keep automatic draft invoice set to `NON` during the first historical import. Enable it only after the totals have been reconciled.

## Triggers

`dallySetup()` installs two project triggers:

- installable `onEdit`: only marks an edited dossier `À synchroniser`;
- one-minute time trigger: groups dirty rows by dossier and sends a batch-like sequence of dossier requests.

The edit trigger never performs HTTP calls. This prevents one API request per edited cell and avoids partial-dossier writes while the operator is typing.

The maximum number of dossiers processed per minute is configured in `Synchronisation CRM` (default: 10), staying comfortably below the API backstop rate limit.

## Workbook mapping highlights

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

## Route configuration

Route metadata is read from the `Synchronisation CRM` routing table, not hard-coded into the API payload builder. The prepared workbook contains:

- `Saisie maritime`: sea / export / SN Dakar → FR Paris
- `Saisie aérien`: air / export / SN Dakar → FR Paris

Change the routing table before using the same connector for another corridor.

## Accounting boundary

The connector never posts an invoice. `/api/v1/freight/invoice` creates or retrieves the native **draft** invoice. Posting remains a Finance action in Odoo.

Payments entered before invoice posting remain visible as pending Freight collections. When a posted invoice and a matching configured payment channel exist, Odoo promotes them to native `account.payment` records.
