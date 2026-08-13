# Architecture

**Projet :** DallyTrading — site public + ERP/CRM
**Date :** 12 août 2026
**Statut :** architecture validée, phase 1 (infrastructure) en cours

---

## 1. État des lieux constaté

Relevé le 12 août 2026 sur `217.154.121.244`, en lecture seule.

### Hôte

| Élément | Valeur |
|---|---|
| OS | Ubuntu 24.04.4 LTS (noyau 6.8.0-137) |
| Panneau | **Plesk Obsidian 18.0.80.2** |
| CPU | 12 vCPU AMD EPYC-Milan |
| RAM | 23 Gi (≈ 17 Gi disponibles) |
| **Swap** | **0 B** — cf. DT-004 |
| Disque | 697 Gi, 337 Gi libres (52 %) |
| Déjà installé | Docker 29.7.2, Compose v5.4.0, PostgreSQL 16.14, Node 20.20.2, Redis, MySQL, Ollama, imunify360, Dr.Web |
| Domaines hébergés | ~20, dont plusieurs en production |

### Instance Odoo préexistante

Le cahier des charges indiquait qu'aucune installation Odoo n'existait. **C'est inexact.**

| Élément | Valeur |
|---|---|
| Version | Odoo **18.0** (build `18.0-20260421`) |
| Base | `sen_containers_crm` |
| Ports | `127.0.0.1:18069` (HTTP), `127.0.0.1:18072` (gevent) |
| Domaine | `https://crm.sen-containers.com` — actif, HTTP 200 |
| Exécution | Conteneurisée, réseau `172.19.0.0/16` |
| Abonnement | `sen-containers` |

Cette instance porte des données de production d'un tiers. Elle est **hors périmètre** :
ni modifiée, ni lue, ni interrogée par le système DallyTrading. Trois vulnérabilités y
ont été constatées et signalées sans intervention : voir
[`SECURITY-FINDINGS.md`](SECURITY-FINDINGS.md).

### État des domaines DallyTrading

| Domaine | DNS | HTTP→HTTPS | HTTPS | Constat |
|---|---|---|---|---|
| `dallytrading.com` | ✅ | ✅ 301 | ⚠️ 403 | vhost + certificat OK, `httpdocs` vide |
| `www.dallytrading.com` | ❌ **absent** | — | ❌ | enregistrement A à créer |
| `crm.dallytrading.com` | ✅ | ✅ 301 | ❌ TLS 18 | vhost présent, **certificat manquant** |

---

## 2. Décisions d'architecture

### ADR-001 — Reverse proxy : nginx de Plesk, pas de conteneur proxy

**Contexte.** Le cahier des charges (§4, §11) prévoit un service `reverse-proxy` dans
Docker Compose, hypothèse valable sur un VPS nu.

**Décision.** Aucun conteneur proxy. Le reverse proxy est le nginx de Plesk, configuré
par domaine via les « directives nginx additionnelles ».

**Motif.** Plesk possède les ports 80 et 443 pour une vingtaine de domaines en
production. Publier un conteneur sur ces ports provoquerait un conflit de bind et
couperait tous les sites de la machine. Plesk gère également l'émission et le
renouvellement Let's Encrypt : les dupliquer créerait deux autorités concurrentes sur
les mêmes certificats.

**Conséquences.** Configuration versionnée dans `infrastructure/nginx/` mais **appliquée
manuellement via Plesk** — elle n'est pas déployable par script. Cet écart est assumé et
documenté dans [`DEPLOYMENT.md`](DEPLOYMENT.md).

### ADR-002 — Instance Odoo 19 dédiée et totalement indépendante

**Contexte.** Un Odoo 18 tourne déjà, avec la base `sen_containers_crm`. DallyTrading
est par ailleurs représentant commercial de SEN CONTAINERS au Sénégal. Trois options
étaient ouvertes : instance dédiée, multi-sociétés sur l'instance existante, ou instance
dédiée avec reporting consolidé.

**Décision.** Instance Odoo 19 **dédiée et sans aucun couplage** : base `dallytrading`,
PostgreSQL propre, filestore propre, utilisateurs, modules, API et sauvegardes propres.
Ni base partagée, ni dépendance technique, ni reporting croisé, ni synchronisation.

