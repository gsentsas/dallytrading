# Espace client — frontière d'authentification

État : **portail client en lecture seule validé en production. Première mutation
de profil construite et validée sur environnement isolé, non déployée.**
Branche de la mutation : `feature/portal-profile-write`.

Le tableau de bord métier (devis, sourcing, trading, expéditions, documents et
profil en lecture) reste celui déjà déployé. Ce cycle n'ajoute que l'édition du
profil décrite au §11.


---

## 1. Le trajet d'une requête

```
Navigateur
   │  cookie dt_portal_session (HttpOnly, Secure, SameSite=Lax, chiffré)
   ▼
Next.js — BFF                       apps/web/src
   │  proxy.ts ......................ombre : redirige si le cookie est absent
   │  lib/portal/auth.ts ............DAL : lit le cookie, exige Odoo
   │  lib/portal/odoo-portal.ts .....passerelle SANS clé d'API
   ▼  Cookie: session_id=…
Odoo 19 — /api/v1/portal/*          dally_portal/controllers/portal_api.py
   │  auth='user' → session portail réelle
   ▼
ACL → record rules → groups= sur les champs → projection
```

Chaque flèche vers le bas retire des droits. Aucune n'en ajoute.

## 2. La règle qui tient l'ensemble

> **Le cookie ne prouve rien.**

Il contient un identifiant de session Odoo et un horodatage. Rien d'autre : ni
`partner_id`, ni e-mail, ni groupes. Ce n'est pas une économie de place — c'est
que toute valeur portée par le cookie devient une valeur à laquelle on est tenté
de faire confiance. Un `partner_id` scellé serait authentique, et s'en servir
pour filtrer des données transformerait un artefact de transport en autorisation.

Comme il n'y a rien d'autre dedans, la seule chose qu'on puisse en faire est de
retrouver la session Odoo et de laisser Odoo décider. Chaque accès privé
déclenche donc un appel réel à `/api/v1/portal/me`.

## 3. Ce que le proxy fait, et ne fait pas

`apps/web/src/proxy.ts` regarde si le cookie est **présent**. Il ne l'ouvre pas,
ne vérifie ni signature ni expiration, et n'interroge pas Odoo. **Un cookie forgé
au hasard passe ce contrôle**, et `src/proxy.test.ts` l'affirme explicitement.

C'est acceptable parce que rien ne s'y appuie : la page appelle ensuite
`getPortalMe()`, qui interroge Odoo et se fait refuser. Le proxy évite seulement
d'afficher un squelette de page à un visiteur non connecté.

## 4. Séparation des passerelles

| | `DallyApiAdapter` | `PortalOdooGateway` |
|---|---|---|
| Identité | utilisateur d'intégration | le client connecté |
| Transporte | `X-API-Key` | `Cookie: session_id=…` |
| Sert | formulaires publics | `/api/v1/portal/*` |

Deux types distincts, **sans base commune**. `odoo-portal.ts` n'importe jamais
`ODOO_API_KEY*` : un repli sur la clé de service — qui lirait les dossiers de
tout le monde — n'est pas découragé, il est absent du code. Ajouter un mode
« session » au premier adaptateur aurait été plus court et aurait créé exactement
ce bug.

## 5. Variable d'environnement

| Nom | Rôle |
|---|---|
| `PORTAL_SESSION_SECRET` | scelle le cookie (AES-256-GCM) |

```bash
openssl rand -base64 48
```

Serveur uniquement. Sans défaut : un défaut de développement finirait par devenir
la valeur de production, puisque rien ne viendrait jamais le signaler. Le
frontend refuse de démarrer s'il est absent ou plus court que 32 caractères.

**La modifier invalide toutes les sessions portail ouvertes** — c'est le seul
moyen de les révoquer d'un coup.

À ajouter dans `apps/web/.env.production` (0600, non versionné) **avant** tout
déploiement, puis `systemctl restart dallytrading-web`. Ce n'est pas une
`NEXT_PUBLIC_*` : un redémarrage suffit, pas un rebuild.

## 6. Décisions et leurs raisons

**Chiffré, pas seulement signé.** Un cookie signé est lisible : l'identifiant de
session Odoo serait en clair dans les outils du navigateur, un cache disque, un
rapport de bug. AES-256-GCM le chiffre *et* l'authentifie.

