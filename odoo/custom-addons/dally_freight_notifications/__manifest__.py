# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Notifications client Freight",
    "summary": "Politique d'état, outbox durable et livraison des notifications client.",
    "description": """
Une politique unique décide ce que le client voit au portail, dans le suivi
public et par courriel. Les transitions métier n'envoient jamais directement :
elles écrivent une ligne durable dans `dally.shipment.notification`.

Un cron traite ensuite les lignes en attente par lots, avec verrouillage
`FOR UPDATE SKIP LOCKED`, cinq tentatives maximum et revalidation des règles
juste avant l'envoi. Les gabarits sont rendus exclusivement depuis un snapshot
client-safe de la notification, jamais depuis l'expédition.

La protection contre les doublons est garantie pour la concurrence base de
données et les rejeux normaux du cron. SMTP ne fournit pas de clé
d'idempotence externe : un crash après acceptation SMTP mais avant commit peut
théoriquement produire un second envoi lors d'un retry.

Le back-office expose enfin la santé de la file depuis le dossier Freight :
compteurs en attente/échec, filtres opérationnels et relance manuelle réservée
au Manager. La relance remet uniquement en file ; elle n'envoie jamais depuis
l'interface et repasse par toutes les validations du cron.
""",
    "version": "19.0.1.2.2",
    "category": "Inventory/Delivery",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "license": "LGPL-3",
    "depends": ["dally_tracking", "dally_portal", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/dally_freight_notifications_rules.xml",
        "data/mail_template_data.xml",
        "data/dally_freight_state_policy_data.xml",
        "data/ir_cron_data.xml",
        "views/dally_freight_notifications_views.xml",
        "views/notification_ops_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
