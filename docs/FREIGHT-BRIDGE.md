# Pont fret — exploitation

`dally_freight_bridge` confine le module tiers `tk_freight` et projette ses
données vers le portail client. Ce document couvre ce qu'il faut savoir pour
l'exploiter sans rouvrir une faille.

Les mesures qui justifient chaque décision sont dans
[`evaluations/TK-FREIGHT-EVALUATION.md`](evaluations/TK-FREIGHT-EVALUATION.md).

---

## 1. La règle de mise à jour

> **Ne jamais exécuter `odoo -u tk_freight` seul en production.**

`tk_freight` accorde au groupe portail des droits en lecture **et écriture** sur
ses modèles, alors qu'il ne contient qu'une seule règle d'enregistrement. Le pont
retire ces droits en écrasant les enregistrements du fournisseur par leur
`xmlid`.

Mettre à jour le fournisseur seul recharge ses propres fichiers de sécurité et
**restaure les valeurs d'origine**. Le portail redevient alors capable de lire et
de modifier les colis, documents et factures de tous les clients — sans qu'aucun
message ne le signale.

Toute mise à jour du fournisseur se fait donc dans la même opération :

```bash
odoo -u tk_freight,dally_freight_bridge
```

Et la version du fournisseur est validée en stack jetable **avant** d'atteindre
la production.

## 2. Ce qui se passe si la règle est oubliée

Le garde-fou (`models/lockdown_guard.py`) relit l'état réel en base — pas les
fichiers du dépôt — et réagit à deux niveaux, délibérément différents :

| Moment | Comportement |
|---|---|
| Installation ou mise à jour du pont | **Échec dur.** L'opération s'arrête. |
| Chargement ordinaire du registre | Journal `CRITICAL`, sans lever. |

Le second n'échoue pas volontairement : faire tomber un démarrage
transformerait une régression de sécurité en panne totale du back-office, qui
est resté sain. Le message est en revanche impossible à manquer :

```
CONFINEMENT tk_freight DEFAIT — 4 modele(s) tk accessibles au portail : …
Correctif : odoo -u tk_freight,dally_freight_bridge
```

## 3. Le garde-fou raisonne par invariant, pas par liste

Vérifier une liste de droits connus ne protège que du passé. Le garde-fou
découvre donc dynamiquement :

* **les modèles** définis uniquement par `tk_freight` (33 à ce jour) ;
* **les ACL** déclarées par `tk_freight`, même si elles portent sur un modèle du
  noyau ;
* **les routes** portées par les classes de contrôleur du fournisseur.

Il exige ensuite : aucun droit portail, aucune route non neutralisée.

Ce choix n'est pas théorique — il a trouvé **quatre ACL portail que l'inventaire
statique avait manquées** (`custom.department`, `dashboard.details`,
`policy.risk`, `quot.order.line`), toutes en lecture et écriture, aucune ne
portant un préfixe `freight` ou `shipment`.

Un premier critère, plus large, désignait aussi `res.partner`, `sale.order`,
`account.move` et `stock.picking`. Ce sont des modèles du **noyau** que
`tk_freight` se contente d'étendre : les fermer aurait cassé le portail Odoo
standard — un client n'aurait plus vu ses propres factures. Le périmètre est
donc l'**origine** de l'ACL, jamais le nom du modèle.

## 4. Sources de vérité

| Donnée | Source | Projection |
|---|---|---|
| Devis | `dally.quote.request` | — |
| Booking | `shipment.freight.booking` | — |
| Expédition **opérationnelle** | `freight.shipment` | `dally.shipment` |
| Colis | `shipment.package.line` | `dally.shipment.package` |
| Événements | `shipment.tracking` | `dally.shipment.event` |
| Suivi public | jeton DallyTrading | — |

La synchronisation est **à sens unique, tk → Dally**. Rien dans le portail ne
réécrit le fournisseur : une modification côté client ne doit jamais remonter
dans l'outil d'exploitation par un effet de bord.