**Vérification du compte à la connexion.** `/web/session/authenticate` accepte
aussi un salarié. Sans le rappel immédiat à `/api/v1/portal/me` — qui refuse les
comptes non-`share` par un 403 — un compte interne obtiendrait un cookie portail.
La session ouverte est refermée aussitôt en cas de refus.

**Message d'échec unique.** Identifiant inconnu, mot de passe faux, compte
interne, compte désactivé : même texte, même code, même statut. Distinguer les
cas transformerait le formulaire en oracle d'existence de comptes.

**503 et non 401 quand Odoo est injoignable.** Dire « session expirée » sur une
panne pousserait l'utilisateur à se reconnecter en boucle, et « identifiants
invalides » lui ferait douter de son mot de passe.

**`Secure` dérivé de `NEXT_PUBLIC_SITE_URL`, pas d'`ENVIRONMENT`.** Constaté
pendant ce cycle : `ENVIRONMENT` a un défaut `development` et **est absente de
`apps/web/.env.production`**, le fichier que systemd charge réellement. S'y fier
aurait retiré `Secure` en production sans qu'aucune erreur ne le signale.

**Déconnexion : Odoo d'abord, cookie ensuite.** L'inverse perdrait l'identifiant
nécessaire pour fermer la session Odoo, qui resterait valide jusqu'à expiration.
La route répond toujours 200 : une déconnexion qui échoue laisserait
l'utilisateur avec un cookie qu'il ne peut plus retirer.

## 7. Limite assumée : la limitation de débit

`/api/portal/auth/login` compte par IP (10) et par identifiant (5) sur 5 minutes.

Le compteur par identifiant existe parce que le compteur par IP ne verrait jamais
une attaque distribuée visant **un** compte connu.

⚠️ **Ce n'est pas une protection distribuée.** `checkRateLimit` compte en mémoire
d'un seul processus Node : il ne coordonne rien entre processus et repart de zéro
à chaque redémarrage. C'est un frein qui arrête le cas courant, pas une défense
contre le bourrage d'identifiants. Une vraie protection volumétrique se place
devant Node — nginx `limit_req`, qui exige un `limit_req_zone` dans le bloc
`http`, hors de portée des directives Plesk par domaine (cf. `DEPLOYMENT.md`).

## 8. Ce qui a été prouvé

`npm run test` — 381 tests Vitest au total (17 fichiers). La suite Odoo du
module exécute 97 tests post-install (117 assertions recensées), sans échec :

- scellement : aller-retour, IV aléatoire, identifiant absent du texte scellé,
  huit formes d'altération refusées à l'identique, expiration, horloge future ;
- origine : sous-domaine refusé, http refusé, absence refusée, `Origin` prime sur
  `Referer` ; dix formes de redirection ouverte refusées ;
- passerelle : aucune clé d'API émise, injection d'en-tête bloquée, redirection
  Odoo traitée comme session morte, pas de seconde tentative après un refus ;
- routes : compte interne refusé et session refermée, message identique pour
  identifiant inconnu et mot de passe faux, freinage, 503 sur panne, `no-store` ;
- cloisonnement : deux sessions successives reçoivent chacune leur propre
  réponse, et les cookies émis sont exactement ceux attendus ;
- journalisation : un cycle complet est capturé et ne contient ni mot de passe,
  ni session Odoo, ni secret, ni `Cookie:`, ni `Authorization`, ni clé d'API.

Build vérifié dans une copie isolée (la production sert `.next/` depuis le même
répertoire, un `npm run build` sur place *serait* un déploiement). Le bundle
client contient bien le code du formulaire — contrôle positif — et zéro
occurrence du secret, de la clé d'API, de `session_id` et de `dt_portal_session`.

## 9. Validation E2E dans un vrai navigateur

Faite. Chromium réel, session Odoo réelle, environnement entièrement jetable.

```bash
./infrastructure/scripts/e2e-portal.sh all
```

`up` monte une pile Odoo 19 + PostgreSQL 16 neuve (labels `com.dallytrading.e2e`,
base vide, comptes synthétiques en `.invalid`) et un frontend Next construit dans
une copie du dépôt, écoutant sur `127.0.0.1:3020`. `test` exécute la suite. `down`
détruit les objets portant le label et efface les secrets éphémères — jamais de
`docker prune`, qui sur cette machine partagée finirait par emporter un voisin.

