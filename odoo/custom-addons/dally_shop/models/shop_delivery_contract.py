# -*- coding: utf-8 -*-
"""Aligne les bornes Odoo sur le contrat public Next des méthodes de remise."""

from odoo import _, api, models
from odoo.exceptions import ValidationError


class DallyShopDeliveryMethodContract(models.Model):
    _inherit = "dally.shop.delivery.method"

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            values = dict(vals)
            if isinstance(values.get("code"), str):
                values["code"] = values["code"].strip()
            prepared.append(values)
        return super().create(prepared)

    def write(self, vals):
        values = dict(vals)
        if isinstance(values.get("code"), str):
            values["code"] = values["code"].strip()
        return super().write(values)

    @api.constrains("code", "name", "client_help", "fee_policy", "fixed_fee")
    def _check_public_contract_bounds(self):
        for method in self:
            if len(method.code or "") > 64:
                raise ValidationError(_("Le code public est limité à 64 caractères."))
            if len(method.name or "") > 128:
                raise ValidationError(_("Le nom public est limité à 128 caractères."))
            if len(method.client_help or "") > 300:
                raise ValidationError(_("L'aide client est limitée à 300 caractères."))
            if method.fee_policy != "fixed" and method.fixed_fee:
                raise ValidationError(
                    _("Un montant fixe n'est autorisé que pour la politique de frais fixes.")
                )
