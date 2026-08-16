# -*- coding: utf-8 -*-
"""Unique capacité d'écriture accordée à un utilisateur portail.

Odoo 19 donne nativement ``res.partner`` en lecture seule au groupe portail. Le
contrôleur de profil doit pourtant écrire sans ``sudo``. Ajouter seulement une ACL
``perm_write`` ouvrirait aussi ``/web/dataset/call_kw`` et toutes les méthodes
publiques du modèle.

La capacité ci-dessous ferme cette brèche : toute écriture exécutée par un
utilisateur ``share`` est refusée, sauf si elle provient de la méthode privée
``_dally_portal_update_profile``. Cette méthode ne peut pas être appelée par RPC
(les méthodes commençant par ``_`` sont privées pour Odoo) et pose dans le contexte
un objet sentinelle impossible à reconstruire depuis du JSON.
"""

import re

from odoo import _, models
from odoo.exceptions import AccessError, ValidationError


PORTAL_PROFILE_FIELDS = frozenset({
    "name", "phone", "street", "street2", "zip", "city",
})

_PROFILE_LIMITS = {
    "name": 120,
    "phone": 64,
    "street": 128,
    "street2": 128,
    "zip": 32,
    "city": 128,
}
_UNSAFE_TEXT = re.compile(r"[\x00-\x1f\x7f<>]")
_PHONE = re.compile(r"[0-9+(). /-]*\Z")
_PROFILE_WRITE_CONTEXT_KEY = "_dally_portal_profile_write_capability"
_PROFILE_WRITE_CAPABILITY = object()


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _dally_portal_update_profile(self, values):
        """Valide puis modifie uniquement le contact de l'utilisateur courant."""
        self.ensure_one()
        user = self.env.user
        if (
            not user.share
            or not user.has_group("base.group_portal")
            or self != user.partner_id
        ):
            raise AccessError(_("Portal profile update denied."))

        clean = self._dally_portal_normalize_profile(values)
        protected_partner = self.with_context(**{
            _PROFILE_WRITE_CONTEXT_KEY: _PROFILE_WRITE_CAPABILITY,
        })
        protected_partner.write(clean)
        return tuple(clean)

    def _dally_portal_normalize_profile(self, values):
        """Liste blanche et validation métier, indépendantes du contrôleur HTTP."""
        if not isinstance(values, dict) or not values:
            raise ValidationError(_("At least one profile field is required."))

        unknown = set(values) - PORTAL_PROFILE_FIELDS
        if unknown:
            raise ValidationError(_("Unknown profile field."))

        clean = {}
        for field, raw in values.items():
            if not isinstance(raw, str):
                raise ValidationError(_("Profile fields must be text."))
            value = raw.strip()
            if field == "name" and not value:
                raise ValidationError(_("Name cannot be empty."))
            if len(value) > _PROFILE_LIMITS[field]:
                raise ValidationError(_("Profile field is too long."))
            if _UNSAFE_TEXT.search(value):
                raise ValidationError(
                    _("Profile field contains unsupported characters.")
                )
            if field == "phone" and not _PHONE.fullmatch(value):
                raise ValidationError(
                    _("Phone number contains unsupported characters.")
                )
            clean[field] = value or False
        return clean

    def check_access(self, operation):
        """Ouvre uniquement le contrôle ORM de la capacité privée exacte."""
        if operation == "write" and self.env.user.share:
            capability = self.env.context.get(_PROFILE_WRITE_CONTEXT_KEY)
            if (
                capability is _PROFILE_WRITE_CAPABILITY
                and self == self.env.user.partner_id
            ):
                return None
        # L'ACL native de res.partner reste donc read-only pour tout appel
        # portail ordinaire, y compris les méthodes publiques appelées par RPC.
        return super().check_access(operation)

    def write(self, values):
        """Refuse toute écriture portail hors de la capacité privée ci-dessus."""
        if self.env.user.share:
            capability = self.env.context.get(_PROFILE_WRITE_CONTEXT_KEY)
            if capability is not _PROFILE_WRITE_CAPABILITY:
                raise AccessError(_("Portal partner writes are restricted."))
            if self != self.env.user.partner_id:
                raise AccessError(_("Portal partner writes are restricted."))
            if set(values) - PORTAL_PROFILE_FIELDS:
                raise AccessError(_("Portal partner writes are restricted."))
            # Several optional Odoo addons extend ``res.partner.write`` with
            # internal-only side effects (for example, searching pending
            # snailmail letters when an address changes). A portal user must
            # not gain access to those models. Invoke the ORM implementation
            # directly after the exact-capability check above: field conversion,
            # recomputations and constraints still run with the real portal user
            # and without sudo, while unrelated privileged hooks do not.
            return models.Model.write(self, values)
        return super().write(values)
