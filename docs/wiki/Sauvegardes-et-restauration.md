# Sauvegardes et restauration

Une sauvegarde DallyTrading est un **ensemble logique** : base PostgreSQL + filestore + métadonnées nécessaires à la vérification.

## Sauvegarder

```bash
./infrastructure/scripts/backup.sh
```

## Vérifier

```bash
./infrastructure/scripts/verify-backup.sh backups/daily/<timestamp>
```

La simple présence d'un dump n'est pas une preuve de restaurabilité.

## Pourquoi base + filestore

Odoo stocke une partie des pièces jointes dans le filestore. Restaurer uniquement la base peut produire :

- pièces jointes orphelines ;
- documents manquants ;
- incohérences invisibles au démarrage.

La base et son filestore doivent donc être traités comme **une seule sauvegarde métier**.

## Restauration

La restauration de test doit se faire dans un environnement isolé :

- PostgreSQL dédié ;
- volumes dédiés ;
- réseau dédié ;
- aucun port de production réutilisé ;
- aucune écriture sur la base de production.

Le test doit vérifier au minimum :

1. restauration SQL ;
2. restauration filestore ;
3. démarrage Odoo ;
4. ouverture de la base ;
5. présence des modules DallyTrading ;
6. accès à des pièces jointes ;
7. cohérence métier minimale.

## Avant une opération risquée

Toujours prendre une sauvegarde vérifiable avant :

- migration Odoo ;
- modification majeure de modules ;
- changement de stockage ;
- intervention destructive ;
- restauration partielle ;
- maintenance sur les volumes.

## Règle

> Une sauvegarde dont la restauration n'a jamais été testée n'est pas une sauvegarde fiable.

## Références

- [Stratégie de sauvegarde](https://github.com/gsentsas/dallytrading/blob/main/docs/BACKUPS.md)
- [Exercice de restauration](https://github.com/gsentsas/dallytrading/blob/main/docs/RESTORE.md)
