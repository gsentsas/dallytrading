# -*- coding: utf-8 -*-
"""Ce qui arrive à un dossier, consigné depuis le terrain.

## Pourquoi aucun modèle d'événement de plus

`dally.shipment.event` raconte déjà l'histoire d'un dossier : le backoffice la
lit, le portail en publie une partie, le suivi public une autre. Créer un
second modèle pour Dally Ops scinderait cette histoire en deux — le backoffice
n'en verrait qu'une moitié, et il faudrait un jour réconcilier deux tables qui
ne se sont jamais parlé.

Le terrain écrit donc dans le même récit que tout le monde. Ce qui distingue sa
contribution tient en un champ : `ops_event_kind`.

## Ce que ce champ ajoute, et ce qu'il n'ajoute pas

Il nomme la nature du geste — une anomalie, un reconditionnement, un client
contacté — là où `status` ne sait dire que l'état du dossier. Il est nul sur
tout ce qui existait avant : les transitions automatiques et les saisies
backoffice restent ce qu'elles sont, et rien ne les réécrit.

Il ne touche ni `SHIPMENT_STATES`, ni la machine à états, ni la politique de
publication. Un événement de terrain décrit ; il ne fait pas avancer.
"""

from odoo import fields, models

#: Les sept natures qu'un opérateur peut consigner.
#:
#: Fermée, et validée côté serveur. Le libellé qui accompagne chaque code n'est
#: pas décoratif : c'est lui qui deviendra la `description` de l'événement, et
#: c'est ce qui permet au texte de l'opérateur de rester dans la note interne.
OPS_EVENT_KINDS = [
    ("anomaly", "Anomalie constatée"),
    ("damage_noted", "Dommage constaté"),
    ("customer_contacted", "Client contacté"),
    ("awaiting_customer", "En attente du client"),
    ("repacked", "Colis reconditionné"),
    ("handover", "Remise / transmission effectuée"),
    ("other", "Autre événement"),
]


class DallyShipmentEvent(models.Model):
    """L'événement métier, augmenté de la nature que le terrain lui donne."""

    _name = "dally.shipment.event"
    _inherit = "dally.shipment.event"

    ops_event_kind = fields.Selection(
        selection=OPS_EVENT_KINDS,
        string="Nature (terrain)",
        index=True,
        copy=False,
        help="Renseignée uniquement par Dally Ops. Vide sur les événements "
             "engendrés par une transition et sur les saisies backoffice : "
             "c'est ce qui permet de distinguer l'origine sans tenir une "
             "seconde table.",
    )


class DallyOpsEventRequest(models.Model):
    """Le registre d'idempotence des événements de terrain.

    Registre technique, et rien d'autre : il ne raconte aucune histoire, il
    retient seulement quel geste a déjà été traité. L'événement métier, lui,
    vit dans `dally.shipment.event`.

    `intent_hash` porte l'intention entière — dossier, nature, note. Comparer
    l'identifiant seul laisserait un geste recyclé sur une autre intention
    recevoir en silence le résultat du premier, et l'opérateur croirait avoir
    consigné ce qu'il vient d'écrire.
    """

    _name = "dally.ops.event.request"
    _description = "Dally Ops — registre d'idempotence des événements"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(
        required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, readonly=True)
    shipment_id = fields.Many2one(
        "dally.shipment", required=True, index=True, readonly=True,
        ondelete="cascade")
    shipment_event_id = fields.Many2one(
        "dally.shipment.event", required=True, readonly=True,
        # `restrict` : le registre ne doit pas survivre à l'événement qu'il
        # atteste, ni l'événement disparaître en laissant croire qu'il n'a
        # jamais existé.
        ondelete="restrict")
    #: SHA-256 de l'intention complète : action, dossier, nature, note.
    intent_hash = fields.Char(required=True, readonly=True)
    operator_user_id = fields.Many2one(
        "res.users", required=True, readonly=True)
    created_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True)

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)",
        "Cette demande a déjà été traitée.")
