# -*- coding: utf-8 -*-
"""Le registre des encaissements enregistrés depuis le terrain.

Troisième registre du module, et pour la même raison que les deux autres : une
demande rejouée après une coupure doit relire son résultat plutôt que d'en
produire un second. Ici l'enjeu est plus lourd qu'ailleurs — un doublon ne
créerait pas seulement une ligne de trop, mais une **écriture comptable** de
trop.

La protection est double, et c'est voulu : ce registre garde le contrat de
Dally Ops, tandis que la clé métier `external_payment_key` garde l'identité de
l'encaissement dans le moteur, avec son propre verrou et sa propre contrainte
d'unicité.
"""

from odoo import fields, models


class DallyOpsPaymentRequest(models.Model):
    _name = "dally.ops.payment.request"
    _description = "Dally Ops — registre d'idempotence des encaissements"
    _rec_name = "request_uuid"

    request_uuid = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, index=True, readonly=True)
    #: SHA-256 de la demande normalisée. Aucune donnée personnelle.
    payload_hash = fields.Char(required=True, readonly=True)
    shipment_id = fields.Many2one(
        "dally.shipment", required=True, index=True, ondelete="cascade", readonly=True)
    collection_id = fields.Many2one(
        "dally.freight.collection", required=True, index=True,
        ondelete="cascade", readonly=True)
    #: Le DTO rendu, figé au moment où l'encaissement a été accepté.
    result_snapshot = fields.Text(required=True, readonly=True)
    operator_user_id = fields.Many2one("res.users", required=True, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _request_unique = models.Constraint(
        "UNIQUE(company_id, request_uuid)", "Cet encaissement a déjà été enregistré.")