**Motif.** L'isolation supprime tout risque pour une base de production tierce et
respecte la primauté de la marque DallyTrading. Une migration 18 → 19 de l'instance
existante aurait fait porter le risque du projet sur les données de SEN CONTAINERS.

**Conséquences.**
- SEN CONTAINERS est modélisé comme un **`res.partner` standard**, au même titre que
  tout autre fournisseur ou partenaire.
- Les champs `business_unit`, `partner_network` et `service_brand` prévus au §23 du
  cahier des charges sont **retirés du périmètre** : aucun champ ni module spécifique à
  SEN CONTAINERS dans le cœur DallyTrading.
- Coût mémoire d'environ 6 à 8 Gi, absorbable sur les 17 Gi disponibles.

### ADR-003 — PostgreSQL en conteneur dédié

**Décision.** Un conteneur `postgres:16-alpine` plutôt que l'instance PostgreSQL 16.14
de l'hôte.

**Motif.** L'instance hôte appartient à Plesk (`psaadm`). La partager coupleraient le
cycle de vie d'Odoo aux mises à jour de Plesk, et une restauration DallyTrading pourrait
affecter d'autres abonnements. Le conteneur rend cycle de vie, sauvegardes et montées de
version indépendants.

**Conséquences.** Aucun port publié sur l'hôte : PostgreSQL n'est joignable que depuis
le réseau Docker `dallytrading_private`, déclaré `internal: true`.

### ADR-004 — Contournement de l'entrypoint de l'image Odoo

**Contexte.** L'`entrypoint.sh` de l'image Odoo officielle lit les paramètres de
connexion dans `odoo.conf` puis les repasse en **arguments de ligne de commande**. Le
mot de passe devient lisible par tout utilisateur du serveur via `ps aux` — constaté sur
l'instance voisine (DT-003), depuis un compte non privilégié.

**Décision.** Surcharger l'entrypoint :

```yaml
entrypoint: ["odoo"]
command: ["-c", "/etc/odoo/odoo.conf"]
```

Les secrets restent dans `odoo.conf` en `0600`, généré depuis un modèle par
`render-config.sh`.

**Conséquences.** On perd la logique d'attente de PostgreSQL de l'entrypoint, reprise par
`depends_on: condition: service_healthy` avec un `healthcheck` `pg_isready`.

### ADR-005 — Rôle PostgreSQL sans `CREATEDB` ni `SUPERUSER`

**Décision.** Le rôle `odoo_dally` ne dispose d'aucun privilège d'administration. La
base est pré-créée par l'entrypoint PostgreSQL et lui appartient ; Odoo s'y initialise
sans jamais avoir besoin de créer une base.

**Conséquences.** `verify-backup.sh --deep` a besoin de `CREATEDB` pour sa base jetable :
le droit est accordé temporairement pendant l'exercice de restauration, puis retiré.
Procédure dans [`RESTORE.md`](RESTORE.md).

### ADR-006 — Dimensionnement calculé, non recopié

**Décision.** `workers = 4`, `max_cron_threads = 2`, limites mémoire 1,5 / 2 Gi.

**Motif.** La formule usuelle `(2 × vCPU) + 1` donnerait 25 workers : elle suppose une
machine dédiée. Ici, 12 vCPU et 17 Gi sont partagés avec Plesk, une vingtaine de
domaines, une autre instance Odoo, MySQL, Redis et Ollama. Pire cas retenu :
4 × 2 Gi ≈ 8 Gi.

**Conséquences.** À réévaluer sous charge réelle. `workers` est piloté par `.env`, donc
ajustable sans modifier le code.

### ADR-007 — Ni Redis, ni sidecar de sauvegarde au MVP

**Décision.** La stack se limite à `postgres` et `odoo`.

**Motif.** §4 : pas de technologie sans justification. Odoo 19 n'a pas besoin de Redis
(cache en base et en mémoire de processus) ; un Redis tourne déjà sur l'hôte si le besoin
apparaît. Un conteneur de sauvegarde devrait de toute façon appeler `docker exec` sur ses
voisins, ce qui suppose de lui monter le socket Docker — soit un accès root — pour
remplacer un simple `cron`. Les sauvegardes sont donc des scripts hôte planifiés.

