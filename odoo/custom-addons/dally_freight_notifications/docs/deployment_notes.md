# Déploiement — notifications Freight

## Expédition historique en brouillon

Aucune migration automatique ne fait avancer une expédition historique restée en `draft`.

Au déploiement, auditer chaque dossier historique en brouillon en lecture seule. Si le dossier correspond réellement à une demande acceptée et doit être visible par le client, le faire avancer explicitement vers `request_received` par le chemin métier normal. Sinon, le laisser en brouillon.

## Livraison des courriels

Le cron traite les notifications `pending` toutes les 15 minutes, par lots de 100, avec au maximum 5 tentatives. Les transitions Freight ne dépendent jamais du serveur SMTP.

La prise de ligne utilise `FOR UPDATE SKIP LOCKED`, ce qui empêche deux workers de traiter simultanément la même notification et rend le rejeu normal du cron idempotent au niveau base de données.

SMTP ne fournit cependant pas de clé d'idempotence externe : si le serveur SMTP accepte un message puis que le worker meurt avant le commit PostgreSQL qui marque la notification `sent`, une relance peut théoriquement produire un second envoi. Cette fenêtre de crash doit rester documentée ; le système ne revendique pas une garantie « exactly once » au niveau SMTP.

## Confidentialité

Les gabarits sont rendus sur `dally.shipment.notification`, à partir de champs snapshot client-safe uniquement. Ils ne doivent jamais naviguer vers `shipment_id`, `partner_id` ou `event_id`, ni lire des coûts, marges, prix d'achat, fournisseurs, notes internes ou transporteurs internes.

Les URL de suivi peuvent apparaître uniquement dans le contenu envoyé au client. Elles ne doivent jamais être journalisées ni conservées dans `last_error`.
