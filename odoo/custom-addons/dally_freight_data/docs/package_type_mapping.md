# Colis, conteneurs, catalogue : trois représentations, trois questions

Ce document est un **rapport**. Il ne prescrit aucune migration et le code n'a
pas bougé : les trois représentations restent telles quelles.

## Ce qui existe

| Représentation | Où | Nature | Valeurs | Lignes |
|---|---|---|---|---|
| `dally.shipment.package.package_type` | `dally_freight` | Selection | parcel, pallet, crate, bag, drum, container, vehicle, other | 8 |
| `dally.shipment.container_type` | `dally_freight` | Selection | none, lcl, 20ft, 40ft, 40hc, reefer, other | 7 |
| `freight.package` | `tk_freight` | Modèle | *(table vide)* | 0 |

## Pourquoi ce n'est pas un doublon à trois branches

La tentation est de n'en garder qu'une. Elles ne répondent pourtant pas à la
même question, et les fusionner perdrait de l'information.

**`package_type` décrit une unité manutentionnée.** Il vit sur la ligne de
colisage : *dix palettes et trois fûts*. Il répond à « qu'est-ce qu'on
soulève ».

**`container_type` décrit le mode de chargement de l'expédition entière.** Il
vit sur l'expédition, pas sur la ligne : une expédition est en LCL, en 40 pieds
ou pas conteneurisée du tout — elle ne peut pas être les trois. Il répond à
« comment ça voyage ».

**`freight.package` est un catalogue dimensionné.** Ses champs le disent :
`length`, `width`, `height`, `volume`, `gross_weight`, `charge`, plus les
drapeaux `air` / `ocean` / `land` / `container` / `item`. C'est un référentiel
de modèles physiques avec un tarif, pas une nomenclature. Il répond à « combien
mesure et combien coûte ce type d'emballage ».

Le seul vrai recouvrement est la valeur `container` de `package_type` avec le
drapeau `container` de `freight.package`, et les valeurs `20ft` / `40ft` /
`40hc` / `reefer` de `container_type` avec ce que serait un catalogue de
conteneurs.

## Correspondance, à titre indicatif

| `package_type` | `container_type` | `freight.package` (le jour où il sera peuplé) |
|---|---|---|
| parcel | none | `item = true`, dimensions libres |
| pallet | none / lcl | `item = true`, dimensions palette EUR ou US |
| crate, bag, drum | none / lcl | `item = true` |
| container | 20ft, 40ft, 40hc, reefer | `container = true`, une ligne par format ISO |
| vehicle | none / lcl | `item = true` — le véhicule est déjà décrit par `dally.freight.vehicle.cargo` |
| other | other | — |

`container_type = lcl` n'a **pas** d'équivalent dans `package_type` : le
groupage est un mode de chargement, jamais un type de colis. Symétriquement,
`vehicle` n'a pas d'équivalent dans `container_type`.

## Ce qu'il faudrait décider avant de toucher à quoi que ce soit

1. **Le tarif.** `freight.package.charge` fait de ce modèle un objet
   commercial. Le peupler engage une politique de prix ; tant qu'elle n'existe
   pas, la table doit rester vide.
2. **Les formats ISO.** Un catalogue de conteneurs sérieux distingue 20GP,
   40GP, 40HC, 40RF, 45HC, flat rack, open top. Les quatre valeurs actuelles de
   `container_type` sont un raccourci commercial, pas une nomenclature.
3. **Où vit la vérité.** Si `freight.package` devient le catalogue, alors
   `container_type` devrait à terme pointer vers lui plutôt que d'énumérer. Ce
   changement casse les vues, l'API publique et les projections du portail : il
   mérite son propre cycle, avec sa migration de données.

En l'état, les trois cohabitent sans se contredire, et aucune donnée n'est
perdue. Le coût de l'attente est nul ; celui d'une fusion précipitée ne l'est
pas.