### ADR-008 — Abstraction `OdooGateway`

**Décision.** Tout accès à Odoo depuis le site passe par une interface unique, avec
trois implémentations interchangeables : `Json2Adapter` (cible), `DallyApiAdapter`
(module `dally_api`), `LegacyRpcAdapter` (encapsulé dans un seul fichier).

**Motif.** Odoo 19 introduit l'API JSON-2 et annonce la dépréciation de XML-RPC /
JSON-RPC. Coupler le site à un protocole voué à disparaître créerait une dette immédiate.

**Réserve honnête.** La disponibilité effective de JSON-2 dans les conditions de ce
projet n'a **pas encore été vérifiée** sur une installation réelle : elle repose sur la
documentation. Validation empirique prévue en phase 3, avant d'en faire la voie primaire.
L'abstraction rend ce point non bloquant.

**Conséquences.** Aucun appel Odoo ne peut exister hors de `services/odoo/`. Les DTO
publics sont des listes blanches explicites de champs : le suivi public ne peut pas
structurellement divulguer marge, coûts fournisseurs ou notes internes (§44).

### ADR-009 — Dépôt Git dans un sous-répertoire `platform/`

**Décision.** Le dépôt est à `/var/www/vhosts/dallytrading.com/platform/`, non à la
racine du vhost.

**Motif.** La racine du vhost contient `.claude.json`, `.imunify_patch_id` et des
répertoires gérés par Plesk (`logs/`, `httpdocs/`, `error_docs/`). Un dépôt à ce niveau
exposerait des secrets à un `git add -A` malencontreux. La séparation rend l'accident
impossible plutôt que simplement improbable.

### ADR-010 — Offre fournisseur et proposition client : deux modèles

**Contexte.** Une demande de sourcing produit des offres fournisseurs (coût unitaire,
transport, assurance, douane, scores) puis une proposition au client (prix de vente,
frais de service, conditions). Les deux pouvaient tenir dans un modèle avec un drapeau
« visible client ».

**Décision.** Deux modèles distincts : `dally.sourcing.offer` et
`dally.sourcing.proposal`, reliés par un unique pont
(`_dally_draft_from_offer`) qui ne fait traverser que le `cost_basis`, lui-même
restreint par `groups=`. Voir ADR-012 : aucun prix de vente n'est dérivé.

**Motif.** Un modèle unique avec filtre laisse « montrer l'offre au client » à un bug
près. Avec deux modèles, l'offre n'a aucun endpoint public, n'apparaît dans aucun DTO,
et son ACL exclut entièrement les groupes commercial et lecture seule. Divulguer un prix
d'achat exigerait d'écrire un endpoint exprès.

**Conséquences.** Un utilisateur commercial peut présenter une proposition sans
apprendre ce qu'elle a coûté : `cost_basis` et `margin` portent `groups=` et sont
retirés par l'ORM hors manager sourcing et finance.

### ADR-011 — Un utilisateur d'API par capacité

**Contexte.** Trois endpoints publics écrivent dans Odoo : leads, devis, sourcing. Un
seul utilisateur d'intégration aurait suffi techniquement.

**Décision.** Un utilisateur par capacité — `user_dally_api_integration` (leads et
devis), `user_dally_api_tracking`, `user_dally_api_sourcing` — chacun dans le groupe
minimal dont ses endpoints ont besoin.

**Motif.** L'utilisateur des leads porte `group_dally_commercial`, qui implique
`group_dally_readonly`, précisément le groupe qui garde `internal_notes`. Le réutiliser
pour le sourcing rendrait les notes internes chargeables par l'ORM, laissant la liste
blanche du contrôleur comme seule protection. Le champ `dally.api.key.user_id` existe
pour cela.

**Conséquences.** Trois clés à gérer plutôt qu'une, et une fuite de clé reste bornée à
ses propres capacités.

### ADR-012 — Aucune marge par défaut dans le code

**Contexte.** La proposition rédigée depuis une offre appliquait
`DEFAULT_MARGIN_RATE = 0.15`, présentée comme un simple point de départ garantissant
qu'un brouillon ne passe jamais sous le coût.

