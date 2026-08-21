# -*- coding: utf-8 -*-
"""Freight-specific safe fallback for formatted phone deduplication.

The CRM helper already matches email and most phone variants.  A legacy/local
number can however have no usable ``phone_sanitized`` value (for example
``06 12 34 56 78`` without country metadata), while the Sheet later sends
``+33 6 12 34 56 78``.  Both carry the same nine significant subscriber digits.

This fallback is deliberately conservative: it links only when exactly one
active partner has the same normalized nine-digit tail.  Ambiguity creates a new
partner instead of risking cross-customer data exposure.
"""

import re

from odoo import api, models, _
from odoo.exceptions import ValidationError


SIGNIFICANT_PHONE_DIGITS = 9


class DallyFreightSyncService(models.AbstractModel):
    _inherit = "dally.freight.sync.service"

    @api.model
    def _resolve_partner(self, client, *, existing=None, explicit_id=None):
        Partner = self.env["res.partner"]

        if explicit_id:
            partner = Partner.browse(int(explicit_id)).exists()
            if not partner:
                raise ValidationError(_("partner_id does not identify an existing customer."))
            created = False
        elif existing:
            partner = existing
            created = False
        else:
            email = self._text(client.get("email"), 254)
            phone = self._text(client.get("phone"), 40)
            self._lock_partner_identity(email, phone)
            partner = Partner._dally_find_existing(email=email, phone=phone)
            if not partner and phone:
                partner = self._find_unique_partner_by_phone_tail(phone)
            created = not bool(partner)
            if not partner:
                name = self._text(client.get("name"), 200)
                if not name:
                    raise ValidationError(_("client.name is required for a new customer."))
                partner = Partner.create({"name": name})

        updates = {}
        for source_name, target_name, limit in (
            ("name", "name", 200),
            ("email", "email", 254),
            ("phone", "phone", 40),
            ("address", "street", 500),
        ):
            if source_name in client:
                value = self._text(client.get(source_name), limit)
                if value:
                    updates[target_name] = value

        if updates:
            partner.write(updates)
        return partner, created

    @api.model
    def _find_unique_partner_by_phone_tail(self, phone):
        digits = re.sub(r"\D", "", phone or "")
        if len(digits) < SIGNIFICANT_PHONE_DIGITS:
            return self.env["res.partner"]
        tail = digits[-SIGNIFICANT_PHONE_DIGITS:]

        # Raw columns are normalized in SQL because legacy contacts may not have
        # a useful phone_sanitized value.  LIMIT 2 is intentional: only a unique
        # match may be linked automatically.
        self.env.cr.execute(
            """
            SELECT id
              FROM res_partner
             WHERE active IS TRUE
               AND (
                    RIGHT(regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g'), %s) = %s
                 OR RIGHT(regexp_replace(COALESCE(dally_whatsapp, ''), '[^0-9]', '', 'g'), %s) = %s
               )
             ORDER BY id
             LIMIT 2
            """,
            [SIGNIFICANT_PHONE_DIGITS, tail, SIGNIFICANT_PHONE_DIGITS, tail],
        )
        ids = [row[0] for row in self.env.cr.fetchall()]
        return self.env["res.partner"].browse(ids[0]) if len(ids) == 1 else self.env["res.partner"]
