# Contrat Apps Script — compléments de fret

Cette note décrit les deux changements que le connecteur devra porter une fois
le support serveur des compléments déployé. **Elle ne les implémente pas** :
cette phase est serveur uniquement, et le Google Sheet n'est pas touché.

## Où vit le code concerné

Contrairement à ce qui a pu être supposé, le script bound **est** versionné :

```
integrations/google-sheets/freight-sync/Code.gs
```

`prepareInvoice_()` s'y trouve à la ligne 430, `syncPayments_()` à la ligne 453.
Ce fichier est un miroir du projet Apps Script lié au classeur ; le pousser vers
le classeur reste une opération manuelle et distincte.

## A. `prepareInvoice_()` — n'écrire que sur les lignes couvertes

### Le défaut actuel

```js
rows.forEach(row => {
  setCell_(sheet, row.row, DALLY.columns.saleOrderId, data.sale_order_id || '');
  setCell_(sheet, row.row, DALLY.columns.invoiceId, data.invoice_id || '');
  setCell_(sheet, row.row, DALLY.columns.invoiceNumber, data.invoice_number || 'Brouillon');
});
```

L'écriture porte sur **toutes** les lignes du dossier. Tant qu'une seule facture
existait, c'était correct. Avec un complément, cela écraserait les références de
la facture principale sur les colis déjà facturés — le classeur affirmerait que
d'anciennes marchandises appartiennent à une pièce qui ne les contient pas.

### Le contrat attendu

L'API rend désormais deux champs supplémentaires :

| champ | valeur |
|---|---|
| `invoice_kind` | `"primary"` ou `"supplement"` |
| `covered_line_keys` | les `external_line_key` que **cette** facture couvre |

- `invoice_kind == "primary"` → comportement actuel, inchangé.
- `invoice_kind == "supplement"` → n'écrire `sale_order_id`, `invoice_id` et
  `invoice_number` que sur les lignes dont la **Clé article facture** figure
  dans `covered_line_keys`.

Le `sale_order_id` rendu est celui de la commande qui a réellement produit la
facture — la commande complémentaire dans ce cas, jamais la principale.

Se fier au seul `invoice_kind` pour deviner les lignes serait fragile : c'est
`covered_line_keys` qui fait foi, parce qu'elle est calculée depuis la pièce
elle-même, en remontant ligne de facture → ligne de commande → colis.

## B. `syncPayments_()` — viser la bonne pièce

### Le défaut actuel

Le payload envoyé à `/api/v1/freight/payment` ne porte pas d'`invoice_id` :

```js
const payload = {
  external_payment_key: key,
  ...
  payment_date: ...,
  payment_method: method,
};
```

Le serveur solde alors la facture principale du dossier. Un encaissement destiné
au complément irait donc réduire le solde de la mauvaise pièce.

### Le contrat attendu

Quand la ligne de paiement porte un **Odoo Invoice ID**, l'ajouter au payload :

```js
...(invoiceIdDeLaLigne ? {invoice_id: invoiceIdDeLaLigne} : {}),
```

Absent, le comportement reste strictement celui d'aujourd'hui — la cible est la
facture principale. Présent, le serveur vérifie quatre points avant d'accepter :
nature `out_invoice`, même société, même client, et appartenance au dossier
(lue par les lignes, puisqu'un complément ne porte pas `dally_freight_shipment_id`).
En cas d'écart, il répond 409 ou 422 plutôt que d'imputer au hasard.

La réponse expose la facture **effectivement** ciblée, ce qui permet au classeur
de vérifier qu'il a visé juste plutôt que de le supposer.

## Ordre de déploiement

Le serveur d'abord, le connecteur ensuite. L'inverse enverrait un `invoice_id` à
une API qui l'ignore : le paiement irait silencieusement sur la facture
principale, et l'erreur ne se verrait qu'au rapprochement.