**Décision.** Constante supprimée. Le brouillon part avec `selling_unit_price = 0` et
un `cost_basis` visible. Le passage à `ready` puis `sent` exige un drapeau
`price_validated` posé par `action_validate_price()`, réservé au manager sourcing, à la
finance et à la direction. Toute modification du prix, de la quantité, du fret, des
frais, de la taxe ou de la devise retire la validation.

**Motif.** Un taux d'uplift codé en dur est un prix que l'entreprise annonce sans que
personne ne l'ait choisi. « Point de départ » suppose que quelqu'un le revoie ; rien ne
l'imposait, et un brouillon pouvait partir tel quel. Le garde-fou réel n'est pas une
valeur préremplie mais l'impossibilité d'envoyer un prix non validé. La restriction aux
groupes qui voient le coût est structurelle : juger si un prix couvre un coût suppose
de voir le coût.

**Pourquoi la restriction est en Python et non un `groups=` de champ.** Un groupe de
champ aurait rendu `price_validated` illisible par l'utilisateur sourcing — or c'est
précisément lui qui doit comprendre pourquoi sa proposition ne part pas — et aurait
cassé le retrait automatique de la validation, qui écrit ce champ au nom d'un
utilisateur qui n'a pas le droit de valider. Le champ reste lisible ; l'action est
gardée. `cost_basis` et `margin` gardent leur `groups=` : eux sont confidentiels, pas
cette information de workflow.

**Conséquences.** Une étape de plus dans le circuit, assumée. Une politique de marge
par défaut reste possible plus tard, mais en configuration — administrable, documentée,
éventuellement dépendante du type d'opération — jamais en constante de module. Un test
assure l'absence de l'attribut sur le module, pour que la réintroduire échoue.

### ADR-013 — Conversions commerciales : une ligne réelle, ou aucun document

**Contexte.** `action_create_purchase_order()` et `action_create_sale_order()` créaient
l'en-tête sans `order_line`. La limite était documentée comme volontaire : chiffrer
supposait des choix d'opérateur.

**Décision.** Les deux actions créent la commande **avec sa ligne, en un seul appel**,
ou refusent avec un `UserError` énumérant ce qui manque. Un champ `product_id` est
ajouté sur `dally.sourcing.request` ; son absence bloque la conversion.

**Motif.** Une commande sans ligne peut être confirmée et apparaît dans le reporting
alors que plus personne ne sait ce qui devait être acheté ; une ligne de vente à prix
nul peut en outre être facturée, et le client reçoit une facture pour rien. Un document
vide n'est pas une absence de décision : c'est une décision fausse déjà enregistrée. Un
refus explicite est visible ; une commande vide ne l'est pas.

**Motif du `product_id` plutôt qu'un produit créé à la volée.** Une ligne de commande
Odoo exige un `product_id`, et une demande de sourcing décrit un besoin, pas une
référence de catalogue. Créer le produit automatiquement remplirait le catalogue de
quasi-doublons que personne n'a arbitrés, et cette dette ne se rembourse pas.

**Conséquences.** Une demande doit être rattachée au catalogue avant conversion. Les
deux actions restent idempotentes. L'unité de mesure de la ligne est omise
volontairement : Odoo la dérive du produit, qui en est la source de vérité.

### ADR-014 — Les règles par type d'opération sont des données, pas des branches

**Contexte.** `dally_trade` traite six types d'opération qui n'engagent pas les mêmes
responsabilités : un courtage n'achète jamais la marchandise, une commission n'a pas de
prix d'achat à retrancher. L'implémentation immédiate est un `if operation_type == ...`
partout où le comportement diffère.

**Décision.** Toutes les règles sont déclarées dans
`models/dally_trade_rules.py` — volet achat, volet vente, commande d'achat autorisée,
modèle de revenu, parties requises — et lues par chaque modèle via `operation_rules()`.
`operation_rules()` lève sur un type inconnu au lieu de retourner un défaut.

**Motif.** Des branches dispersées rendent impossible d'énumérer ce qu'il faut changer
pour ajouter un septième type, et le premier oubli fait qu'un courtage se voit émettre
une commande d'achat — enregistrant une dette qui n'existe pas. Un repli silencieux sur
un type inconnu produirait la même chose en pire, puisque rien ne signalerait l'erreur.

