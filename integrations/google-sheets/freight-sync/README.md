# DallyTrading Freight — Google Sheets connector

Bound Apps Script connector for `FActuration COntainer 2`.

## Purpose

Synchronise the operational Google Sheet with the validated Odoo Freight billing API without making the spreadsheet the accounting source of truth.

The connector covers all transactional source tabs:

1. `Saisie maritime` / `Saisie aérien` → customer, shipment and freight articles;
2. invoice creation → native Odoo sale order + **draft invoice only**;
3. customer payments → Freight collection then native `account.payment` when accounting prerequisites exist;
4. `Dépenses` → internal expense with actor allocations;
5. `Transferts caisse` → internal cash transfer;
6. `Facture impression` → professional PDF export through the integrated `Pdf.gs` script.

Dashboard, synthesis, invoice-print and customs-print tabs remain derived/reporting views and are not pushed as independent records.

## Freight API flow

For one dossier the connector performs, in order:

1. `POST /api/v1/freight/sync`;
2. optional `POST /api/v1/freight/invoice`;
3. one `POST /api/v1/freight/payment` per active payment row;
4. `POST /api/v1/freight/payment/reconcile` with the complete current payment-key set.

The reconcile call is essential: a payment removed from the Sheet is cancelled in Odoo **only while it has not yet produced a native `account.payment`**. A payment already registered in accounting is never silently rewritten; the API returns it as blocked and requires an accounting correction.

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

If an article row contains cargo facts but no `BD` key, the connector creates the deterministic dossier article key before sending it. This allows a genuine `Sur devis` cargo row to exist in CRM without being invoiced.

A payment-only administrative row with no cargo measurements is **not** sent as a freight article.

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

1. Open the native Google Sheet `FActuration COntainer 2`.
2. Open **Extensions → Apps Script**.
3. Keep a single bound project and copy **all three** files: `Code.gs`, `Cash.gs`, `Pdf.gs`.
4. Enable the manifest file in Apps Script project settings and use `appsscript.json` from this directory.
5. Add the two Script Properties above.
6. Execute `dallySetup()` once and approve the requested scopes.
7. Execute `dallyCashSetup()` once to install the independent expense/transfer edit + timer triggers.
8. Reload the spreadsheet. Menus **Dally CRM**, **Dally Caisse** and **Factures DallyTrading** appear.
9. Run **Dally CRM → Diagnostic configuration** before any write operation.

**Do not create a second `onOpen()` function.** `Code.gs` owns the only `onOpen()` and calls the cash/PDF menu builders. In particular, never delete the existing Apps Script project to install the PDF button.

## Safe defaults

If the configuration sheet ever has to be recreated, the connector now starts with conservative defaults:

- automatic sync: `NON`
- automatic draft invoice: `NON`
- payment sync: `NON`
- initial migration mode: `NON`

This prevents a newly recreated configuration from unexpectedly writing accounting-related data.

## Migration mode

While migration mode is `OUI`, payloads use source `legacy_xlsx`.
After historical reconciliation, switch it to `NON`; new edits then use source `google_sheets`.

When current source is `google_sheets`, payment reconciliation is allowed to retire stale pending collections created by both `google_sheets` and the earlier `legacy_xlsx` migration. Back-office collections are never touched.

## Triggers

`dallySetup()` installs:

- installable `onEdit` that only marks an edited dossier `À synchroniser`;
- one-minute time trigger that groups dirty rows by dossier and sends dossier requests when automatic sync is enabled.

`dallyCashSetup()` installs:

- one installable cash `onEdit` trigger;
- one one-minute cash timer.

There is no independent cash `onOpen` trigger anymore; the unique `onOpen()` in `Code.gs` creates all menus.

No edit trigger performs HTTP calls. This prevents one API request per edited cell and avoids sending a half-completed row while the operator is typing.

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

## `Sur devis` protection

A cargo row is recognised even when its invoice amount is still zero if it contains a description plus real cargo measurements (weight, dimensions or volume). A deterministic `BD` article key is generated and the cargo is synchronised to CRM.

A `Sur devis` row is never invoice-ready. Even the manual **Créer la facture brouillon du dossier** command refuses to create its invoice until the billing method, billable weight and applied price are valid. This prevents a case such as A012 from creating a zero/incorrect invoice.

