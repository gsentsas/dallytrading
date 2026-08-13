# -*- coding: utf-8 -*-
"""Contact deduplication (§28).

A customer who requests three quotes over six months, each time typing their
name slightly differently, must remain a single ``res.partner``. Without this,
the CRM slowly fills with near-duplicates and the sales history of a given
customer is spread across several records.

The strategy is deliberately conservative: it only ever *links* to an existing
contact, it never merges or edits one. Merging is a human decision — an
automated merge that gets it wrong exposes one customer's data to another.
"""

import re

from odoo import api, fields, models

#: Number of trailing digits compared when matching phone numbers.
#: Senegalese subscriber numbers are 9 digits; comparing the tail absorbs the
#: many ways a caller writes the country code (+221, 00221, 221, or nothing).
PHONE_SIGNIFICANT_DIGITS = 9


def normalize_phone(value):
    """Reduce a phone number to its comparable tail.

    Returns ``None`` when there is not enough signal to match on, so callers
    never compare on a fragment like "77" and match half the database.
    """
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) < PHONE_SIGNIFICANT_DIGITS:
        return None
    return digits[-PHONE_SIGNIFICANT_DIGITS:]


def normalize_email(value):
    if not value:
        return None
    email = value.strip().lower()
    return email or None


class ResPartner(models.Model):
    _inherit = "res.partner"

    dally_whatsapp = fields.Char(
        string="WhatsApp",
        help="WhatsApp number, when it differs from the phone number. "
             "Widely used channel for customer contact in this market.",
    )

    @api.model
    def _dally_find_existing(self, email=None, phone=None, mobile=None,
                             whatsapp=None, company_name=None):
        """Return the best existing partner match, or an empty recordset.

        Criteria are applied in decreasing order of reliability (§28):

        1. **Email** — near-unique in practice.
        2. **Phone / mobile / WhatsApp** — compared on the significant tail, so
           +221 77 123 45 67 matches 771234567.
        3. **Company name** — exact, case-insensitive. Weakest signal, applied
           last and only for companies.

        A first name and last name are never matched on: homonyms are common and
        a false positive would attach one person's request to another's file.
        """
        # 1. Email
        email = normalize_email(email)
        if email:
            match = self.search([("email", "=ilike", email)], limit=1)
            if match:
                return match

        # 2. Phone numbers. All three inbound numbers are compared against both
        #    stored fields, since customers do not distinguish them.
        candidates = {
            normalize_phone(number)
            for number in (phone, mobile, whatsapp)
        }
        candidates.discard(None)
        for tail in candidates:
            # The database stores numbers in whatever shape they were entered,
            # so an exact SQL match is unreliable; a suffix LIKE narrows the set
            # and normalisation confirms it in Python.
            # Odoo 19 a supprimé `res.partner.mobile` : il ne reste que `phone`
            # (et `phone_sanitized`, calculé). Chercher sur `mobile` levait
            # « Invalid field res.partner.mobile in condition » et faisait échouer
            # toute création de demande depuis le site — constaté en production.
            #
            # Le paramètre `mobile` de cette méthode est conservé : les appelants
            # en passent un, et un numéro de mobile reste un numéro à rapprocher.
            # Il est simplement comparé aux mêmes colonnes que les autres.
            possible = self.search(
                [
                    "|",
                    ("phone", "like", tail),
                    ("dally_whatsapp", "like", tail),
                ],
                limit=20,
            )
            for partner in possible:
                stored = {
                    normalize_phone(partner.phone),
                    normalize_phone(partner.dally_whatsapp),
                }
                stored.discard(None)
                if tail in stored:
                    return partner

        # 3. Company name, exact and case-insensitive.
        if company_name:
            name = company_name.strip()
            if len(name) >= 3:
                match = self.search(
                    [("is_company", "=", True), ("name", "=ilike", name)],
                    limit=1,
                )
                if match:
                    return match

        return self.browse()