**Conséquences.** Un test vérifie que chaque type porte un jeu de règles complet, et un
autre que les types qui n'achètent pas ne peuvent pas produire de commande d'achat. Les
règles restent structurelles : elles ne portent aucun montant, aucun taux et aucun
seuil, qui sont des décisions commerciales et relèvent de la configuration.

### ADR-015 — Pas de marge multi-devises sans conversion déclarée

**Contexte.** Une opération achetée en CNY et revendue en EUR est banale. Le calcul de
marge le plus simple soustrait les deux nombres.

**Décision.** Les champs de marge ne sont calculés que si tous les montants sont déjà
dans la devise d'analyse, ou si une conversion complète est déclarée : devise, date et
source de taux. Sinon `margin_computable` vaut `False` et `margin_blocker` indique
précisément ce qui manque. `_dally_conversion_rate()` retourne `None`, jamais `1.0`.

**Motif.** Un chiffre produit en mélangeant des devises est pire que pas de chiffre,
parce qu'il ressemble à une réponse : quelqu'un s'engage sur un prix parce que l'écran
affichait un bénéfice. Un repli à 1.0 traiterait 100 CNY comme 100 EUR. Une marge vide
accompagnée d'un motif se corrige ; une marge fausse est utilisée.

**Conséquences.** Une étape de saisie supplémentaire dès que les devises diffèrent,
assumée. Une conversion incomplète est refusée à l'écriture : un taux sans date n'est
pas auditable, donc ce n'est pas une conversion. Chaque coût et chaque commission
conserve sa devise d'origine, pour que le chiffre initial et le taux employé restent
visibles.

### ADR-016 — Deux pages trading, deux intentions de recherche

**Contexte.** `/activites/commerce-trading` explique le métier de négoce.
`/trading` demande à un prospect de proposer une opération. Les deux parlent de trading.

**Décision.** Deux pages distinctes, avec des titres, des descriptions et des H1
différents, et `requestHref: '/trading'` sur la fiche activité pour que son appel à
l'action envoie l'intention de conversion vers la page dédiée.

**Motif.** Deux pages visant la même intention se partagent le signal de classement, et
Google en choisit une — généralement pas celle qui convertit. Le mécanisme
`requestHref` existait déjà pour `/sourcing` (ADR implicite dans `config/activities.ts`)
et est réutilisé tel quel plutôt que redécidé.

**Conséquences.** La page activité ne porte plus d'appel à l'action vers `/devis`, ce
qui est voulu : une opération de trading ne se chiffre pas avec le formulaire de devis
fret.

---

## 3. Vue d'ensemble

```text
                              Internet
                                  │
                        ┌─────────▼──────────┐
                        │   Plesk nginx      │  :80 → 301 → :443
                        │   Let's Encrypt    │
                        └───┬────────────┬───┘
             dallytrading.com│            │crm.dallytrading.com
                  www → 301  │            │
              ┌──────────────▼───┐   ┌────▼──────────────────┐
              │ Next.js  :3010   │   │ proxy_pass 127.0.0.1  │
              │  ├─ /api  (BFF)  │   │   :18169  HTTP        │
              │  └─ OdooGateway  │   │   :18172  websocket   │
              └────────┬─────────┘   └────┬──────────────────┘
                       │  HTTPS interne   │
                       └─────────────────►│
                                    ┌─────▼──────────────────────────┐
                                    │ Projet Docker « dally »        │
                                    │                                │
                                    │  odoo:19.0      ─┐             │
                                    │                  ├ dallytrading_private│
                                    │  postgres:16    ─┘  (internal)  │
                                    │                                │
                                    │  volumes :                     │
                                    │   dallytrading_postgres_data          │
                                    │   dallytrading_odoo_filestore         │
                                    └────────────────────────────────┘

        ═══════════ ISOLATION TOTALE — AUCUN LIEN ═══════════

                                    ┌────────────────────────────────┐
                                    │ Odoo 18 — sen_containers_crm   │
                                    │ crm.sen-containers.com         │
                                    │ :18069 / :18072                │
                                    │ HORS PÉRIMÈTRE                 │
                                    └────────────────────────────────┘
```

