# Trading

Sous-système `dally_trade` : les opérations commerciales de DallyTrading, du premier
contact au règlement.

> **Validation Odoo 19 réelle — 13 août 2026.** La suite complète passe avec 587 méthodes, 0 échec et 0 erreur. `dally_trade` représente 104 résultats de module, 25,83 s et 19 278 requêtes.

---

## 1. Périmètre

`dally_trade` traite les transactions commerciales auxquelles DallyTrading **participe
elle-même**. Ce n'est ni du sourcing, ni du fret, ni une commande déguisée.

| Ce que c'est | Ce que ce n'est pas |
|---|---|
| Une transaction avec deux contreparties, deux devises, des coûts et une marge | Une `purchase.order` ou une `sale.order` : celles-ci ont **une** contrepartie et **une** devise |
| Une opération qui **peut** naître d'un sourcing | Une suite obligatoire du sourcing — `sourcing_request_id` est facultatif et le plus souvent vide |
| Un dossier qui **déclenche** une expédition | Un moteur de fret : colis, conteneurs, poids taxable et suivi restent dans `dally_freight` et `dally_tracking` |
| Un dossier qui **produit** des commandes | Un moteur de stock, de facturation ou de paiement : ce sont les flux natifs d'Odoo |

Frontière avec le sourcing : le sourcing répond à « trouvez-moi ce produit ou ce
fournisseur » **pour le compte d'un client**. Le trading, c'est DallyTrading qui achète,
revend, met en relation ou représente, **pour son propre compte**.

## 2. Les six types d'opération

Ils ne sont pas six étiquettes sur un même objet : ils n'engagent pas les mêmes
responsabilités et ne produisent pas les mêmes documents.

| Type | Libellé | Revenu | Volet achat | Commande d'achat |
|---|---|---|---|---|
| `purchase_resale` | Achat-revente | Marge de négoce | oui | oui |
| `import_export` | Import-Export | Marge de négoce | oui | oui |
| `distribution` | Distribution | Marge de négoce | oui | oui |
| `brokerage` | Courtage | Honoraire | **non** | **non** |
| `commission` | Commission | Commission | **non** | **non** |
| `commercial_representation` | Représentation commerciale | Commission | **non** | **non** |

### Les règles sont déclarées une fois

`models/dally_trade_rules.py` porte l'intégralité des règles par type, sous forme de
données. Chaque modèle les lit via `operation_rules()`.

L'implémentation tentante — un `if operation_type == ...` là où le comportement diffère
— disperse les règles dans tout le code, et le jour où un septième type apparaît
personne ne peut énumérer ce qu'il faut changer. Ici la table est lisible d'un coup
d'œil et un test vérifie qu'aucun type n'a de règle manquante.

`operation_rules()` lève un `KeyError` sur un type inconnu plutôt que de retourner un
défaut : un repli silencieux ferait se comporter un type non reconnu comme un
achat-revente, ce qui est exactement la classe de bug que ce fichier prévient.

### Pourquoi un courtage ne peut pas produire de commande d'achat

Parce que DallyTrading n'acquiert pas la marchandise. Émettre une `purchase.order`
enregistrerait une dette qui n'existe pas, dans la comptabilité et dans le reporting
fournisseur. `action_create_purchase_order()` refuse donc explicitement pour
`brokerage`, `commission` et `commercial_representation`.

En revanche une commande de **vente** reste possible sur tous les types : un courtage
facture bien ses honoraires. La différence est ce que représente la ligne, et c'est la
ligne qui en décide.

## 3. Modèles

