# Tests et qualité

La validation DallyTrading combine tests statiques, tests Odoo réels, tests frontend et scénarios end-to-end.

## Odoo

Validation statique des addons :

```bash
python3 infrastructure/scripts/validate-addons.py odoo/custom-addons
```

Le dépôt documente une qualification Odoo 19 réelle du 13 août 2026 : **587 méthodes, 0 échec, 0 erreur** sur la suite alors qualifiée, avec 651 résultats en comptant les sous-tests.

Ce nombre est un **historique de qualification**, pas une garantie automatique pour un commit ultérieur.

## Frontend

Depuis `apps/web` :

```bash
npm run verify
```

Cette commande regroupe les contrôles prévus par le projet, notamment typecheck, lint et tests.

Build de production :

```bash
npm run build
```

Un build réussi reste nécessaire après une modification des variables `NEXT_PUBLIC_*` ou des pages statiques.

## E2E

Le dépôt contient des scénarios Playwright couvrant notamment :

- authentification ;
- session et déconnexion ;
- expirations ;
- isolation entre clients ;
- décisions sur devis ;
- pont Freight ;
- véhicules ;
- groupage ;
- boutique et checkout ;
- livraison ;
- routage des devis.

## Règle de validation

Un correctif sensible doit idéalement suivre :

```text
reproduction du bug
→ test rouge
→ correctif minimal
→ test vert
→ régressions voisines
→ revue du diff
```

## Tests et production

Les tests d'intégration destructifs ou migrations se font sur :

- base éphémère ;
- volumes éphémères ;
- environnement isolé ;
- aucune donnée de production tierce.

## CI GitHub

Ne pas supposer qu'un check obligatoire existe s'il n'est pas configuré. La documentation du dépôt recommande de n'ajouter des status checks obligatoires sur `main` qu'une fois une CI réelle présente et stable.

Une future CI minimale devrait couvrir :

- `npm run verify` ;
- `npm run build` ;
- validation statique des addons ;
- tests Odoo ciblés ;
- scénarios de sécurité/isolation critiques.

## Avant fusion

Vérifier :

1. diff limité au périmètre ;
2. pas de secret ;
3. tests pertinents ;
4. migration si le schéma change ;
5. compatibilité des données historiques ;
6. rollback documenté si nécessaire ;
7. aucune dépendance involontaire vers un système hors périmètre.
