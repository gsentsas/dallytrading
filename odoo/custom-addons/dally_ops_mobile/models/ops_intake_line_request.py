# -*- coding: utf-8 -*-
"""Le registre des mutations d'articles venues du terrain.

## Pourquoi un registre de plus

Celui de l'étape 7 protège la *création* d'un dossier ; celui-ci protège les
*mutations* de ses articles. Les mélanger obligerait à porter des colonnes qui
ne servent qu'à l'un des deux et à raisonner, à chaque lecture, sur le genre de
demande qu'on regarde.

## Pourquoi un instantané du résultat

Un rejeu doit rendre la réponse de **sa** mutation, pas l'état actuel de la
ligne. Sans cela : la correction A passe, sa réponse se perd, la correction B
change le poids, puis le téléphone rejoue A — et lirait le poids de B en
croyant relire le sien.

L'instantané ne contient aucune donnée personnelle : l'article, sa
tarification, les totaux et la référence du dossier. Ni nom, ni téléphone, ni
adresse.
"""

from odoo import fields, models


class DallyOpsIntakeLineRequest(models.Model):
    _name = "dally.ops.intake.line.request"
    _description = "Dally Ops — registre d'idempotence des articles"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    operation = fields.Selection(
        [("add", "Ajout d'article"), ("update", "Correction d'article")],
        required=True, readonly=True,
    )
    #: SHA-256 de la demande normalisée. Aucune donnée personnelle.
    payload_hash = fields.Char(required=True, readonly=True)
    shipment_id = fields.Many2one(
        "dally.shipment", required=True, index=True, ondelete="cascade", readonly=True)
    package_id = fields.Many2one(
        "dally.shipment.package", index=True, ondelete="cascade", readonly=True)
    line_uuid = fields.Char(required=True, index=True, readonly=True)
    #: Le DTO rendu par cette mutation, figé au moment où elle a réussi.
    result_snapshot = fields.Text(required=True, readonly=True)
    operator_user_id = fields.Many2one("res.users", required=True, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)", "Cette demande a déjà été traitée.")
