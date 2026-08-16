# tk_freight — évaluation de faisabilité

**Verdict : GO SOUS CONDITIONS.** Le point juridique est **clos** (§1). Restent des
conditions de sécurité, toutes satisfaisables depuis `dally_freight_bridge` sans
forker le fournisseur.

| | |
|---|---|
| Source | `github.com/rambolee200311/odoo19_freight` |
| Commit évalué | `13b890dd0f1bccbebf23f106254bf85c3cd07d4c` (2026-08-14) |
| Chemin | `mymodules/tk_freight` |
| Version déclarée | 2.2.0 |
| Auteur déclaré | **TechKhedut Inc.** |
| Licence déclarée | **OPL-1** · prix **175 USD** |
| Volume | 227 fichiers · 4 619 lignes de Python · **0 test** |

---

## 1. Licence — CLOS

> **Le propriétaire de DallyTrading a confirmé détenir une licence valide et
> légitime de tk_freight.** Le point est clos et ne conditionne plus le chantier.
>
> Conséquence pratique : l'évaluation dynamique doit se faire sur la **copie
> licenciée**, jamais sur le dépôt GitHub tiers. Celui-ci a servi à l'audit
> statique et ne doit pas devenir une source de production.

Ce qui suit est conservé comme trace de l'analyse initiale, et parce qu'il reste
utile : il documente pourquoi la copie GitHub ne peut pas servir de source, et à
quoi comparer la copie licenciée.

### Analyse initiale (historique)

`__manifest__.py` déclare `'license': 'OPL-1'` et `'price': 175.00`. C'est un
produit **commercial** de TechKhedut, vendu sur l'Odoo Apps Store. L'OPL-1
interdit la redistribution.

Or le dépôt consulté est une **copie complète de l'arbre source d'Odoo** — il
porte le `LICENSE` LGPLv3 et le `README.md` d'Odoo à sa racine — dans laquelle
`tk_freight` a été déposé sous `mymodules/`. Les 50 commits sont d'un seul
individu, pas de TechKhedut, et le module ne contient **aucun fichier de licence
TechKhedut**.

Cette copie est donc, selon toute vraisemblance, une **redistribution non
autorisée**. Nous ne détenons aucune licence.

Cette copie ne peut donc pas servir de source de production, indépendamment de
la licence que nous détenons par ailleurs : elle n'en est pas le canal
d'obtention légitime, et rien ne garantit qu'elle corresponde à la version
vendue.

**Statut** : le propriétaire détient la licence. L'évaluation dynamique se fera
sur sa copie, dont le chemin reste à fournir.

## 2. CONDITION — sécurité portail native

### ACL

`security/ir.model.access.csv` — 94 lignes, dont **30 accordent à
`base.group_portal` `perm_read=1` ET `perm_write=1`** :

`freight.shipment` · `shipment.quotation` · `shipment.freight.booking` ·
`shipment.package.line` · `shipment.tracking` · `freight.documents` ·
`booking.line` · `shipment.item` · `shipment.location` ·
`shipment.location.activity` · `tracking.template` · `tracking.template.line` ·
`shipment.invoice` · `freight.multiple.invoice` · et toute la configuration
(`freight.port`, `freight.vessel`, `freight.airline`, `freight.incoterms`,
`freight.route`, `freight.service`, `freight.package`, `freight.move.type`,
`certificate.type`, `policy.risk`, `custom.department`, `dashboard.details`,
`freight.frequent.route`, `freight.shipment.stages`).

### Record rules

Il en existe **une seule**, dans tout le module :

```xml
<record id="freight_security_rule_portal" model="ir.rule">
  <field name="model_id" ref="tk_freight.model_freight_shipment"/>
  <field name="domain_force">
    ['|', ('consignee_id','=',user.partner_id.id), ('shipper_id','=',user.partner_id.id)]
  </field>
  <field name="groups" eval="[(4, ref('base.group_portal'))]"/>
  <field name="perm_read" eval="True"/>
  <field name="perm_write" eval="True"/>
  <field name="perm_unlink" eval="True"/>
</record>
```

