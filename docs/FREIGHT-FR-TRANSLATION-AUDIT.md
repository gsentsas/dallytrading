# Audit de traduction française Freight

Date d'audit : 24 août 2026. Périmètre : modules Freight DallyTrading et
surfaces Freight des modules connexes. Cet audit a été réalisé avant toute
modification applicative.

## Méthode et résultat d'inventaire

- Modules Dally analysés : `dally_freight`, `dally_freight_billing`,
  `dally_freight_bridge`, `dally_freight_dashboard`, `dally_freight_data`,
  `dally_freight_notifications`, `dally_freight_routing`, `dally_tracking`,
  `dally_portal`, `dally_api` et `dally_crm`.
- Aucun de ces modules ne contient `i18n/fr.po` ni `i18n/fr_FR.po`.
- L'export Odoo 19, effectué en lecture seule sur `dallytrading_freight_dev`,
  contient 624 entrées `msgid` (en-tête inclus) pour les six modules installés :
  `dally_api` (109), `dally_crm` (106), `dally_freight` (193),
  `dally_freight_bridge` (17), `dally_portal` (58) et `dally_tracking` (52).
  Cinq modules Freight non installés dans cette base devront être extraits dans
  une base jetable avant génération des catalogues : billing, dashboard, data,
  notifications et routing.
- La recherche des attributs XML visibles a identifié 66 libellés anglais dans
  le périmètre Freight, sans compter les champs Python, sélections, erreurs,
  aides, QWeb et e-mails.
- Aucune chaîne `fuzzy`, aucun doublon de catalogue et aucune traduction
  existante Dally n'ont été trouvés : la correction est une création de
  catalogues, non une réécriture de clés métier.

La colonne « traduction actuelle » distingue l'absence de catalogue de la
chaîne source déjà française. Les messages d'API dont le `code` est contractuel
seront traduits uniquement dans leur texte humain ; le code et le schéma JSON
restent invariants.

## Incohérences inventoriées