**Rien de tout cela ne touche la production** : ni la base `dallytrading`, ni son
serveur PostgreSQL, ni le filestore, ni les conteneurs de production, ni l'instance
Odoo 18 `odoo_crm` (SEN CONTAINERS).

### Les 28 tests

| Fichier | Ce qu'il établit |
|---|---|
| `01-login` | connexion réussie ; mot de passe absent des URL ; compte interne refusé ; mot de passe faux, compte inconnu et compte interne **indistinguables** (statut, corps, message, timing grossier) |
| `02-session` | rien dans `localStorage`/`sessionStorage`/`document.cookie`/HTML ; cookie HttpOnly, Lax, `/`, **host-only** ; A et B cloisonnés ; `no-store` |
| `07-business` | toutes les surfaces métier et le téléchargement de document restent fonctionnels |
| `08-cross-client` | références réelles ou inventées d'un autre client refusées de façon indistinguable |
| `09-canaries` | aucun champ interne, coût, marge, fournisseur, commission, note ou clé n'atteint le navigateur |
| `10-profile-write` | édition confirmée par Odoo, refresh et reconnexion persistants, A/B isolés, mass assignment et origines externes refusés |
| `03-logout` | cookie retiré, Odoo invalidé, **retour arrière stérile**, onglet dupliqué inerte, cookie supprimé/altéré/inventé refusé, **rejeu d'un cookie authentique refusé** |
| `04-redirect-origin` | `next` externe ramené au portail ; origine externe refusée sur login et logout |
| `05a`/`05b` | le cookie reste authentique, la session Odoo est détruite entre les deux → **accès refusé** |
| `06-network` | audit du trafic réel : aucun secret, aucune donnée de B ; le mot de passe n'existe **que** dans le corps du POST de connexion |

### Deux points qui méritent d'être connus

**Le cookie est host-only.** Aucun `Domain=` n'est posé, donc le navigateur ne
l'enverra jamais à un sous-domaine — en production, jamais à
`crm.dallytrading.com`, qui n'en a aucun usage. Une session envoyée à un hôte qui
n'en a pas besoin est une session exposée pour rien. Vérifié dans Chromium :
`cookie.domain` ne commence pas par un point.

**La suite tourne fichier par fichier, avec redémarrage entre chacun.** Ce n'est
pas une commodité : `/api/portal/auth/login` limite à 10 tentatives par IP sur
5 minutes, et une suite E2E parle depuis une seule IP. La limite n'a pas été
relâchée d'un iota — le compteur vit en mémoire d'un seul processus, et le
redémarrage le remet à zéro. Ce détour **est** la démonstration de la limite
décrite au §7 : elle est réelle, et elle n'est pas distribuée.

### Limites de cette validation

- **`Secure` n'a pas pu être observé** : l'environnement de test est en `http://`,
  où l'attribut empêcherait la connexion. Le comportement est couvert autrement —
  `wantsSecureCookie()` le dérive du schéma de `NEXT_PUBLIC_SITE_URL`, et un test
  unitaire vérifie les deux branches de `cookieOptions()`.
- Un seul moteur (Chromium). Firefox et WebKit n'ont pas été essayés.
- Le navigateur tourne dans l'image officielle Playwright : son Chromium réclame
  neuf bibliothèques système absentes de cet hôte, dont l'installation demanderait
  les droits d'administration.

## 10. Portes de déploiement à conserver

Les gates A à C ont été validés lors du déploiement du portail en lecture seule.
Ils restent des invariants pour le futur déploiement de la mutation.

### A. `PORTAL_SESSION_SECRET` (déjà configuré en production)

```bash
openssl rand -base64 48
```

La production le charge depuis `apps/web/.env.production`, en 0600. Le frontend
refuse de démarrer s'il est absent : c'est voulu. Ne pas le changer pendant le
déploiement du profil, car sa rotation invaliderait les sessions existantes.

Ce n'est pas une `NEXT_PUBLIC_*` : un `systemctl restart dallytrading-web`
suffit, pas un rebuild.

### B. `Secure` validé en HTTPS réel

Le déploiement en lecture seule a confirmé `Secure`, `HttpOnly`, `SameSite=Lax`,
`Path=/` et l'absence de `Domain`. Les tests isolés continuent à couvrir la
dérivation depuis `NEXT_PUBLIC_SITE_URL`.

### C. Le cookie doit rester exactement

