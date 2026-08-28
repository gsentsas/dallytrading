# Sécurité et isolation

La sécurité DallyTrading repose d'abord sur des **frontières structurelles** : isolation des systèmes, droits minimaux et absence de secrets dans le code.

## Règles absolues

### 1. Ne jamais exposer les secrets

Les secrets ne doivent apparaître ni dans Git, ni dans les logs, ni dans le navigateur.

Emplacements prévus :

- `.env` hors Git ;
- `odoo/config/odoo.conf` généré en permissions restrictives ;
- Script Properties pour Google Apps Script ;
- configuration serveur/Plesk pour les secrets d'infrastructure.

### 2. Ne jamais publier PostgreSQL

La base DallyTrading reste sur le réseau Docker privé. Aucun port PostgreSQL n'est publié vers Internet.

### 3. Fermer le Database Manager

L'instance DallyTrading utilise :

```ini
list_db = False
dbfilter = ^dallytrading$
```

Le reverse proxy doit également empêcher l'exposition inutile des routes de gestion de base.

### 4. Ne pas passer les mots de passe en ligne de commande

Les secrets Odoo/PostgreSQL restent dans le fichier de configuration, pas dans les arguments du processus visibles via `ps`.

### 5. Un utilisateur d'intégration par capacité

Une clé API compromise ne doit pas donner accès à toute la plateforme.

Les identités doivent être séparées par besoin : catalogue, devis, tracking, sourcing, Freight, facturation, etc.

## Isolation inter-systèmes

DallyTrading reste séparé des autres environnements présents sur l'hôte :

- pas de base partagée ;
- pas de filestore partagé ;
- pas de clé API partagée ;
- pas de module cœur dépendant d'un autre système ;
- pas de requête vers une autre base métier sans projet d'intégration explicite.

Un partenaire commercial externe reste un `res.partner`, pas une dépendance technique.

## Portail client

Le portail applique :

- session Odoo réelle ;
- cookie HttpOnly/Secure ;
- ACL ;
- record rules ;
- groupes sur les champs ;
- projections publiques en liste blanche.

Une clé d'intégration ne doit jamais servir de secours pour lire les données privées d'un client.

## Données internes

Sont considérées internes par défaut :

- coûts fournisseurs ;
- marges ;
- prix d'achat ;
- commissions ;
- notes de négociation ;
- notes d'exploitation ;
- identifiants techniques ;
- références internes du module tiers Freight.

## Commandes destructives

Sur un serveur partagé, aucune commande destructive sans analyse d'impact et sauvegarde :

```text
docker compose down -v
DROP DATABASE
rm -rf
```

Ces exemples ne sont pas des commandes de routine.

## Audit

Les constats historiques sont documentés séparément. Certains peuvent concerner d'autres systèmes présents sur l'hôte et sont explicitement hors périmètre DallyTrading.

Ne jamais recopier dans un document public la valeur d'un mot de passe, token, clé privée ou secret observé pendant un audit.

## Référence

[docs/SECURITY-FINDINGS.md](https://github.com/gsentsas/dallytrading/blob/main/docs/SECURITY-FINDINGS.md)