| Module | Fichier | Chaîne source représentative | Traduction actuelle | Problème constaté | Traduction proposée | Catégorie |
|---|---|---|---|---|---|---|
| `dally_freight` | `models/dally_shipment.py` | `DallyTrading Shipment`, `Customer`, `Transport Mode`, `Status` | Absente | Noms de modèles et champs anglais | Expédition DallyTrading ; Client ; Mode de transport ; Statut | champ |
| `dally_freight` | `models/dally_shipment.py` | 14 états `Draft` à `Cancelled` | Absente | États anglais dans formulaire, kanban et suivi | Tableau des états du glossaire | état |
| `dally_freight` | `models/dally_shipment.py` | `Sea Freight`, `Air Freight`, `Road Transport`, `Vehicle Transport` | Absente | Modes incohérents avec les cartes françaises | Fret maritime, fret aérien, fret routier, transport de véhicules | état |
| `dally_freight` | `models/dally_shipment_package.py` | `Parcel`, `Pallet`, `Crate`, `Unit Weight`, `Total Volume` | Absente | Colis et unités restent anglais | Colis, palette, caisse, poids unitaire, volume total | champ |
| `dally_freight` | `views/dally_shipment_views.xml` | `Shipments`, `Cancel`, `Customer`, `Cargo`, `Internal Notes` | Absente | Menus, boutons, pages et alertes anglais | Expéditions, Annuler, Client, Marchandises, Notes internes | vue / bouton |
| `dally_freight` | `views/dally_shipment_views.xml` | `Chargeable weight`, `Late`, `Shipment Analysis` | Absente | Aides, filtre, kanban et analyse anglais | Poids taxable, En retard, Analyse des expéditions | vue |
| `dally_freight_billing` | `models/payment_collection.py` | `DallyTrading Freight Customer Collection` | Absente | « collection » ambiguë et non française | Encaissement client de fret DallyTrading | modèle |
| `dally_freight_billing` | `models/payment_collection.py` | `Pending invoice/configuration`, `Registered in accounting`, `Registration error`, `Cancelled from source` | Absente | États d'encaissement critiques en anglais | États du glossaire | état |
| `dally_freight_billing` | `models/payment_collection.py` | `Collected By`, `Inbound Payment Method` et erreurs de comptabilisation | Absente | Champ de collecteur et erreurs anglais | Encaissé par ; Mode de paiement entrant ; messages français | champ / erreur |
| `dally_freight_billing` | `views/payment_collection_views.xml` | `Freight Collections`, `Collection`, `Accounting`, `Collector` | Absente | Écrans d'encaissement majoritairement anglais | Encaissements clients de fret ; Encaissement ; Comptabilité ; Collecteur | vue |
| `dally_freight_billing` | `models/commercial_documents.py` | `Dossier Fee`, `Other Fees`, `Billing Currency`, `Freight Amount` | Absente | Facturation et champs commerciaux anglais | Frais de dossier ; Autres frais ; Devise de facturation ; Montant du fret | champ |
| `dally_freight_billing` | `views/shipment_billing_views.xml` | `Price`, `Freight Billing`, `Prepare Draft Invoice`, `Reset Draft Billing` | Absente | Boutons/action de brouillon anglais | Tarifer ; Facturation du fret ; Préparer la facture brouillon ; Réinitialiser la facturation brouillon | bouton |
| `dally_freight_billing` | `models/shipment_billing.py` | `Actual weight`, `Volumetric`, `On quotation`, `Special` | Absente | Sélections tarifaires anglaises | Poids réel ; Poids volumétrique ; Selon devis ; Tarif spécial | état |
| `dally_freight_billing` | `models/freight_tariff.py` et vues | `Freight Tariff`, `Customer Segment`, `All`, `Individual`, `Business` | Absente | Tarification anglaise | Tarif de fret ; Segment client ; Tous ; Particulier ; Professionnel | champ |
| `dally_freight_billing` | `models/cash_operations.py` et vues | `Internal Freight Expenses`, `To review`, `Internal Cash Transfer` | Absente | Caisse et dépenses anglaises | Dépenses internes de fret ; À vérifier ; Transfert interne de caisse | état / vue |
| `dally_freight_billing` | `reports/freight_invoice_report.xml` | Textes visibles français ; titre de contexte à vérifier | Partielle par source | Le PDF est majoritairement français, mais doit être vérifié contre les libellés dynamiques et les états traduits | Facture ; Facture — brouillon ; Encaissements ; Reste à payer (indicatif) | rapport |
| `dally_freight_notifications` | `data/mail_template_data.xml` | `Freight — prise en charge`, `dossier Freight` | Source mixte | E-mails français mais « Freight » reste visible | Fret ; dossier de fret | e-mail |
| `dally_freight_notifications` | `data/dally_freight_state_policy_data.xml` | `Prête à partir`, `Partie`, `Livrée`, `Annulée` | Française mais divergente | Accord et formulation diffèrent du statut sélectionné anglais et des vues | États client du glossaire | état |
| `dally_freight_notifications` | modèles et vues | `Notification` / autres libellés déjà français ; une `AccessError` anglaise | Source mixte | Une erreur interne reste anglaise | Gestionnaire requis pour relancer une notification de fret | erreur |
| `dally_tracking` | `models/dally_shipment.py` | `Your shipment is in transit.`, `Status changed to` | Absente | Chatter, événement automatique et suivi public anglais | Votre expédition est en transit ; Statut modifié : | notification |
| `dally_tracking` | `models/dally_shipment_event.py` et vues | `Tracking Events`, `Visible to Customer`, `Customer-Facing Description` | Absente | Événements et publication anglais | Événements de suivi ; Visible au client ; Description destinée au client | vue |
| `dally_tracking` | `controllers/tracking.py` | `No shipment matches this reference and tracking code.` | Absente | Message utilisateur anglais ; code API stable | Aucune expédition ne correspond à cette référence et à ce code de suivi. | erreur API |
| `dally_freight_dashboard` | données, modèle et vue | `Demandes Freight`, `Tableau de bord Freight` | Source mixte | « Freight » reste visible ; les noms `noupdate` doivent être migrés avec prudence | Demandes de fret ; Tableau de bord du fret | dashboard |
| `dally_freight_routing` | modèles et vues | Champs majoritairement français | Française | Vérifier seulement les libellés hérités et conserver les termes du glossaire | Itinéraire, transporteur, expédition | vue |
| `dally_portal` | `models/dally_quote_request.py`, vues | `Customer Decision`, `Rejection reason`, erreurs portail | Absente | Décision de devis exposée en anglais au back-office / portail | Décision du client ; Motif du refus ; messages français | portail |
| `dally_portal` | projections | Libellés de sélection hérités | Dépend de la sélection | Le portail réutilise les labels ; sans catalogue il reproduit l'anglais | Labels `fr_FR` du glossaire | portail |
| `dally_freight_bridge` | modèles | Pont déjà largement français | Française | Pas de texte client fournisseur à réouvrir ; quelques descriptions techniques restent volontairement techniques | Aucun changement de sécurité | autre |
| `dally_freight_data` | données | Noms de ports, compagnies, itinéraires | Données métier | Ne pas traduire ni altérer les noms propres | Sans modification automatique | data |
| `dally_api` | contrôleurs Freight | codes et messages d'erreur | Absente pour le texte humain | Risque de modifier contractuellement l'API | Traduire seulement `message`, jamais `code`/payload | erreur API |
| `dally_crm` | demandes de devis et commandes Freight | chaînes de devis héritées | Absente | Libellés intermédiaires anglais dans le parcours Freight | Devis, demande de devis, client | vue |