| Attribut | Valeur | Pourquoi |
|---|---|---|
| `HttpOnly` | oui | un script injecté ne peut rien lire |
| `Secure` | oui | jamais en clair sur une requête `http://` |
| `SameSite` | `Lax` | défense en profondeur ; la mutation exige aussi un `Origin` exact |
| `Path` | `/` | |
| `Domain` | **ABSENT** | host-only |

`Domain=.dallytrading.com` enverrait la session à `crm.dallytrading.com`, qui
n'en a aucun usage. Une session transmise à un hôte qui n'en a pas besoin est
une session exposée pour rien. Vérifié en E2E sur Chromium : `cookie.domain` ne
commence pas par un point.

### D. Ordre de déploiement — contraint

**Odoo d'abord, frontend ensuite.** Le BFF ne doit appeler la mutation qu'après
installation de la route et de la capacité privée dans `dally_portal`.

1. backup production vérifié ;
2. `dally_portal` à jour (`-u`) sur `crm.dallytrading.com` ;
3. vérifier les refus ORM/RPC et le GET portail ;
4. build puis déploiement du frontend ;
5. test de succès profil et revalidation des surfaces privées/publiques.

L'ordre inverse exposerait temporairement un formulaire sans endpoint compatible.

### E. Rollback à préparer AVANT

- **Odoo** : sauvegarde base + filestore immédiatement avant le `-u`
  (`infrastructure/scripts/backup.sh`), procédure dans `RESTORE.md`.
- **Frontend** : conserver le `.next` précédent avant de le remplacer ; le
  rollback est une restauration de répertoire plus un `systemctl restart`.
- Une donnée de contact déjà enregistrée est une donnée métier confirmée par
  Odoo : un rollback du code ne doit pas la réécrire automatiquement.

## 11. Première mutation : profil client

`Browser PATCH /api/portal/profile`
→ BFF Next.js avec cookie scellé et `Origin` exact
→ session Odoo réelle → `request.env.user.partner_id` → écriture ORM.

### Cible et liste blanche

La cible est toujours le contact exact de l'utilisateur authentifié
(`request.env.user.partner_id`). `commercial_partner_id` sert à projeter la
société, jamais à la renommer : un contact enfant ne peut donc pas modifier
silencieusement sa société mère.

Liste blanche exacte :

- `name` ;
- `phone` ;
- `street` ;
- `street2` ;
- `zip` ;
- `city`.

E-mail/login, société, pays et tous les champs internes restent en lecture seule.

### Fermeture ORM et mass assignment

L'ACL native de `res.partner` reste read-only. Une méthode privée de capacité
contrôle le contact exact, les champs exacts et une sentinelle non
reconstructible depuis JSON. L'override de `res.partner.write` refuse donc tout
appel générique venant d'un utilisateur `share`. La capacité ouvre uniquement
son propre contrôle d'accès puis appelle l'ORM avec l'utilisateur portail réel,
sans
`sudo`, afin de ne pas ouvrir les hooks d'addons réservés au personnel.

Les tests RPC refusent l'écriture directe du contact propre, de sa société et de
la société d'un autre client. La méthode privée n'est pas appelable par RPC.

### Validation, CSRF et cache

Le BFF et Odoo appliquent tous deux une liste blanche stricte, des limites de
longueur, du texte sans contrôles/HTML et un format téléphonique conservateur. Un
payload vide ou contenant une seule clé inconnue est refusé en entier avec
`400 invalid_request`. Le BFF exige `Origin` et sa valeur doit être exactement
l'origine de `NEXT_PUBLIC_SITE_URL`; `Referer` seul, HTTP en production et toute
origine externe sont refusés. `SameSite=Lax` reste une défense en profondeur,
pas le gate CSRF.

Toutes les réponses de mutation portent `Cache-Control: no-store`. Après succès,
l'interface affiche la projection réellement renvoyée par Odoo puis la relit au
refresh ; aucune copie optimiste n'est utilisée.

### Audit et données sensibles

Odoo et le BFF journalisent `requestId`, `action=profile_update`, résultat et UID
ou noms des champs modifiés. Ils n'enregistrent ni payload, ni adresse, ni numéro,
ni session, cookie ou secret. Le suivi minimum est applicatif : le chatter n'est
pas exposé au portail et la mutation ne dépend d'aucun droit sur celui-ci.

## 12. État de ce cycle