Il n'y a **qu'un seul devis** : `dally.quote.request`. Le workflow du
fournisseur n'exige aucune `shipment.quotation` — vérifié en l'exécutant avec
`quot_id` vide.

## 5. Provisionnement

L'acceptation d'un devis (`state` → `won`) déclenche le provisionnement dans la
**même transaction**. Un échec du fournisseur annule donc aussi l'acceptation :
le client revoit son devis en attente et peut réessayer. L'alternative — commiter
l'acceptation et différer le fret — laisserait un devis accepté sans expédition,
sans que personne ne le sache.

Le déclencheur est la transition d'état, pas le contrôleur HTTP : le fait métier
compte, pas le canal qui l'a produit.

### Idempotence

Le même devis traité *n* fois produit exactement un booking, une expédition et
une projection. Trois barrières, plus une correction issue de la mesure :

1. verrou `FOR UPDATE` sur la ligne du devis ;
2. relecture du lien après le verrou ;
3. index unique sur `shipment.freight.booking.dally_quote_request_id` ;
4. **conversion de la course en `SerializationFailure`.**

La quatrième existe parce que la deuxième ne suffit pas. Odoo force
`REPEATABLE READ` au niveau de la connexion : la transaction perdante conserve
son instantané d'origine et **ne voit pas** le booking que la gagnante vient de
committer. Elle créait, l'index unique la rejetait, et `UniqueViolation`
n'appartient pas aux exceptions qu'Odoo rejoue — l'appelant recevait une 500 sur
une opération légitime. La course est donc convertie en `SerializationFailure`,
rejouée jusqu'à cinq fois ; au tour suivant l'instantané est frais et le chemin
idempotent s'applique.

### Suppression d'un devis provisionné

Le lien est en `ondelete="restrict"` : supprimer un devis qui a produit un
booking est **refusé**. Supprimer l'origine commerciale d'une expédition en cours
est presque toujours une erreur, et une clé étrangère est le meilleur endroit
pour l'arrêter. Le refus est bruyant, ce qui est le comportement recherché.

## 6. Mapping

Les étapes du fournisseur sont identifiées par **`xmlid`**
(`tk_freight.stage_data_1` à `5`), jamais par leur libellé : `name` est un
champ d'interface, traduisible et éditable par n'importe quel administrateur.

Une étape inconnue — ajoutée par une mise à jour, ou créée par l'exploitation —
**laisse l'état Dally inchangé**. Annoncer « Livré » sur une expédition qui ne
l'est pas est la pire sortie possible : le client cesse de suivre son dossier, et
personne ne s'en aperçoit.

| tk | Dally |
|---|---|
| `ocean` | `sea` |
| `air` | `air` |
| `land` | `road` |
| étape inconnue | *état conservé* |

## 7. Publication des événements

**Fermée par défaut.** La synchronisation crée les événements avec
`visible_to_customer = False`. Publier est une décision explicite de
l'exploitation, jamais un effet de bord : un événement interne publié par
accident est irrattrapable, le client l'a lu.

## 8. Courriels du fournisseur

`convert_to_operation()` envoie un courriel au client en `force_send=True`. Il
est supprimé par une extension de `mail.template`, active uniquement sous
drapeau de contexte et uniquement pour le gabarit du fournisseur. La
communication client appartient à DallyTrading — et sans cela, une reprise de
données enverrait de vrais courriels à de vrais clients.

## 9. Ce que le portail ne connaît pas

Le navigateur ne connaît **jamais** `tk_freight`. Il manipule une référence
DallyTrading, et rien d'autre.

* `dally.shipment.tk_shipment_id` porte `groups="dally_core.group_dally_readonly"` :
  le champ n'est pas chargé par l'ORM pour un utilisateur portail, il n'est donc
  pas masqué — il n'existe pas dans son contrat.
* Aucun identifiant tk n'est accepté en entrée. Le `sudo()` de lecture technique
  n'intervient qu'**après** résolution d'un enregistrement Dally autorisé par
  record rule.
* Les routes du fournisseur sont toutes neutralisées, y compris le suivi public
  `/track/shipment`, qui était énumérable sur une référence séquentielle.
