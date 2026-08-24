# Glossaire français Freight DallyTrading

Ce glossaire est la source de vérité de l'interface `fr_FR` pour les modules
Freight DallyTrading. Il s'applique aux vues Odoo, états, rapports, e-mails,
notifications et projections client. Les clés techniques, codes API, XML IDs et
valeurs d'énumération restent inchangés.

| Source | Terme `fr_FR` retenu | Règle d'emploi |
|---|---|---|
| Freight | Fret | « Freight » ne reste pas visible seul. |
| Shipment | Expédition | Terme unique pour le dossier opérationnel. |
| Freight shipment | Expédition de fret | Seulement lorsque la précision est nécessaire. |
| Freight file / dossier | Dossier de fret | « Dossier » est admis dans les écrans compacts. |
| Booking | Réservation | Pas de conservation de « booking » dans l'interface. |
| Quote / Quotation | Devis | « Demande de devis » pour Quote request. |
| Customer | Client | « Cliente » n'est jamais employé comme libellé générique. |
| Shipper / Consignee | Expéditeur / Destinataire | « Destinataire » logistique, pas « bénéficiaire ». |
| Carrier | Transporteur | Compagnie maritime ou aérienne selon le contexte. |
| Package(s) | Colis | « Liste de colisage » pour Packing List. |
| Goods description | Désignation de la marchandise | « Nature de la marchandise » dans l'aide descriptive. |
| Weight / Gross weight | Poids / Poids brut | Les unités restent `kg`, `m³` et `CBM` selon le champ source. |
| Actual weight | Poids réel | |
| Volumetric weight | Poids volumétrique | |
| Billable / Chargeable weight | Poids taxable | Terme retenu pour la base de facturation. |
| Origin / Destination / Route | Origine / Destination / Itinéraire | |
| Transport mode | Mode de transport | |
| Sea / Air / Road freight | Fret maritime / Fret aérien / Fret routier | « Maritime », « Aérien », « Routier » admis pour les cartes compactes. |
| Vehicle transport / Groupage | Transport de véhicules / Groupage | |
| Tracking / Tracking event | Suivi / Événement de suivi | Le client voit « Suivre mon expédition ». |
| Status | Statut | « État » reste réservé aux politiques techniques et au statut de notification déjà établi. |
| Invoice | Facture | |
| Draft invoice / Posted invoice | Facture brouillon / Facture comptabilisée | Ne jamais confondre avec un paiement. |
| Customer collection | Encaissement client | Terme obligatoire pour `dally.freight.collection`. |
| Payment / Customer payment | Paiement / Règlement client | « Paiement » pour l'écriture comptable ; « encaissement » pour le journal source. |
| Collected by | Encaissé par | |
| Payment method / channel | Mode de paiement / Canal de paiement | |
| Pending invoice/configuration | En attente de facturation/configuration | |
| Registered in accounting | Comptabilisé | |
| Registration error | Erreur de comptabilisation | |
| Cancelled from source | Annulé à la source | |
| Amount received / Balance due | Montant encaissé / Reste à payer | Le PDF utilise « Reste à payer (indicatif) » si la facture n'est pas comptabilisée. |
| Paid / Partially paid / Unpaid | Payé / Partiellement payé / Impayé | |
| Expense / Internal expense | Dépense / Dépense interne | |
| Cash transfer | Transfert de caisse | |
| Sender / Recipient | Émetteur / Bénéficiaire | Hors contexte logistique. |
| Customs / Declared customs value | Douane / Valeur en douane déclarée | |
| Service fee / Other fees / Dossier fee | Frais de service / Autres frais / Frais de dossier | |
| Unit price / Tariff / Tariff family | Prix unitaire / Tarif / Famille tarifaire | |
| Pricing / automatic / manual | Tarification / Tarification automatique / Tarification manuelle | |
| Promotion / Special price | Promotion / Tarif spécial | |
| Invoice-ready / Blocked | Prêt à facturer / Bloqué | |
| Error / Warning | Erreur / Avertissement | |

## États d'expédition

Les libellés suivants sont utilisés dans la sélection Odoo, le suivi, le portail,
les notifications et le tableau de bord. Ils n'altèrent pas les clés techniques.

| Clé technique | Source anglaise | Libellé client actuel | Libellé final `fr_FR` |
|---|---|---|---|
| `draft` | Draft | Brouillon | Brouillon |
| `request_received` | Request Received | Demande reçue | Demande reçue |
| `awaiting_goods` | Awaiting Goods | En attente de la marchandise | En attente de la marchandise |
| `goods_received` | Goods Received | Marchandise reçue | Marchandise reçue |
| `preparing` | Preparing | En préparation | En préparation |
| `ready` | Ready to Ship | Prête à partir | Prête à expédier |
| `departed` | Departed | Partie | Expédition partie |
| `in_transit` | In Transit | En transit | En transit |
| `arrived` | Arrived | Arrivée à destination | Arrivée à destination |
| `customs` | Customs Clearance | En dédouanement | En dédouanement |
| `available` | Available for Pickup | Disponible pour enlèvement | Disponible pour enlèvement |
| `out_for_delivery` | Out for Delivery | En cours de livraison | En cours de livraison |
| `delivered` | Delivered | Livrée | Livrée |
| `cancelled` | Cancelled | Annulée | Annulée |

Les formulations client ci-dessus sont volontairement accordées avec
« expédition » lorsque le sujet est explicite. Dans un badge isolé, elles restent
naturelles sans reprendre le nom du dossier.

## États d'encaissement, de caisse et de notification

| Modèle | Clé technique | Source | Libellé final `fr_FR` |
|---|---|---|---|
| `dally.freight.collection` | `pending` | Pending invoice/configuration | En attente de facturation/configuration |
| `dally.freight.collection` | `registered` | Registered in accounting | Comptabilisé |
| `dally.freight.collection` | `error` | Registration error | Erreur de comptabilisation |
| `dally.freight.collection` | `cancelled` | Cancelled from source | Annulé à la source |
| dépense / transfert | `review` | To review | À vérifier |
| dépense / transfert | `validated` | Validated | Validé |
| dépense / transfert | `cancelled` | Cancelled | Annulé |
| notification | `pending` | En attente | En attente |
| notification | `sent` | Envoyée | Envoyée |
| notification | `failed` | Échec | Échec |
| notification | `skipped` | Ignorée | Ignorée |

## Exceptions assumées

- `tk_freight`, les XML IDs, noms de modèles, codes d'API, clés de paiement et
  valeurs d'énumération restent en anglais : ils sont techniques et ne sont pas
  des libellés d'interface.
- Les noms de produits, partenaires, compagnies et valeurs saisies par les
  utilisateurs ne sont pas traduits automatiquement.
- `Google Sheets`, `XLSX`, `NINEA`, `RCCM`, `ETA`, `AWB`, `LCL` et `CBM` sont
  des noms propres, acronymes ou unités métier. Leur contexte est traduit.
