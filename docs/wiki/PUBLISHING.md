# Publication vers le GitHub Wiki

Les fichiers de `docs/wiki/` sont les sources prêtes à être utilisées dans le Wiki GitHub.

## Pourquoi cette étape existe

GitHub n'expose pas d'API REST standard pour créer la toute première page d'un Wiki. Le dépôt Git `gsentsas/dallytrading.wiki` n'existe qu'après initialisation du Wiki depuis l'interface GitHub.

## 1. Initialiser le Wiki une seule fois

Sur :

`https://github.com/gsentsas/dallytrading/wiki`

Créer la première page `Home` depuis l'interface GitHub.

Après cette opération, GitHub crée le dépôt Git du Wiki.

## 2. Cloner le Wiki

```bash
git clone git@github.com:gsentsas/dallytrading.wiki.git
cd dallytrading.wiki
```

## 3. Copier les pages

Depuis le dépôt principal :

```bash
cp ../dallytrading/docs/wiki/Home.md .
cp ../dallytrading/docs/wiki/_Sidebar.md .
cp ../dallytrading/docs/wiki/Architecture.md .
cp ../dallytrading/docs/wiki/Installation-et-deploiement.md .
cp ../dallytrading/docs/wiki/Modules-Odoo.md .
cp ../dallytrading/docs/wiki/API-et-integrations.md .
cp ../dallytrading/docs/wiki/Freight-et-consolidation.md .
cp ../dallytrading/docs/wiki/Portail-client-et-tracking.md .
cp ../dallytrading/docs/wiki/Sourcing.md .
cp ../dallytrading/docs/wiki/Trading.md .
cp ../dallytrading/docs/wiki/E-commerce.md .
cp ../dallytrading/docs/wiki/Google-Sheets-Freight.md .
cp ../dallytrading/docs/wiki/Securite-et-isolation.md .
cp ../dallytrading/docs/wiki/Sauvegardes-et-restauration.md .
cp ../dallytrading/docs/wiki/Tests-et-qualite.md .
cp ../dallytrading/docs/wiki/Exploitation-et-depannage.md .
cp ../dallytrading/docs/wiki/Glossaire.md .
```

`PUBLISHING.md` est une procédure de maintenance et n'a pas besoin d'être publié dans le Wiki.

## 4. Vérifier avant push

```bash
git status
git diff --check
```

Contrôler notamment :

- aucun secret ;
- aucun mot de passe ;
- aucun token ;
- aucun `.env` ;
- liens Wiki cohérents ;
- `Home.md` présent ;
- `_Sidebar.md` présent.

## 5. Publier

```bash
git add *.md
git commit -m "docs: initialize DallyTrading wiki"
git push origin master
```

Selon la branche créée par GitHub pour le Wiki, remplacer `master` par la branche distante réellement affichée par `git branch -r`.

## Maintenance

Le dépôt principal reste la source versionnée des pages Wiki. Pour une modification importante :

1. modifier `docs/wiki/*` dans une branche ;
2. relire via pull request ;
3. fusionner dans `main` ;
4. recopier/publier les pages correspondantes dans le dépôt Wiki.

Cette discipline évite qu'une documentation critique ne vive uniquement dans le Wiki sans historique de revue dans le dépôt principal.