Trois conséquences, chacune suffisante à elle seule :

1. **29 des 30 modèles en écriture n'ont AUCUNE restriction de ligne.** Un
   utilisateur portail peut lire *et modifier* chaque devis, booking, ligne de
   colis, événement de suivi, document, port, navire, compagnie aérienne,
   incoterm, route et modèle de suivi de la base — **tous clients confondus**.
2. Même sur `freight.shipment`, la règle accorde `perm_write` **et
   `perm_unlink`** : un client peut modifier ou **supprimer** son expédition,
   son état compris.
3. Le filtre porte sur `user.partner_id`, pas sur `commercial_partner_id` :
   l'inverse de notre convention. Les autres contacts d'une même société ne
   voient rien, et c'est le seul cloisonnement existant.

C'est la symétrie exacte de nos choix : ACL en lecture seule, record rule par
modèle sur `commercial_partner_id`, `groups=` au niveau des champs, et une seule
écriture portail encapsulée dans une capacité privée.

## 3. CONDITION — suivi public sans jeton, via `sudo()`

```python
@http.route(['/track/shipment', '/track/shipment/<string:booking>',
             '/track/shipment/<string:shipment>'], auth="public", website=True)
def track_shipment(self, booking=None):
    tracking_no = request.params.get('q')
    freight = request.env['freight.shipment'].sudo().search([('name', '=', tracking_no)])
    ...
    return request.render('tk_freight.freight_success', {'freight': freight, ...})
```

`auth="public"` + `sudo()` + recherche sur la seule référence. Aucune capacité,
aucun jeton. Les record rules sont contournées et le recordset entier est passé
au template.

C'est un oracle d'énumération : les références Odoo sont séquentielles, donc
devinables. Notre architecture existante — `/tracking?ref=&t=`, clé d'API
serveur `tracking:read`, 404 anti-énumération, `no-store`, journaux expurgés —
a été construite précisément contre cela.

**Cette route ne doit jamais être exposée.** Si le module est adopté, le bridge
devra projeter `shipment.tracking` vers `dally_tracking` et l'accès public tk
rester fermé au niveau du reverse proxy.

## 4. HIGH — IDOR en lecture ET en écriture sur `/post/comment`

```python
@http.route(['/post/comment'], auth="user", website=True)
def post_comment(self, **kw):
    book_id = request.env['shipment.freight.booking'].sudo().browse(int(kw['book_id']))
    request.env['booking.line'].sudo().create({... 'booking_id': book_id.id})
    book_id.sudo().message_post(body=body)
    return request.render("tk_freight.portal_my_booking_detail",
                          {'booking': book_id.sudo(), 'track_ids': track_ids})
```

`sudo().browse(int(kw['book_id']))` sur un identifiant fourni par l'appelant,
sans aucun contrôle de propriété. Tout utilisateur authentifié — donc tout
client portail — peut écrire un commentaire sur **n'importe quel** booking, et la
réponse **affiche la page de détail de ce booking**. C'est un IDOR en écriture
et en lecture dans le même appel.

`shipment.freight.booking` n'ayant aucune record rule, rien ne le rattrape.

## 5. MEDIUM

- **`csrf=False` sur une route qui crée** : `/freight/shipment/booking/submit`
  (`auth="user"`) exécute `sudo().create()`. Les champs sont whitelistés un par
  un et `consignee_id` est forcé à l'utilisateur de session — donc pas de mass
  assignment — mais le CSRF est désactivé sur un endpoint créateur.
- **`cache=300` sur des routes `auth="user"`** (booking, quotation, détails).
  Mettre en cache des pages authentifiées est un risque de fuite inter-client dès
  qu'un cache partagé se trouve sur le chemin.
