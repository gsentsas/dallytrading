# Google Sheets Freight

Le classeur opérationnel Freight peut être synchronisé avec Odoo, mais **Google Sheets n'est pas la source comptable de vérité**.

## Périmètre

Le connecteur couvre notamment :

- `Saisie maritime` ;
- `Saisie aérien` ;
- création de facture brouillon ;
- paiements clients ;
- dépenses internes ;
- transferts de caisse ;
- génération PDF via le script lié.

Les feuilles de synthèse ou d'impression restent des vues dérivées et ne sont pas poussées comme objets métier autonomes.

## Flux Freight

Pour un dossier :

```text
POST /api/v1/freight/sync
      ↓
POST /api/v1/freight/invoice       (optionnel)
      ↓
POST /api/v1/freight/payment       (0..n)
      ↓
POST /api/v1/freight/payment/reconcile
```

Pour la caisse interne :

```text
POST /api/v1/freight/expense
POST /api/v1/freight/cash-transfer
```

## Idempotence

Le classeur conserve des clés métier pour empêcher les doublons :

- clé dossier / source ;
- clé article Freight ;
- clé paiement ;
- clé dépense ;
- clé transfert.

Un retry réseau ne doit jamais créer un second article ou un second paiement pour la même opération.

## Secrets

Ne jamais mettre les clés API :

- dans une cellule ;
- dans le code Apps Script versionné ;
- dans un document partagé.

Elles vivent dans les **Script Properties** du projet Apps Script lié.

## Installation du projet lié

1. Ouvrir le Google Sheet natif.
2. Ouvrir **Extensions → Apps Script**.
3. Utiliser un seul projet lié.
4. Installer les fichiers `Code.gs`, `Cash.gs`, `Pdf.gs` et le manifeste prévu.
5. Ajouter les Script Properties requises.
6. Exécuter `dallySetup()` puis `dallyCashSetup()`.
7. Recharger le classeur.
8. Lancer **Dally CRM → Diagnostic configuration** avant toute écriture.

Ne jamais créer un second `onOpen()` concurrent.

## Valeurs sûres par défaut

Après recréation de la configuration :

- synchronisation automatique : `NON` ;
- facture brouillon automatique : `NON` ;
- synchronisation paiements : `NON` ;
- migration initiale : `NON`.

L'objectif est d'éviter qu'une réinitialisation du connecteur produise des écritures comptables inattendues.

## Déclencheurs

Le déclencheur `onEdit` ne fait pas d'appel HTTP. Il marque les dossiers concernés.

La synchronisation réseau est réalisée par les actions explicites ou le timer lorsque l'automatisation est activée.

Cela évite :

- un appel API par cellule modifiée ;
- l'envoi d'une ligne encore en cours de saisie ;
- les boucles d'édition provoquées par les colonnes de sortie CRM.

## Paiements

Un paiement retiré du Sheet ne peut être annulé automatiquement que tant qu'il n'a pas produit un paiement comptable natif irréversible.

Un paiement déjà enregistré en comptabilité doit faire l'objet d'une correction comptable explicite.

## `Sur devis`

Une ligne de marchandise peut être synchronisée même si son prix final n'est pas encore défini.

En revanche, elle ne doit pas être considérée comme facturable tant que les données tarifaires nécessaires ne sont pas validées.

## Développements en cours

Les améliorations de synchronisation bidirectionnelle de la consolidation doivent rester considérées comme **non stables** tant que leur pull request n'est pas fusionnée dans `main`.

## Référence complète

[integrations/google-sheets/freight-sync/README.md](https://github.com/gsentsas/dallytrading/blob/main/integrations/google-sheets/freight-sync/README.md)
