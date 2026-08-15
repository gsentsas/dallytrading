# Espace client — frontière d'authentification

État : **couche BFF + authentification construite et testée, non déployée.**
Branche : `feature/client-portal-mvp`.

Ce document décrit uniquement ce qui existe. Le tableau de bord métier (devis,
sourcing, trading, expéditions, documents, profil) n'est pas commencé.

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

`npm run test` — 281 tests au total, dont 92 sur le portail (5 fichiers) :

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

## 9. Ce qui n'est pas fait

- aucun déploiement : `/espace-client` répond 404 en production ;
- aucune page métier ;
- `PORTAL_SESSION_SECRET` absent de `.env.production` ;
- aucune validation par un navigateur réel contre l'instance Odoo.