## Fournisseur `tk_freight`

Le code fournisseur n'est pas modifié. Son `i18n/fr.po` existe mais comporte des
traductions insuffisantes ou incorrectes (`Customer` → « Cliente », `Package` →
« Emballer », `Quotation` → « Citation », `Shipment Status` → « Expédition
statut »). Ces textes ne sont pas une surface client Dally : le bridge retire les
ACL portail, neutralise les routes fournisseur et le garde-fou contrôle ces
invariants. Les e-mails directs fournisseur sont également supprimés par le
bridge.

Conséquence : aucune surcharge fournisseur ne sera appliquée tant qu'un texte
précisément visible dans un écran Dally n'est pas démontré. Si cela devient
nécessaire, elle devra être portée par un module Dally, sans modifier
`tk_freight`, ses ACL ni ses routes, et validée avec le test de confinement.

## Plan de correction contrôlé

1. Créer les catalogues PO depuis l'export Odoo 19 dans une base Freight-dev
   jetable, jamais à la main à partir d'un grep.
2. Ajouter les traductions `fr_FR` suivant le glossaire, en conservant les
   `msgid`, clés d'états, codes API et données métier.
3. Mettre à jour les données `noupdate` de politique et tableau de bord par une
   migration explicite et idempotente, uniquement pour les libellés visibles.
4. Ajouter des tests ciblés de sélection `fr_FR`, de libellé d'encaissement,
   d'état client et du rapport de facture.
5. Valider syntaxe, XML, PO et tests exclusivement dans la stack
   `dallytrading-freight-dev` avec une base jetable et un `--db-filter` strict.

## Checklist manuelle après chargement des traductions

- Menu et listes Expéditions ; formulaire, colis, réservation et devis.
- Suivi, événements, tableau de bord, portail et notifications.
- Encaissements clients, canaux de paiement, tarification, dépenses et
  transferts de caisse.
- Facture PDF : brouillon, articles, encaissements, reste à payer et statuts.
- Vérifier qu'aucun écran ne mélange anglais et français et que le confinement
  `tk_freight` reste intact.
