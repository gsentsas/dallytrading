# Glossaire

## BFF

**Backend for Frontend.** Couche serveur Next.js appelée par le navigateur et chargée de parler aux APIs privées Odoo.

## CRM

Gestion de la relation client. Dans DallyTrading, Odoo porte les opportunités et les demandes qualifiables.

## ERP

Système de gestion intégré. Odoo 19 constitue le cœur ERP/CRM DallyTrading.

## OdooGateway

Interface unique utilisée par le site pour accéder aux capacités Odoo côté serveur.

## Projection publique

Sous-ensemble explicite de données autorisées à sortir d'Odoo vers un client, le site ou une intégration. Une projection sûre fonctionne par liste blanche.

## Idempotence

Propriété garantissant qu'un même appel rejoué ne crée pas plusieurs fois le même objet métier.

## Source de vérité

Système qui fait autorité pour une donnée. Pour DallyTrading :

- Odoo fait autorité pour le métier, les prix, commandes, achats, factures et paiements ;
- Google Sheets peut être un outil de saisie/synchronisation, mais pas l'autorité comptable ;
- Next.js présente et orchestre les échanges, mais ne décide pas seul des règles métier.

## Freight

Sous-système de gestion des expéditions : maritime, aérien, routier, colis, poids, volumes, consolidation et tracking.

## Consolidation / groupage

Regroupement de plusieurs expéditions ou dossiers sur un départ commun.

## CBM

Cubic Meter / mètre cube. Unité de volume utilisée en fret maritime et logistique.

## Poids volumétrique

Poids calculé à partir des dimensions du colis selon un coefficient métier, utilisé pour comparer volume occupé et poids réel.

## Poids taxable

Poids retenu pour la tarification lorsque la règle métier compare notamment poids réel et poids volumétrique.

## Sourcing

Recherche et qualification de fournisseurs/solutions pour répondre au besoin d'un client.

## Trading

Opération commerciale dans laquelle DallyTrading participe directement : achat-revente, import-export, distribution, courtage, commission ou représentation.

## Pricelist

Liste de prix Odoo utilisée comme autorité de tarification pour un contexte donné, notamment la boutique.

## Record rule

Règle Odoo filtrant les enregistrements qu'un utilisateur peut lire ou modifier.

## ACL

Access Control List. Droits de base d'un groupe sur un modèle Odoo : lecture, création, écriture, suppression.

## `groups=`

Restriction Odoo placée directement sur un champ. Les utilisateurs non autorisés ne reçoivent pas le champ de l'ORM.

## Filestore

Stockage disque Odoo contenant notamment des pièces jointes. Il doit être sauvegardé avec la base.

## Plesk

Panneau d'hébergement qui gère sur l'hôte les domaines, certificats TLS et le reverse proxy nginx.

## Apps Script

Plateforme JavaScript de Google utilisée pour le connecteur lié au classeur Freight.

## Script Properties

Stockage de configuration/secrets du projet Google Apps Script. Utilisé pour les clés API Freight.