- **47 `sudo()`**, dont 24 dans les contrôleurs.
- **Aucun test** dans le module.

## 6. Périmètre fonctionnel — ce qui existe

`freight.shipment` porte **140 champs**, `shipment.freight.booking` 114,
`shipment.quotation` 60. La couverture multimodale est réelle au niveau du
modèle de données :

- **Maritime** : `vessel_id`, `voyage_no`, `obl`, `port_ids`,
  `ocean_shipment_type` (FCL/LCL), `freight.port`, `freight.vessel`.
- **Aérien** : `mawb_no`, `freight.airline`.
- **Terrestre** : `truck_ref`, `trucker`, `trucker_number`, `truck_owner_id`,
  `inland_shipment_type` (FTL/LTL), héritage de `fleet.vehicle`.
- **Transverse** : `shipper_id`/`consignee_id` + notifiés, adresses source et
  destination éclatées, `freight.incoterms`, `freight.route`, `freight.service`,
  `shipment.package.line`, `shipment.tracking`, `freight.documents`,
  `freight.statement`, rapports QWeb (B/L, AWB, CMR, waybill, instruction
  d'expédition).
- **Intégrations** : hérite `sale.order`, `account.move`, `stock.picking`,
  `crm.lead`, `res.partner`, `product.template`, `fleet.vehicle`,
  `portal.mixin`.

**Transport de véhicules** : aucun modèle dédié. Pas de VIN, pas
d'immatriculation sur l'expédition. `fleet.vehicle` décrit **notre** flotte, pas
la marchandise. Ce besoin DallyTrading devrait être ajouté par le bridge.

Dépendances : `contacts, base, base_setup, account, product, web, fleet, mail,
board, calendar, sale_management, stock, website, crm, portal, hr` — toutes
Community, mais lourdes (`website`, `hr`, `stock`). `apexcharts.js` est vendorisé
dans les assets.

## 7. Ce que je n'ai pas fait, et pourquoi

Non exécuté : stack isolée `dallytrading-freight-eval`, installation, inspection
du registre, smoke opérationnel SEA/AIR/LAND, tests ACL et IDOR dynamiques,
énumération de suivi, facturation et stock synthétiques.

Motif unique : le §1. Installer et exercer une copie obtenue par redistribution
non autorisée, puis construire dessus, est précisément ce qu'il ne faut pas
engager avant que la question du titre soit réglée.

L'audit statique suffit néanmoins à décider : les trois points bloquants sont
lisibles dans le manifeste, le CSV d'ACL, l'unique `ir.rule` et un contrôleur de
250 lignes.

## 8. Architecture si le module est acquis

`tk_freight` reste un **moteur opérationnel interne**. Rien de lui n'est exposé.

```
Browser → Next.js → BFF → dally_portal / dally_tracking
                              ↓
                     dally_freight_bridge
                              ↓
                         tk_freight
                              ↓
              Sales / Stock / Accounting / Fleet
```

### Source de vérité

| Domaine | Source |
|---|---|
| Prospect, devis commercial | **Dally** (`dally.quote.request`) |
| Exécution de l'expédition | **tk_freight** (`freight.shipment`) |
| Projection publique du suivi | **dally_tracking** |
| Identité et sécurité portail | **dally_portal** |
| Comptabilité | Odoo `account.move`, déclenché par tk |
| Documents | Odoo, exposés par la liste blanche `dally.portal.document` |

### Mapping

| DallyTrading | tk_freight | Remarque |
|---|---|---|
| `dally.quote.request` | `shipment.quotation` → `shipment.freight.booking` | Le devis reste chez nous ; à l'acceptation, le bridge crée le booking |
| `dally.shipment` | `freight.shipment` | 140 champs contre les nôtres ; liaison par `tk_shipment_id`, **non implémentée dans ce cycle** |
| `dally.shipment.package` | `shipment.package.line` | correspondance directe (type, quantité, poids, volume) |
| `dally.shipment.event` | `shipment.tracking` | projection vers notre DTO, `visible_to_customer` restant **notre** décision |
| `dally.portal.document` | `freight.documents` | liste blanche : aucun document tk ne devient public automatiquement |

### Direction de synchronisation

Un seul sens par domaine. `dally.shipment.state` deviendrait une **projection**
de `freight.shipment.stage_id`, pas un second état maintenu en parallèle —
deux états indépendants divergent toujours.

### Migration, si décidée

1. Coexistence, aucun couplage.
2. Liaison `dally.shipment.tk_shipment_id`, lecture seule.
3. Migration sur données synthétiques, réversible.
4. Bascule production, après validation.
5. Dépréciation éventuelle des champs Dally devenus redondants.

## 9. Scores

| Axe | /10 | |
|---|---|---|
| Fonctionnel freight | 7 | large couverture de données, peu de garde-fous |
| Odoo 19 | ? | non mesuré (non installé) |
| SEA | 7 | vessel, voyage, OBL, FCL/LCL, ports |
| AIR | 5 | MAWB et compagnie ; pas de HAWB visible |
| LAND | 6 | camion, chauffeur, FTL/LTL |
| Transport de véhicules | 2 | aucun modèle dédié, ni VIN ni immatriculation |
| Comptabilité | 6 | hérite `account.move`, factures et notes fournisseur |
| Stock | 5 | hérite `stock.picking`, comportement non mesuré |
| Intégration Dally | 6 | mapping clair, mais bridge substantiel à écrire |
| **Sécurité native** | **1** | write portail sur 30 modèles, 1 record rule, suivi public sans jeton, IDOR sudo |
| Sécurité derrière bridge | 7 | atteignable si aucune route tk n'est exposée |
| Maintenabilité | 4 | 0 test, 47 sudo, licence propriétaire, fork tiers |
| Migration | 7 | peu de données Dally, migration réversible |

## 10. Recommandation

**GO SOUS CONDITIONS.**

1. ~~Licence~~ — **close** : le propriétaire la détient. L'évaluation dynamique
   se fait sur sa copie, pas sur le dépôt GitHub tiers.
2. **aucune route tk n'est exposée** — website et portal tk désactivés, `/shipment`
   et `/track/shipment` bloqués au reverse proxy ;
3. les **ACL portail tk sont neutralisées** : `base.group_portal` ne doit
   conserver aucun `perm_write`, et l'unique `ir.rule` perdre `perm_unlink` ;
4. `/post/comment` reste inaccessible tant que l'IDOR n'est pas corrigé ;
5. l'évaluation dynamique est jouée sur la copie licenciée.

### Point d'attention sur la neutralisation des ACL

Odoo **additionne** les ACL : ajouter une ligne en lecture seule ne retire pas un
`perm_write` déjà accordé par la ligne du fournisseur. Une ACL supplémentaire
plus restrictive ne suffira donc pas, et le prétendre serait une fausse sécurité.

Le bridge devra **écraser les lignes du fournisseur par leurs xmlid**
(`tk_freight.access_freight_shipment_portal`, etc.) via des données XML de notre
module, chargé après lui — et le résultat devra être **mesuré dynamiquement**,
groupe par groupe, pas déduit.

Ces conditions se satisfont depuis `dally_freight_bridge` **sans forker le
fournisseur** : un module qui surcharge les ACL et ne route rien vers tk. C'est
la stratégie à privilégier — un fork rendrait chaque mise à jour vendeur
coûteuse.

## 11. Déploiement vendeur, si acquis

Le code tiers reste **hors du dépôt public** :

```
/opt/dallytrading/vendor-addons/tk_freight     # licencié, privé, non versionné ici
addons_path = <community>,/opt/dallytrading/vendor-addons,<dally addons>
```

Non appliqué. Documenté seulement.
