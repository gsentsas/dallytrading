# Freight et consolidation

Le sous-système Freight gère l'expédition opérationnelle sans déplacer la source de vérité comptable hors d'Odoo.

## Périmètre

DallyTrading couvre notamment :

- fret maritime ;
- fret aérien ;
- routier ;
- véhicules ;
- groupage / consolidation ;
- colis et mesures ;
- CBM ;
- poids réel, volumétrique et taxable ;
- suivi et événements ;
- facturation brouillon et paiements liés au Freight ;
- tableaux de bord et notifications.

## Modèles DallyTrading

Le portail et les intégrations publiques manipulent les modèles DallyTrading, notamment `dally.shipment` et ses projections. Les détails du module tiers Freight ne doivent pas traverser la frontière client.

## Pont vers le module tiers

`dally_freight_bridge` confine le module tiers Freight et projette ses données vers les modèles DallyTrading.

### Règle critique de mise à jour

Ne jamais mettre à jour le module tiers seul en production lorsqu'il est utilisé avec le pont.

La mise à jour doit maintenir le confinement dans la même opération :

```bash
odoo -u tk_freight,dally_freight_bridge
```

La raison est simple : le pont corrige les droits du fournisseur. Une mise à jour isolée du fournisseur peut restaurer ses ACL d'origine.

## Sources de vérité

```text
Demande/devis DallyTrading
      │
      ▼
Qualification / acceptation
      │
      ▼
Opération Freight
      │
      ├── projection DallyTrading
      ├── tracking client
      ├── facturation
      └── paiements / caisse
```

Le portail ne doit jamais réécrire directement les modèles techniques du fournisseur.

## Consolidations

Les consolidations organisent les départs groupés et les affectations d'expéditions.

Principes :

- une consolidation a un cycle de vie explicite ;
- une expédition planifiée doit rester cohérente avec les routes et le mode de transport ;
- les changements d'affectation doivent être traçables ;
- les synchronisations externes ne doivent pas écraser silencieusement une modification utilisateur concurrente.

Les améliorations encore en pull request ne doivent être documentées comme stables qu'après fusion dans `main`.

## Événements et visibilité client

Les événements internes sont fermés à la publication par défaut. La visibilité client est une décision explicite.

Un événement publié ne doit jamais exposer :

- notes internes ;
- prix d'achat ;
- marge ;
- identifiants techniques du module tiers ;
- données d'autres clients.

## Facturation Freight

La facturation est basée sur les objets natifs Odoo :

- `sale.order` ;
- `account.move` ;
- `account.payment`.

Le connecteur Google Sheets peut demander la création d'une **facture brouillon**, mais ne doit pas devenir la source comptable de vérité.

## Références

- [Freight Bridge](https://github.com/gsentsas/dallytrading/blob/main/docs/FREIGHT-BRIDGE.md)
- [Glossaire Freight FR](https://github.com/gsentsas/dallytrading/blob/main/docs/FREIGHT-FR-GLOSSARY.md)
- [Connecteur Google Sheets](https://github.com/gsentsas/dallytrading/tree/main/integrations/google-sheets/freight-sync)
