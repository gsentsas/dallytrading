# -*- coding: utf-8 -*-
"""Base URL policy for authenticated DallyTrading users."""

from odoo import models


CRM_BASE_URL_PARAM = "dally.crm.base_url"
CRM_BASE_URL_DEFAULT = "https://crm.dallytrading.com"


def _crm_base_url(env):
    value = env["ir.config_parameter"].sudo().get_param(
        CRM_BASE_URL_PARAM, CRM_BASE_URL_DEFAULT
    )
    return (value or CRM_BASE_URL_DEFAULT).rstrip("/")


class ResUsers(models.Model):
    _inherit = "res.users"

    def get_base_url(self):
        if not self:
            return super().get_base_url()
        self.ensure_one()
        if self._is_internal():
            return _crm_base_url(self.env)
        return super().get_base_url()


class ResPartner(models.Model):
    _inherit = "res.partner"

    def get_base_url(self):
        if not self:
            return super().get_base_url()
        self.ensure_one()
        if any(user._is_internal() for user in self.sudo().user_ids):
            return _crm_base_url(self.env)
        return super().get_base_url()
