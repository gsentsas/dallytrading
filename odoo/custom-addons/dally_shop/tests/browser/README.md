# Test navigateur de la galerie back-office

Le bug qui a motivé ce test ne se voyait qu'à l'écran : la zone galerie
s'affichait, mais sans bouton d'ajout. Les droits se vérifient en Python et
l'architecture de la vue s'inspecte sur l'arbre XML — la présence d'un bouton,
non. D'où cette spec, et son emplacement : à côté du module qu'elle teste,
plutôt que dans `apps/web/e2e`, qui vise le site public.

## Ce qu'elle exige

Une instance Odoo jetable portant ce module, deux comptes et un produit :

* un compte dans **Boutique — catalogue** *et* capable d'écrire
  `product.template` — écrire un `one2many` exige le droit sur le parent ;
* un compte en **Read Only**, pour vérifier que le bouton disparaît ;
* un produit avec un slug boutique.

## Exécution

```
docker run --rm --network <réseau-odoo> \
  -v <apps/web>:/work -v $(pwd):/work/e2e-galerie -w /work \
  -e ODOO_URL=http://<hôte-odoo>:8069 -e PRODUIT_ID=<id> \
  -e GALERIE_CATALOGUE_LOGIN=... -e GALERIE_CATALOGUE_PASSWORD=... \
  -e GALERIE_LECTURE_LOGIN=... -e GALERIE_LECTURE_PASSWORD=... \
  mcr.microsoft.com/playwright:v1.62.1-noble \
  npx playwright test --config=/work/e2e-galerie/playwright.config.ts
```

`apps/web` est monté pour ses `node_modules` : l'image Playwright n'a pas accès
au registre npm depuis un réseau Docker interne.

## Deux pièges rencontrés, et notés ici

`networkidle` n'arrive jamais sur le back-office Odoo — le bus de notifications
garde une connexion ouverte. On attend `.o_form_view`.

Le kanban complète sa dernière rangée de cartes fantômes : compter
`.o_kanban_record` donnait neuf vignettes pour trois photos. Le sélecteur
exclut `.o_kanban_ghost`.
