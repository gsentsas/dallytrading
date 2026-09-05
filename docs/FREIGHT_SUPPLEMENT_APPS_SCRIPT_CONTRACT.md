# Contrat Apps Script — compléments de fret

Cette note décrit le contrat entre le connecteur et l'API des compléments.
Le miroir Git **a été mis à jour** pour l'honorer ; le classeur, lui, n'est pas
touché.

```
APPS_SCRIPT_SOURCE_UPDATED=YES
APPS_SCRIPT_LIVE_DEPLOYED=NO
SHEET_MUTATED=NO
```

## Où vit le code concerné

Le script bound est versionné :

```
integrations/google-sheets/freight-sync/Code.gs
```

Ce fichier est un miroir du projet Apps Script lié au classeur. Le pousser vers
le classeur reste une opération manuelle et distincte, volontairement exclue de
cette phase : le serveur doit accepter le nouveau contrat avant que le
connecteur ne commence à l'utiliser.

## A. `prepareInvoice_()` — n'écrire que sur les lignes couvertes

### Le défaut corrigé

L'écriture portait sur **toutes** les lignes du dossier. Tant qu'une seule facture
existait, c'était correct. Avec un complément, cela écraserait les références de
la facture principale sur les colis déjà facturés — le classeur affirmerait que
d'anciennes marchandises appartiennent à une pièce qui ne les contient pas.

### Le contrat, désormais implémenté

L'API rend deux champs supplémentaires :

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

Si une réponse `supplement` arrive **sans** `covered_line_keys`, le connecteur
lève une erreur et n'écrit rien. Écrire partout serait pire que ne rien écrire.

## B. `syncPayments_()` — viser la bonne pièce

### Trois états, pas deux

C'est l'invariant central de ce contrat, et le plus facile à casser.

| État du payload | Sens | Effet serveur |
|---|---|---|
| `invoice_id` **absent** | l'appelant ne dit rien | la cible existante n'est pas touchée |
| `invoice_id: <id>` | l'appelant vise une pièce | `target_invoice_id = <id>` après validation |
| `invoice_id: ""` | l'appelant retire la cible | `target_invoice_id = False`, retour à la principale |

Confondre « absent » et « vide » est un défaut silencieux : un rejeu conserverait
un complément que le classeur vient justement de retirer, et l'encaissement
partirait sur la mauvaise pièce dès qu'il deviendrait comptabilisable.

Le connecteur transmet donc toujours la colonne **Odoo Invoice ID**, y compris
vide. Son nettoyage générique de payload supprime les chaînes vides — il épargne
`invoice_id`, et lui seul :

```js
Object.keys(payload).forEach(k => {
  if (typeof payload[k] === 'undefined') delete payload[k];
  else if (payload[k] === '' && k !== 'invoice_id') delete payload[k];
});
```

### Ce que le serveur vérifie

Une valeur présente est validée avant d'être acceptée : nature `out_invoice`,
état non `cancel`, même société, même client, et appartenance au dossier (lue par
les lignes, puisqu'un complément ne porte pas `dally_freight_shipment_id`). En
cas d'écart, il répond 404, 409 ou 422 plutôt que d'imputer au hasard.

Une facture `draft` **reste** une cible valide : l'encaissement peut précéder la
comptabilisation du complément, la collection attend, et `action_post` la
réveille. Une facture `cancel` est refusée — elle ne sera jamais comptabilisée,
et la collection resterait en attente pour toujours.

Une fois l'encaissement rattaché à un `account.payment`, la cible est figée :
ni redirection ni effacement.

La réponse expose la facture **effectivement** ciblée, ce qui permet au classeur
de vérifier qu'il a visé juste plutôt que de le supposer.

## Ordre de déploiement

Le serveur d'abord, le connecteur ensuite. L'inverse enverrait un `invoice_id` à
une API qui le rejette en `422 unknown_fields`, et toute synchronisation de
paiement échouerait.

Le miroir Git porte déjà les deux changements. Les pousser vers le projet Apps
Script lié au classeur est une opération manuelle, distincte, et volontairement
hors de cette phase : elle ne doit avoir lieu qu'après l'upgrade du module en
production.

## Vérification

`scripts/test_freight_sheet_supplement_contract.js` charge le vrai `Code.gs`
sans Google et prouve les quatre points : un complément n'écrit que sur
`covered_line_keys`, une principale garde son comportement, un complément sans
`covered_line_keys` refuse d'écrire, et `invoice_id: ""` survit au nettoyage du
payload alors que les autres champs vides en sont retirés.
