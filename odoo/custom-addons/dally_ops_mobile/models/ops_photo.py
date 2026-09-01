# -*- coding: utf-8 -*-
"""Les preuves photographiques d'un dossier de terrain.

## Pourquoi un modèle métier plutôt que `ir.attachment` seul

`ir.attachment` sait stocker des octets ; il ne sait pas dire *de quel dossier*
ils sont la preuve, *à quel titre*, ni *qui* les a pris. Surtout, son identité
est une clé primaire : la publier au navigateur rouvrirait l'énumération que
tout le reste de Dally Ops referme depuis l'origine. Le modèle porte donc une
identité opaque, et la pièce jointe reste un détail de stockage qui ne sort
jamais.

## Ce qui n'existe pas ici, et ne doit pas exister

Aucun champ de publication client. Une photo d'exploitation — un colis éventré,
un emballage refait, une anomalie constatée — n'est pas destinée au client, et
la rendre publiable demanderait une décision qui n'appartient pas au terrain.
`dally.portal.document` reste le seul chemin vers le client, et rien ici ne
mène à lui : ce n'est pas interdit, c'est **inexprimable**.

## Pourquoi rien ne se supprime vraiment

`active = False` plutôt que `unlink`. Une preuve retirée reste une preuve qui a
existé : savoir qu'une photo a été prise puis retirée, par qui et quand, vaut
mieux que de découvrir un dossier sans trace. La pièce jointe survit avec elle,
et `ondelete="restrict"` empêche qu'un ménage sur une autre table l'emporte.
"""

import uuid as uuid_module

from odoo import fields, models

#: Ce qu'une photo documente. Fermé, et validé côté serveur.
#:
#: Cinq valeurs : assez pour que la recherche d'une preuve ait un sens plus
#: tard, assez peu pour qu'un opérateur choisisse sans réfléchir. Une sixième
#: se décidera quand le terrain la réclamera, pas avant.
PHOTO_KINDS = [
    ("reception", "État à la réception"),
    ("package", "Emballage"),
    ("damage", "Dommage ou anomalie"),
    ("preparation", "Préparation avant expédition"),
    ("other", "Autre"),
]

#: Les actions que le registre d'idempotence sait rejouer.
PHOTO_ACTIONS = [
    ("add", "Ajout"),
    ("delete", "Retrait"),
]


class DallyOpsPhoto(models.Model):
    _name = "dally.ops.photo"
    _description = "Dally Ops — photo de dossier"
    _order = "create_date desc, id desc"
    _rec_name = "photo_uuid"

    #: L'identité publiée. Tirée par le serveur, jamais reçue du navigateur.
    photo_uuid = fields.Char(
        required=True, index=True, readonly=True, copy=False,
        default=lambda self: str(uuid_module.uuid4()),
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True, readonly=True)
    shipment_id = fields.Many2one(
        "dally.shipment", required=True, index=True, readonly=True,
        ondelete="cascade")
    attachment_id = fields.Many2one(
        "ir.attachment", required=True, readonly=True,
        # `restrict` : on ne perd pas une preuve par effet de bord. La retirer
        # doit être un geste, pas la conséquence du ménage d'une autre table.
        ondelete="restrict")
    kind = fields.Selection(
        selection=PHOTO_KINDS, required=True, readonly=True)
    operator_user_id = fields.Many2one(
        "res.users", required=True, index=True, readonly=True)

    active = fields.Boolean(default=True, index=True)
    deleted_at = fields.Datetime(readonly=True, copy=False)
    deleted_by_user_id = fields.Many2one(
        "res.users", readonly=True, copy=False)

    _photo_uuid_unique = models.Constraint(
        "UNIQUE(company_id, photo_uuid)",
        "Cette photo existe déjà.")


class DallyOpsPhotoRequest(models.Model):
    """Le registre d'idempotence des deux gestes photo.

    Un seul registre pour l'ajout et le retrait, parce qu'un identifiant de
    demande est unique par société quelle que soit l'action : deux tables
    laisseraient le même identifiant servir une fois à ajouter et une fois à
    supprimer, et le second geste passerait pour neuf.

    `intent_hash` porte l'intention entière — dossier, nature, contenu. Comparer
    l'action seule laisserait un identifiant recyclé sur une autre photo rendre
    en silence le résultat du premier envoi, et l'opérateur croirait avoir
    enregistré ce qu'il vient de faire.
    """

    _name = "dally.ops.photo.request"
    _description = "Dally Ops — registre d'idempotence des photos"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(
        required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, readonly=True)
    action = fields.Selection(
        selection=PHOTO_ACTIONS, required=True, readonly=True)
    photo_id = fields.Many2one(
        "dally.ops.photo", required=True, index=True, readonly=True,
        ondelete="restrict")
    #: SHA-256 du contenu envoyé. Vide pour un retrait, qui n'en porte aucun.
    content_hash = fields.Char(readonly=True)
    #: SHA-256 de l'intention complète : action, dossier, nature, contenu.
    intent_hash = fields.Char(required=True, readonly=True)
    operator_user_id = fields.Many2one(
        "res.users", required=True, readonly=True)

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)",
        "Cette demande a déjà été traitée.")