| Modèle | Rôle | Accessible à |
|---|---|---|
| `dally.trade.opportunity` | Le dossier : parties, workflow, devises, marge, approbation | Trade utilisateur et au-dessus |
| `dally.trade.line` | Ce qui est échangé, avec **deux** prix : achat et vente | Trade utilisateur (prix d'achat restreint) |
| `dally.trade.cost` | Les coûts, par catégorie | **Trade responsable et finance seulement** |
| `dally.trade.commission` | Commissions à recevoir et à verser | **Trade responsable et finance seulement** |

### Ce qui est réutilisé plutôt que reconstruit

| Besoin | Réutilisé |
|---|---|
| Référence `DT-TRD-AAAA-NNNNNN` | `dally.reference.mixin` de `dally_core` |
| Contreparties | `res.partner` — trois `Many2one`, pas de modèle de partie |
| Articles | `product.product` — pas de `dally.trade.product` |
| Unités | `uom.uom` |
| Incoterms | `account.incoterms` |
| Montants | `fields.Monetary` avec `currency_field` |
| Anti-doublon contact | `res.partner._dally_find_existing` de `dally_crm` |
| Achat, vente, facturation | `purchase.order`, `sale.order`, `account.move` natifs |
| Expédition et suivi | `dally.shipment`, `dally.shipment.event` |
| Pipeline | `crm.lead` |

### Pourquoi pas de `dally.trade.party`

Envisagé, puis écarté. Les six types n'impliquent jamais qu'un nombre **borné** de
rôles : un client, un fournisseur, un mandant. Trois `Many2one` vers `res.partner`
suffisent, et un modèle intermédiaire ajouterait une jointure, un formulaire et une ACL
sans ajouter de comportement.

Il se justifierait le jour où un dossier devrait porter N intervenants du même rôle avec
des attributs propres à l'opération — une répartition de commission entre trois
apporteurs, par exemple. Ce jour-là, ce sera le moment de l'introduire.

### Pourquoi deux prix sur la ligne, et pas un prix plus une marge

Stocker un prix et un pourcentage obligerait à **dériver** le second, et un chiffre
dérivé est un chiffre que personne n'a décidé. Cela rendrait aussi la devise ambiguë :
« 20 % de marge » sur un achat en CNY revendu en EUR ne veut rien dire sans taux.

Les deux prix sont donc saisis explicitement, et aucun n'est calculé à partir de
l'autre. Le prix d'achat porte `groups=` : un commercial chiffre une vente sans
apprendre ce qu'elle a coûté.

## 4. La frontière de confidentialité

Quatre couches, dont une seule serait insuffisante.

1. **`groups=` sur les champs.** L'ORM ne charge pas le champ du tout. Masquer dans une
   vue ne protège rien : la valeur est toujours dans le résultat de requête.
   Une constante unique, `INTERNAL_GROUPS`, est utilisée partout — pour que la frontière
   ne dérive pas champ par champ, le mode de défaillance où onze champs sont restreints
   et le douzième ne l'est pas. Un test le vérifie.
2. **ACL au niveau du modèle.** `dally.trade.cost` et `dally.trade.commission` sont
   **entièrement** hors de portée des groupes commercial, trade utilisateur et lecture
   seule. Divulguer un coût exigerait d'écrire un accès exprès.
3. **Record rules.** Isolation multi-société en `global`, et une règle
   `create_uid = user.id` sur l'utilisateur d'API.
4. **Liste blanche de payload.** `PUBLIC_PAYLOAD_KEYS` définit ce qui peut sortir. Un
   champ ajouté demain est absent par défaut — la seule direction qui échoue sans
   danger.

### Ce qu'un utilisateur trade voit et ne voit pas

| Voit | Ne voit pas |
|---|---|
| Le dossier, les parties, le workflow | Le fournisseur (`supplier_id`) |
| Les lignes et le prix de vente | Le prix d'achat, le total d'achat |
| L'expédition, la commande de vente | Les coûts, les commissions |
| L'objet, le besoin, les dates | La marge brute, nette, le taux |
| | Les notes de négociation, l'approbation |

`sudo()` n'apparaît nulle part dans le chemin public : il contournerait à la fois les
`groups=` et les record rules.

## 5. Multi-devises : rien n'est soustrait naïvement

Un achat en CNY et une vente en EUR **ne se soustraient pas**.

Les champs de marge ne sont calculés que si l'une des deux conditions est remplie :

- tous les montants sont déjà dans la devise d'analyse ; **ou**
- une conversion explicite est déclarée : `conversion_currency_id`, `conversion_date`
  et `conversion_rate_source`.

Sinon `margin_computable` vaut `False`, les montants restent à zéro, et
`margin_blocker` indique **précisément** ce qui manque. Un chiffre produit en mélangeant
des devises est pire que pas de chiffre, parce qu'il ressemble à une réponse : il est
utilisé, quelqu'un s'engage sur un prix parce que l'écran affichait un bénéfice. Une
marge vide accompagnée d'un motif, elle, se corrige.

`_dally_conversion_rate()` retourne `None` — jamais `1.0` — quand le taux ne peut pas
être établi. Un repli à 1.0 traiterait silencieusement 100 CNY comme 100 EUR.

Deux sources de taux, toutes deux auditables :

| Source | Ce qui est enregistré |
|---|---|
| `odoo_rate` | La date de conversion ; Odoo lève plutôt que de deviner s'il n'a pas de taux ce jour-là |
| `manual` | Le taux saisi, champ par champ, contraint strictement positif |

Une conversion incomplète est refusée à l'écriture : un taux sans date n'est pas
auditable, donc ce n'est pas une conversion.

## 6. Commissions

Un seul modèle, avec un `direction` explicite (`receivable` / `payable`), plutôt que
deux modèles qui dupliqueraient le calcul et finiraient par diverger. L'opportunité
ajoute les commissions à recevoir au produit et retranche celles à verser de la marge :
c'est le seul endroit où le signe compte.

Le montant est **résolu une fois** dans `computed_amount`, pour qu'il ne dépende pas du
chemin de code qui l'a lu.

Garde-fous :

- un montant fixe doit être strictement positif ;
- un pourcentage exige un taux **et** une base — « pourcentage de quoi » est la première
  source de litige sur une commission ;
- un taux supérieur à 1 est refusé : 3 au lieu de 0,03 est une erreur d'unité bien plus
  souvent qu'une commission de 300 %, et elle gonflerait toutes les marges en aval ;
- un pourcentage sur une base exprimée dans une autre devise est refusé : il
  affirmerait silencieusement un taux 1:1.

**Aucun taux par défaut.** Un taux se négocie par opération et par contrepartie ; une
constante dans le code serait un taux que personne n'a accepté, appliqué en silence.

## 7. Coûts

Des lignes catégorisées, pas un total unique. « Le fret, la douane et l'assurance ont
coûté 4 200 € » n'est pas un enregistrement exploitable : quand la marge se révèle
fausse, la question est **quel** coût a été sous-estimé, et un total ne peut pas y
répondre.

Catégories : marchandise, transport, assurance, douane et taxes, manutention,
inspection, frais financiers, documentation, autre.

Chaque coût conserve la devise dans laquelle il a été engagé. Convertir à la saisie
détruirait le chiffre d'origine et masquerait le taux employé.

`is_estimate` reste explicite pour qu'une marge bâtie sur des estimations ne soit pas
prise pour une marge établie.

## 8. Workflow

Seize états. Chacun répond à une question qu'un opérateur pose réellement — « est-ce
chiffré ? », « ça attend qui ? », « le client a-t-il signé ? », « sommes-nous encore
payés ? ». Les regrouper reviendrait à mettre la même information dans un champ de
notes, où elle n'est ni filtrable ni reportable.

```
draft → qualifying → structuring → pricing → approval_pending → approved
      → proposal_sent → negotiating → contracted → purchasing → executing
      → settling → closed
```

Plus `on_hold` (avec retour à l'état d'origine, mémorisé et non deviné), `cancelled` et
`lost`.

`ALLOWED_TRANSITIONS` est déclaré comme donnée. Sans cela une opération pourrait passer
de `draft` à `closed` : un dossier clôturé sans contrepartie, sans prix, sans
approbation et sans commande, et personne ne s'en aperçoit avant qu'on demande ce qui a
été échangé.

### Garde-fous métier

| Action | Condition |
|---|---|
| `action_structure` | un type d'opération |
| `action_start_pricing` | au moins une ligne |
| `action_approve` | droits d'approbation **et** marge calculable si l'approbation est requise |
| `action_send_proposal` | approbation obtenue si requise, un montant ou une commission, un destinataire |
| `action_contract` | approbation obtenue si requise |
| `action_start_purchasing` | un type qui comporte un volet achat |
| `action_create_purchase_order` | type autorisant l'achat, contractualisé, fournisseur, devise, société, lignes exploitables |
| `action_create_sale_order` | contractualisé, client, devise, société, lignes exploitables |

Les parties requises par le type ne sont vérifiées qu'à partir de `structuring` : une
demande publique ne peut pas savoir qui sera le fournisseur, et l'exiger à la réception
rendrait le formulaire impossible à remplir.

## 9. Approbation

Trois déclencheurs, du plus grave au plus contextuel :

1. **Marge nette négative.** Aucun paramétrage nécessaire : une opération qui perd de
   l'argent ne doit jamais être engagée sans que quelqu'un l'ait décidé.
2. **Taux de marge sous un plancher configuré.**
3. **Produit au-dessus d'un plafond configuré.**

Les seuils sont lus dans `ir.config_parameter` :

| Clé | Effet si vide |
|---|---|
| `dally_trade.approval_revenue_threshold` | Aucun plafond |
| `dally_trade.approval_min_margin_rate` | Aucun plancher |

Ils sont créés **vides** à l'installation. Livrer `0.15` ou `10000` reviendrait à
inventer la politique de risque de DallyTrading, et la première opération bloquée ou
laissée passer le serait par un nombre que personne n'a choisi. Vide signifie « pas de
seuil », jamais « seuil par défaut ».

Une opération dont la marge n'est **pas calculable** ne peut pas être approuvée :
approuver un chiffre inconnu n'est pas approuver.

L'approbation est réservée à la direction trade et à la direction générale, vérifiée en
Python et pas seulement par le `groups=` du bouton — un attribut de vue est un confort
d'interface, pas un contrôle.

## 10. Conversions vers les documents natifs

Même règle que `dally_sourcing` (ADR-013) : **une ligne réelle, ou aucun document.**

Une commande sans ligne exploitable peut être confirmée et apparaît dans le reporting
alors que plus personne ne sait ce qui devait être acheté. Une ligne de vente à prix nul
peut en outre être facturée, et le client reçoit une facture pour rien. Un document vide
n'est pas une absence de décision : c'est une décision fausse déjà enregistrée.

Les deux actions créent la commande **avec ses lignes en un seul appel**, ou refusent
avec un `UserError` qui énumère ligne par ligne ce qui manque. Un dossier partiellement
exploitable ne produit **rien** : la moitié d'une commande est pire que pas de commande,
parce que la moitié manquante est invisible.

Chaque ligne doit porter un `product_id`, une quantité strictement positive et un prix
strictement positif sur le côté concerné. L'unité de mesure est délibérément omise :
Odoo la dérive du produit, qui en est la source de vérité.

Les deux conversions sont **idempotentes** : relancées, elles ouvrent le document
existant.

## 11. Fret et CRM

`action_create_shipment()` crée un `dally.shipment` dans `dally_freight` et s'arrête là.
Aucune logique de transport ici : poids, colis, conteneurs, poids taxable et timeline de
suivi appartiennent à `dally_freight` et `dally_tracking`. Les dupliquer donnerait deux
réponses à « où est la marchandise ».

L'extension de `dally.shipment` vit dans `dally_trade`, pas dans `dally_freight` : la
dépendance va dans un seul sens. Le fret ignore le trading, ce qui permet à un
déploiement fret seul d'exister.

`action_create_crm_opportunity()` n'est pas automatique : toutes les demandes reçues
d'internet ne méritent pas une entrée de pipeline, et un pipeline plein de pistes mortes
est un pipeline que personne ne lit.

## 12. Sécurité

### Groupes

| Groupe | Portée |
|---|---|
| `dally_trade.group_dally_trade_user` | Dossiers, parties, lignes, volet vente, workflow |
| `dally_trade.group_dally_trade_manager` | En plus : volet achat, coûts, commissions, marges, approbation |
| `dally_trade.group_dally_trade_api` | Groupe technique, n'implique **aucun** autre groupe |
| `dally_core.group_dally_finance` | Lecture des coûts, commissions et marges (réutilisé) |

### Utilisateur d'API dédié

`user_dally_api_trade` est le **quatrième** utilisateur d'intégration, pour la raison
d'ADR-011 : l'utilisateur des leads porte `group_dally_commercial`, qui implique
`group_dally_readonly` — précisément le groupe qui garde `internal_notes`. Le réutiliser
ici rendrait les notes internes chargeables par l'ORM sur le chemin public, laissant la
liste blanche du contrôleur comme seule protection.

Il n'appartient à aucun groupe commercial, et une record rule le limite aux
enregistrements qu'il a lui-même créés : la surface d'exposition d'une clé fuitée est
bornée à ce que cette clé a créé, et non à toute la base.

### Scope

`trading:write`, **réutilisé** — il existait déjà dans `AVAILABLE_SCOPES`. Créer un
second nom `trade:write` signifierait deux orthographes pour une permission, et une clé
accordée sur l'une échouerait silencieusement sur l'autre.

## 13. API

### `POST /api/v1/trade/opportunities`

Scope requis : `trading:write`. Idempotent sur `request_uuid`, **archives comprises** —
une soumission archivée comme spam puis rejouée toucherait sinon la contrainte unique et
remonterait en 500 au lieu d'un rejeu.

```json
{
  "request_uuid": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "operation_type": "brokerage",
  "subject": "Mise en relation sur un lot de cacao",
  "description": "…",
  "requirements": "…",
  "service_code": "trade",
  "contact": {
    "name": "Aminata Diallo",
    "company": "Diallo & Fils",
    "email": "aminata@example.com",
    "phone": "+221771234567",
    "whatsapp": "+221771234567",
    "country": "SN"
  },
  "origin_country": "CI",
  "destination_country": "SN",
  "source_url": "https://dallytrading.com/trading",
  "referrer_url": ""
}
```

Réponse `201` :

```json
{
  "success": true,
  "data": {
    "reference": "DT-TRD-2026-000031",
    "operationType": "brokerage",
    "status": "received"
  },
  "requestId": "…"
}
```

### Champs internes refusés, pas ignorés

Un appel portant `internal_cost`, `purchase_margin`, `internal_margin`,
`supplier_score`, `internal_commission`, `negotiation_notes` ou `approval_status` reçoit
un `422 forbidden_field` **nommant le champ**, à n'importe quel niveau d'imbrication.

Le refus est délibéré plutôt qu'un abandon silencieux. Un appelant qui envoie
`internal_margin` est soit dans l'erreur sur le contrat, soit en train de le sonder ;
répondre 201 ne lui apprendrait rien dans le premier cas et le récompenserait dans le
second.

La liste blanche `FLAT_FIELDS` reste ce qui protège réellement le modèle ; la liste des
champs refusés existe par-dessus, pour la qualité du message.

Le même refus est appliqué **côté BFF**, avant validation. Zod supprime les clés
inconnues par défaut : sans ce contrôle, une demande portant `internal_margin` recevrait
un 201. Rien n'atteindrait Odoo, mais l'appelant s'entendrait dire que sa soumission
était correcte. Constaté au premier passage du test fonctionnel, puis corrigé.

### Pas d'endpoint de lecture

Aucun `GET` sur une opération de trading. Un dossier porte des contreparties, des
conditions négociées et un état d'avancement ; l'exposer supposerait un mécanisme de
capacité comparable au `public_tracking_token` du suivi, et rien ne le justifie
aujourd'hui.

## 14. Site

### Deux pages trading, deux rôles

| Page | Intention | Rôle |
|---|---|---|
| `/activites/commerce-trading` | Informationnelle | Explique le métier de négoce et d'intermédiation |
| `/trading` | Conversion | Six étapes pour proposer une opération |

Sans cette séparation les deux pages viseraient la même requête et se partageraient le
signal de classement — cannibalisation de mots-clés, avec Google qui en choisit une,
généralement pas celle qui convertit.

La séparation est tenue à trois endroits : des titres et descriptions différents, des
H1 différents, et `requestHref: '/trading'` sur la fiche activité pour que son appel à
l'action envoie l'intention de conversion vers la page dédiée plutôt que de la
concurrencer.

### Le formulaire

Six étapes. Le type d'opération vient **en premier** : c'est la réponse qui détermine ce
dont parle le reste de la conversation, et un prospect qui y a répondu a déjà dit
l'essentiel.

Chaque type est présenté avec une phrase d'explication, parce que « courtage » et
« commission » sont réellement confondus par qui n'est pas du métier — et un prospect
qui coche le mauvais coûte un appel de qualification.

L'identifiant d'idempotence est généré au montage et réutilisé à chaque réessai : un
double clic ou une connexion coupée ne peut pas créer deux dossiers.

Aucun champ de prix, de coût, de marge ou de commission. Ils ne sont pas « masqués » :
le type `TradeOpportunityInput` n'a pas ces clés, donc il n'y a rien à masquer.

## 15. Ce qui a été vérifié, et comment

| Contrôle | Résultat |
|---|---|
| `validate-addons.py` | 0 erreur, 0 avertissement |
| Compilation Python, XML bien formé | OK |
| `tsc`, `eslint` | OK |
| Vitest | 189 tests |
| Build Next | OK |
| Test fonctionnel bout en bout contre un faux Odoo | 27 contrôles, 0 échec |
| **Tests Odoo** | **104 résultats de module passants ; suite complète 587 méthodes, 0 échec, 0 erreur** |

Le test fonctionnel démarre un faux Odoo et le serveur Next, **tous deux liés à
127.0.0.1 uniquement** — cette machine héberge une vingtaine de domaines en production,
et un serveur de test sur `0.0.0.0` serait joignable depuis internet le temps du test.
Il vérifie explicitement l'inaccessibilité depuis l'IP externe, puis arrête les deux
processus et contrôle que les ports sont fermés.

### Sur le contrôle de fuite

Un `grep` sur le mot `margin` **ne constitue pas une preuve**. La feuille de style
contient `margin:0`, et la page contient la phrase « une marge sur négoce » qui est
précisément ce qu'elle doit expliquer. Les deux sont des faux positifs, et une vraie
fuite se perdrait au milieu.

Le contrôle retire donc d'abord le CSS, puis cherche une **valeur** de marge — un
nombre, un pourcentage ou une devise accolés — et les noms de champs techniques. Les
motifs sont eux-mêmes vérifiés contre un fragment délibérément fuiteux, pour prouver
qu'ils détecteraient une vraie fuite plutôt que de passer sur une page vide.

## 16. Limites connues

| Limite | Raison |
|---|---|
| Tests Odoo | Suite Odoo 19 isolée validée : 104 résultats de module, 0 échec |
| Pas de seuil d'approbation livré | Une politique de risque n'est pas une constante ; les paramètres existent, vides |
| Pas de marge ni de commission par défaut | Même raison : un chiffre par défaut est un chiffre que personne n'a décidé |
| Pas de conversion automatique entre devises | Convertir en silence masquerait le taux ; la conversion est déclarée et datée |
| Pas de `dally.trade.party` | Les six types n'impliquent qu'un nombre borné de rôles (§3) |
| Pas d'endpoint de lecture publique | Un dossier de trading n'a pas d'équivalent au token de suivi |
| Pas de téléversement de documents au formulaire | Les pièces jointes passent par e-mail ou WhatsApp avec la référence |
| Pas de moteur de risque, de KYC, de douane automatisée ni de couverture de change | Hors périmètre : ce sont des produits en soi, pas des fonctions d'un module de négoce |
| Pas d'e-mail transactionnel | SMTP relève de l'administrateur |