## Payment correction rules

The current Sheet payment rows are treated as the operational source set for Sheet-managed collections.

- New payment → upsert by `BF` key.
- Corrected pending payment → same key, values updated.
- Removed pending payment → reconcile marks the Odoo collection `cancelled`.
- Re-added cancelled payment → same key is reactivated and becomes `pending` again.
- Already-accounted payment → never mutated/cancelled from the Sheet; Finance must create the accounting correction.

Cancelled collections are excluded from the customer invoice PDF totals and are not promoted to native accounting when the invoice is later posted.

## Internal expense mapping

`Dépenses` preserves the workbook structure:

- `A`: external expense key
- `B:E`: date/category/description/beneficiary
- `F:H`: allocations paid by Gilles, Alain and Dalanda
- `J`: source currency (`EUR` or `FCFA` → API `XOF`)
- `K:L`: historical workbook EUR/XOF snapshots
- `M:P`: payment method, reference, status, comment

A valid expense requires a real date, category, description and at least one positive actor allocation. The Apps Script now rejects missing dates locally before making any HTTP call.

The expense is operational cash tracking; it is **not** converted into an accounting vendor bill by this connector.

## Cash transfer mapping

`Transferts caisse` maps the sender, recipient, amount/currency, EUR/XOF snapshots, reason, handover method, status and comment into `dally.cash.transfer`.

A valid transfer requires a date, positive amount and two different actors. A transfer never affects customer invoices or customer payments.

## PDF export

`Pdf.gs` exports only `Facture impression!A1:H47` in A4 portrait mode and creates the resulting PDF in the current user's Google Drive.

The manifest contains the Drive authorization required by `DriveApp.createFile`. There is no second `onOpen()` and therefore no menu collision with the CRM connector.

## Route configuration

Route metadata is read from the `Synchronisation CRM` routing table, not hard-coded into the API payload builder. The prepared workbook contains:

- `Saisie maritime`: sea / export / SN Dakar → FR Paris
- `Saisie aérien`: air / export / SN Dakar → FR Paris

Change the routing table before using the same connector for another corridor.

## Accounting boundary

The connector never posts an invoice. `/api/v1/freight/invoice` creates or retrieves the native **draft** invoice. Posting remains a Finance action in Odoo.

Payments entered before invoice posting remain visible as pending Freight collections. When a posted invoice and a matching configured payment channel exist, Odoo promotes them to native `account.payment` records.

## Consolidation-scoped intake references

`A001`, `A002`, … are local collection references within the intake consolidation namespace. They are not global identifiers. For a planned consolidation such as `AIR-DSS-CDG-2026-002`, the server allocates `A001` and exposes the immutable global `external_reference` `AIR-DSS-CDG-2026-002-A001`. A legacy payload that already supplies `external_reference=A001` remains supported unchanged.

The planned consolidation is intentionally visible before the dossier: B = `Consolidation prévue`, C = `N dossier`. The technical identity columns are hidden at BH:BK (`sync_source_key`, `global_external_reference`, `intake_consolidation_ref`, `collection_local_ref`). The source key is stable for retries and is never an API secret. Logical dossier grouping priority is: (1) `sync_source_key`, (2) `global_external_reference`, then (3) `shipment_id + dossier`. Existing article/payment keys are preserved; new keys use the global reference (or stable source key) before the `|A|n` / `|P|n` suffix.

Use **Actualiser les départs ouverts** to refresh the read-only collecting-consolidation table in `Synchronisation CRM`. It returns only company-scoped collecting departures and the route/mode fields needed for selection; no financial or customer data is returned. Editing a cell never performs HTTP. The manual synchronisation action performs allocation and association. A `request_received` or `awaiting_goods` shipment stores its planned departure without physical lines; `goods_received` and `preparing` shipments attach available packages through the same server method as the Odoo wizard. If a departure closes before receipt, the response reports that re-planning is required and does not silently switch to another consolidation. Re-planning is allowed only before physical loading and keeps the intake/local/global identity unchanged.

For a multi-line dossier, all rows share the same stable source key and logical consolidation+dossier group. The first successful response writes the local reference, global reference and intake namespace back to the hidden/technical columns; replaying the same source key returns the same shipment and does not consume another `Axxx`.

