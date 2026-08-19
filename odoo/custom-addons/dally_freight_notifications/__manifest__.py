# -*- coding: utf-8 -*-
{
    "name": "DallyTrading — Notifications client Freight",
    "summary": "Une politique d'état unique, et une file d'attente durable "
               "pour ce qu'on écrit au client.",
    "description": """
Ce que le client a le droit de voir, et ce qu'on lui écrit — décidés une fois.

## Le problème

Trois questions se posaient à trois endroits différents : le portail affichait
l'état brut, le suivi public publiait un événement si une phrase existait dans
un dictionnaire du code, et personne n'écrivait jamais au client. Trois
réponses, aucune source commune, et rien qui se change sans déploiement.

`dally.freight.state.policy` porte désormais la réponse, une ligne par état :
visible au portail, visible au suivi, notifiable, et sous quel libellé. C'est
une donnée, pas du code — couper un courriel devient une case à décocher.

## L'absence de politique ferme la porte

Un état sans politique, ou dont la politique est archivée, n'est ni publié ni
notifié. C'est le sens sûr : un état ajouté demain reste interne jusqu'à ce que
quelqu'un écrive ce que le client doit lire.

## Pourquoi une file d'attente plutôt qu'un envoi direct

Un courriel envoyé pendant la transaction fait dépendre un changement d'état
métier de l'état du serveur de messagerie. `dally.shipment.notification`
enregistre l'intention **dans la transaction**, avec une contrainte d'unicité
sur l'événement : une vraie transition produit au plus une ligne, et réécrire
le même état n'en produit aucune, puisqu'il n'y a alors aucun événement.

Ce cycle ne fait aucun envoi. Il produit la politique, l'alignement et la file.

## Ce que la file retient du dossier

Une photographie sûre — référence, libellé client, trajet, date, lien de suivi
— et rien d'autre. Le futur gabarit lira ces colonnes et jamais l'expédition :
le rendu d'un courriel s'exécute avec un utilisateur technique, pour qui les
`groups=` d'un coût ou d'une marge ne protègent plus rien.
""",
    "version": "19.0.1.0.0",
    "category": "Inventory/Delivery",
    "author": "DallyTrading",
    "website": "https://dallytrading.com",
    "license": "LGPL-3",
    "depends": ["dally_tracking", "dally_portal", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/dally_freight_notifications_rules.xml",
        "data/dally_freight_state_policy_data.xml",
        "views/dally_freight_notifications_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
