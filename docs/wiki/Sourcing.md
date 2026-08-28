# Sourcing

Le sourcing accompagne une demande client depuis le besoin initial jusqu'à l'achat et la vente, sans mélanger les coûts fournisseurs avec la proposition commerciale.

## Cycle métier

```text
Demande client
  → Qualification
  → Recherche fournisseurs
  → Fournisseurs candidats
  → Offres fournisseurs
  → Comparaison
  → Proposition DallyTrading
  → Négociation
  → Acceptation client
  → Achat fournisseur
  → Vente client
  → Exécution
  → Clôture
```

Chaque étape est une décision métier explicite.

## Modèles principaux

| Modèle | Rôle |
|---|---|
| `dally.sourcing.request` | demande client |
| `dally.sourcing.supplier` | fournisseur candidat sur une recherche |
| `dally.sourcing.offer` | offre fournisseur, strictement interne |
| `dally.sourcing.proposal` | proposition présentée au client |

## Frontière offre fournisseur / proposition client

Les coûts fournisseurs et le prix client ne vivent pas dans le même modèle.

```text
Offre fournisseur
  coût, transport, assurance, douane, notes
            │
            ▼
   pont métier contrôlé
            │
            ▼
Proposition client
  prix de vente, frais de service, conditions
```

Le prix de vente n'est pas dérivé automatiquement d'une marge codée en dur.

## Confidentialité

Les utilisateurs commerciaux peuvent présenter une proposition sans connaître nécessairement :

- le coût fournisseur ;
- le `cost_basis` ;
- la marge ;
- le taux de marge ;
- les notes internes fournisseurs.

Cette séparation est appliquée par ACL, groupes de champs et absence d'endpoint public pour les offres internes.

## Réutilisation du standard Odoo

Le module réutilise :

- `res.partner` pour fournisseurs et clients ;
- `purchase.order` pour l'achat ;
- `sale.order` pour la vente ;
- `account.incoterms` ;
- `uom.uom` ;
- les séquences et services communs DallyTrading.

## Garde-fous

Quelques exemples :

- impossible de marquer les fournisseurs identifiés sans fournisseur candidat ;
- impossible de déclarer les offres reçues sans offre ;
- impossible d'envoyer une proposition vide ;
- le prix commercial doit être validé explicitement ;
- les commandes d'achat et de vente exigent des données métier complètes ;
- les états terminaux ne sont pas quittés sans action de réouverture explicite.

## Référence complète

[docs/SOURCING.md](https://github.com/gsentsas/dallytrading/blob/main/docs/SOURCING.md)
