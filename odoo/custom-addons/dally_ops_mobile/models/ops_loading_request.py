# -*- coding: utf-8 -*-
"""Le registre qui distingue une reprise d'un second geste.

Même contrat qu'aux étapes précédentes : le téléphone tire un `request_uuid`
avant le premier envoi et le conserve tant que l'intention ne change pas. Une
4G capricieuse rejoue donc la même demande, et le serveur doit rendre le même
résultat sans charger deux fois.

L'empreinte d'intention est ce qui sépare « la même demande » de « une autre
demande portant le même identifiant ». Sans elle, un identifiant réutilisé
par erreur ferait passer un retrait pour un chargement.

Ce registre n'est pas la donnée métier : la vérité du chargement reste
`dally.freight.consolidation.line`. Il ne dit que ce que ce geste-ci a déjà
produit.
"""

from odoo import fields, models


class DallyOpsLoadingRequest(models.Model):
    _name = "dally.ops.loading.request"
    _description = "Dally Ops — geste de chargement déjà traité"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, readonly=True,
    )
    consolidation_id = fields.Many2one(
        "dally.freight.consolidation", required=True, readonly=True,
        ondelete="cascade", index=True,
    )
    package_id = fields.Many2one(
        "dally.shipment.package", required=True, readonly=True,
        ondelete="cascade", index=True,
    )
    action = fields.Char(required=True, readonly=True)
    intent_hash = fields.Char(required=True, readonly=True)
    operator_user_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict",
    )
    created_at = fields.Datetime(
        required=True, readonly=True, default=fields.Datetime.now,
    )

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)",
        "Ce geste de chargement a déjà été traité.",
    )