Le navigateur ne dialogue **jamais** avec Odoo. Toute requête passe par le BFF Next.js,
seul détenteur de la clé d'API (§2, §54).

## 4. Allocation des ports

| Service | Bind | Port | Note |
|---|---|---|---|
| Odoo 19 HTTP | `127.0.0.1` | **18169** | `18069` occupé |
| Odoo 19 gevent | `127.0.0.1` | **18172** | `18072` occupé |
| PostgreSQL (dally) | réseau Docker | 5432 | **aucune publication hôte** |
| Next.js | `127.0.0.1` | **3010** | |

Aucun service du projet n'écoute sur une interface publique. L'exposition passe
exclusivement par le nginx de Plesk.

## 5. Modules Odoo

```text
dally_core            socle : séquences DT-YYYY-NNNNNN, mixins, paramètres, constantes
  ├── dally_crm       extension crm.lead : UTM, service, WhatsApp, anti-doublon
  ├── dally_freight   maritime, aérien, routier, véhicules, groupage, CBM, conteneurs
  │     └── dally_tracking   dally.shipment + dally.shipment.event
  ├── dally_sourcing  dally.sourcing.request + workflow
  ├── dally_trade     dally.trade.opportunity
  ├── dally_agrobusiness   socle extensible, minimal au MVP
  └── dally_api       points d'accès REST versionnés /api/v1/*
```

Dépendances strictement descendantes. Le core Odoo n'est jamais modifié (§3).
`res.partner`, `crm.lead` et `sale.order` sont réutilisés, jamais dupliqués (§70).

## 6. Source de vérité

Odoo devient progressivement la référence pour : clients, prospects, produits, ventes,
achats, factures, stocks, expéditions et suivi métier. Le site ne reconstruit pas un
second ERP : il ne conserve que sa session utilisateur et un cache de présentation.

## 7. Écarts assumés par rapport au cahier des charges

| § | Prescription | Écart | Motif |
|---|---|---|---|
| §4, §11 | Service `reverse-proxy` dans Compose | Supprimé | ADR-001 — Plesk possède 80/443 |
| §6 | Arborescence sous `/opt/dallytrading` | Applicatif sous le vhost | `/opt` inaccessible au compte d'hébergement ; seuls `backups/` et `logs/` système y restent |
| §23 | `business_unit` / `service_brand` SEN CONTAINERS | Retiré | Décision du commanditaire — ADR-002 |
| §4 | Services `redis`, `worker`, `monitoring` | Non retenus au MVP | ADR-007 — pas de techno sans justification |
| §85 | Phase 0 corrective sur l'instance voisine | Supprimée | Instance hors périmètre ; constats signalés par écrit |
| §85 | Sauvegardes en fin de parcours | Remontées en phase 8 | Sauvegarder après accumulation de données réelles serait trop tard |

## 8. Plan par phases

| Phase | Contenu | Statut |
|---|---|---|
| 1 | Dépôt, arborescence, Compose, `odoo.conf`, scripts, nginx, documentation | 🔄 En cours |
| 2 | Démarrage de la stack, durcissement, vhost, critères §88 | ⛔ Requiert accès Docker |
| 3 | Base `dallytrading`, modules natifs, groupes + ACL, validation JSON-2 | ⏳ |
| 4 | `dally_core`, `dally_crm`, `dally_api`, tests | ⏳ |
| 5 | Next.js : socle, design, accueil, activités, contact, SEO | ⏳ |
| 6 | Formulaire de devis multi-étapes → `crm.lead`, idempotence, critères §89 | ⏳ |
| 7 | `dally_freight`, `dally_tracking`, page `/tracking`, critères §90 | ⏳ |
| 8 | Sauvegardes planifiées, exercice de restauration, supervision, critères §91 | ⏳ |
| 9 | Espace client `/mon-compte` | ⏳ |
| 10 | `dally_sourcing` ✅ · `dally_trade` ⏳ | 🔄 |
| 11 | Boutique, CI/CD, staging | ⏳ |
| 12 | Documentation complète et runbooks | ⏳ |