## Projection CRM → classeur (Dally Ops)

Deux sens coexistent désormais, et ils ne portent pas la même autorité.

```text
Saisie legacy / administrative :  Sheet  → Odoo
Saisies terrain Dally Ops      :  Odoo   → Sheet
```

Pour tout ce qui est saisi depuis Dally Ops — réception, encaissement Wave,
dépense, transfert — **Odoo est la source de vérité** et le classeur reçoit une
projection. Le classeur reste une interface de contrôle, de reporting et de
secours ; il ne redevient jamais l'autorité sur ces objets.

### Le chemin

```text
transaction métier Odoo
  ├─ crée l'objet
  └─ inscrit l'intention dans `dally.ops.sheet.outbox`
COMMIT

Apps Script (minuteur 5 min ou menu)
  → GET  /api/v1/freight/sheet-outbox
  → applique la projection (UPSERT)
  → POST /api/v1/freight/sheet-outbox/ack
```

Aucun appel réseau n'a lieu pendant la transaction métier : **une panne Google
ne peut pas annuler une réception**. L'opération terrain est « synchronisée avec
le CRM » dès qu'Odoo a confirmé ; la projection vers le classeur est un état
administratif distinct, et n'est jamais une condition de succès.

### Pourquoi c'est le classeur qui va chercher

Toute l'autorisation Google vit dans ce projet Apps Script — ses portées et ses
Script Properties. Odoo ne possède aucun identifiant Google, et en fabriquer un
créerait un secret de production là où il n'y en avait pas. Surtout, savoir
écrire dans ce classeur (63 colonnes canoniques, colonnes techniques
d'identité, intention de replanification, neutralisation des formules,
migrations héritées) est une connaissance qui vit ici. La reproduire côté Odoo
créerait une seconde convention d'identité.

Le « cron » de projection est donc **côté Apps Script**. Il n'y en a pas
d'autre ailleurs.

### Clé d'API

Ajouter une troisième Script Property :

- `DALLY_FREIGHT_SHEET_API_KEY`, portant le seul scope `freight:sheet`.

Ce scope ne permet ni de créer un dossier, ni d'émettre une facture, ni de
toucher à la caisse : il lit la file et accuse réception, rien de plus.

### Clés d'UPSERT

| Objet | Identité utilisée | Colonne |
| --- | --- | --- |
| Dossier | `sync_source_key`, puis `global_external_reference`, puis `shipment_id` | BH / BI / AH |
| Article | `external_line_key` | BD |
| Encaissement | `<référence globale>|P|<n>` | BF |
| Dépense | `external_expense_key` | `Dépenses!A` |
| Transfert | `external_transfer_key` | `Transferts caisse!A` |

Aucune projection n'utilise `A001` seul : il est local à son départ, et deux
consolidations en ont chacune un. Aucun numéro de ligne n'est utilisé comme
identité — il change dès qu'on trie.

Les encaissements n'ont pas d'onglet propre dans ce classeur : un paiement vit
dans les colonnes de paiement de la ligne de son dossier (AW/AX, BB/BC, BF).
Deux paiements partiels restent donc deux lignes distinctes.

### Reprise et accusé

L'accusé part **après** l'écriture. Si le classeur est écrit mais que l'accusé
se perd, la ligne repasse en attente après quinze minutes et le passage suivant
refait un UPSERT sur la **même** ligne : la clé métier n'a pas bougé.

Les reprises sont espacées (0, 2, 10, 30, 120 puis 360 minutes). Une projection
invalide passe en `failed` : elle reste visible pour diagnostic et cesse
d'occuper le transport, sans jamais bloquer les autres.

### Conflits avec une correction humaine

La projection écrit les faits, pas les décisions. Une intention de
replanification saisie dans le classeur survit à la projection : le message
`Replanification demandée depuis la feuille.` est préservé, comme dans le sens
Sheet → Odoo.

### Diagnostic

- **Menu `Dally CRM → Projeter les opérations du CRM`** : force un passage.
- Côté Odoo, `dally.ops.sheet.outbox` montre l'état, le nombre de tentatives,
  la prochaine reprise et le dernier motif d'échec.
- Une ligne `failed` se relance en la repassant à `pending`.
