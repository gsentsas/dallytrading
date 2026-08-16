# -*- coding: utf-8 -*-
"""Capacité métier privée pour la décision client sur un devis.

Le groupe portail conserve une ACL strictement read-only sur
``dally.quote.request``. La seule écriture autorisée passe par la méthode privée
``_dally_portal_decide`` : Odoo interdit l'appel RPC des méthodes préfixées par
``_`` et la sentinelle de contexte utilisée ici ne peut pas être reconstruite
depuis du JSON.

``quoted`` ne suffit pas à rendre une demande décidable. Ce statut est posé dès
la création d'un ``sale.order`` encore en brouillon. Il faut aussi qu'au moins un
devis natif lié soit réellement en ``sent``.
"""

import re

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


PORTAL_QUOTE_DECISIONS = frozenset({"accept", "reject"})
PORTAL_REJECTION_REASON_MAX = 500
_UNSAFE_REASON = re.compile(r"[\x00-\x1f\x7f<>]")
_QUOTE_WRITE_CONTEXT_KEY = "_dally_portal_quote_decision_capability"
_QUOTE_WRITE_CAPABILITY = object()
_QUOTE_DECISION_WRITE_FIELDS = frozenset({
    "state",
    "customer_decision_at",
    "customer_decision_by_id",
    "customer_rejection_reason",
})


class PortalQuoteDecisionConflict(UserError):
    """La demande existe, mais sa machine d'état refuse cette décision."""


class DallyQuoteRequest(models.Model):
    _inherit = "dally.quote.request"

    customer_decision_at = fields.Datetime(
        string="Customer Decision At",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
        help="UTC timestamp of the decision made from the authenticated portal.",
    )
    customer_decision_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Customer Decision By",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
        tracking=True,
        help="Exact portal user who accepted or rejected the quotation.",
    )
    customer_rejection_reason = fields.Text(
        string="Customer Rejection Reason",
        readonly=True,
        copy=False,
        help="Optional plain-text reason. It is not part of the portal projection.",
    )

    def _dally_portal_can_decide(self):
        """Vrai uniquement pour une demande citée et un devis natif envoyé."""
        self.ensure_one()
        return (
            self.state == "quoted"
            and any(order.state == "sent" for order in self.sale_order_ids)
        )

    def _dally_portal_decide(self, decision, reason=None):
        """Applique atomiquement la décision du véritable utilisateur portail.

        Retourne ``True`` si une transition a été écrite et ``False`` pour la
        répétition idempotente de la même décision. Une décision opposée, un
        brouillon ou un devis annulé produisent tous un conflit métier.
        """
        self.ensure_one()
        user = self.env.user
        if not user.share or not user.has_group("base.group_portal"):
            raise AccessError(_("Portal quote decision denied."))

        # L'appartenance est redérivée par une recherche ORM sous l'utilisateur
        # réel. Un browse() forgé sur le dossier B ne devient jamais une capacité.
        visible = self.env["dally.quote.request"].search([
            ("id", "=", self.id),
        ], limit=1)
        if visible != self:
            raise AccessError(_("Portal quote decision denied."))

        decision, reason = self._dally_portal_normalize_decision(decision, reason)

        # Les tests et imports peuvent avoir des écritures non flushées. Le verrou
        # doit observer exactement les valeurs que l'ORM considère courantes.
        self.flush_recordset([
            "state", "customer_decision_at", "customer_decision_by_id",
            "customer_rejection_reason",
        ])
        self.env["sale.order"].flush_model(["dally_quote_request_id", "state"])

        # Deux onglets se sérialisent sur la même ligne. Après l'attente éventuelle,
        # READ COMMITTED voit le commit gagnant ; invalider le cache empêche une
        # ancienne valeur de ``state`` de contourner le contrôle.
        self.env.cr.execute(
            f'SELECT id FROM "{self._table}" WHERE id = %s FOR UPDATE',
            [self.id],
        )
        self.env.cr.execute(
            "SELECT id FROM sale_order "
            "WHERE dally_quote_request_id = %s ORDER BY id FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset([
            "state", "sale_order_ids", "customer_decision_at",
            "customer_decision_by_id", "customer_rejection_reason",
        ])
        orders = self.sale_order_ids
        orders.invalidate_recordset(["state"])

        final_decision = (
            "accept" if self.state == "won"
            else "reject" if self.state == "lost"
            else None
        )
        if final_decision:
            # Seules les décisions historiquement attribuées au portail sont
            # idempotentes. Un état won/lost posé par le staff sans audit client ne
            # doit pas être réétiqueté a posteriori.
            if self.customer_decision_at and final_decision == decision:
                return False
            raise PortalQuoteDecisionConflict(
                _("This quotation already has a final decision."),
            )

        if self.state != "quoted" or not any(
            order.state == "sent" for order in orders
        ):
            raise PortalQuoteDecisionConflict(
                _("This quotation is not available for a customer decision."),
            )

        values = {
            "state": "won" if decision == "accept" else "lost",
            "customer_decision_at": fields.Datetime.now(),
            "customer_decision_by_id": user.id,
            "customer_rejection_reason": reason if decision == "reject" else False,
        }
        protected = self.with_context(**{
            _QUOTE_WRITE_CONTEXT_KEY: _QUOTE_WRITE_CAPABILITY,
        })
        protected.write(values)
        return True

    @staticmethod
    def _dally_portal_normalize_decision(decision, reason):
        """Normalise une décision, et accepte son propre résultat en entrée.

        ## Pourquoi l'idempotence est une exigence, pas une élégance

        Cette fonction est appelée DEUX fois sur le même chemin : une fois par le
        contrôleur HTTP, puis une seconde fois par ``_dally_portal_decide``, qui
        revalide pour qu'un appelant non HTTP ne puisse pas contourner la
        frontière. Son résultat lui est donc repassé.

        Or elle renvoyait ``False`` pour « pas de motif », tout en refusant à
        l'entrée tout ``reason`` différent de ``None`` sur une acceptation. Le
        second passage voyait ``False``, qui n'est pas ``None``, et levait :
        **toute acceptation échouait en 400**, alors que le payload du client était
        exactement celui du contrat. Le rejet passait, lui, parce que son motif est
        une chaîne non vide, stable d'un passage à l'autre.

        La règle est donc exprimée sur la valeur NETTOYÉE : une acceptation ne peut
        pas porter de motif *substantiel*. ``None``, ``False`` et la chaîne vide
        décrivent tous l'absence de motif et sont acceptés indifféremment.

        Le contrat externe ne s'en trouve pas relâché : c'est le contrôleur qui
        refuse la seule présence de la clé ``reason`` sur une acceptation, et il
        renvoie 400 avant d'arriver ici — y compris pour ``"reason": ""``.
        """
        if not isinstance(decision, str) or decision not in PORTAL_QUOTE_DECISIONS:
            raise ValidationError(_("Unknown quote decision."))
        # `False` est la forme normalisée de « aucun motif » : c'est ce que cette
        # fonction produit, elle doit donc savoir le relire.
        if reason is None or reason is False:
            reason = ""
        if not isinstance(reason, str):
            raise ValidationError(_("The rejection reason must be text."))
        clean_reason = reason.strip()
        if decision == "accept" and clean_reason:
            raise ValidationError(_("An acceptance cannot carry a rejection reason."))
        if len(clean_reason) > PORTAL_REJECTION_REASON_MAX:
            raise ValidationError(_("The rejection reason is too long."))
        if _UNSAFE_REASON.search(clean_reason):
            raise ValidationError(
                _("The rejection reason contains unsupported characters."),
            )
        return decision, clean_reason or False

    def check_access(self, operation):
        """Ouvre uniquement l'écriture issue de la capacité privée exacte."""
        if operation == "write" and self.env.user.share:
            capability = self.env.context.get(_QUOTE_WRITE_CONTEXT_KEY)
            if (
                capability is _QUOTE_WRITE_CAPABILITY
                and len(self) == 1
                and self.env.user.has_group("base.group_portal")
            ):
                visible = self.env["dally.quote.request"].search([
                    ("id", "=", self.id),
                ], limit=1)
                if visible == self:
                    return None
        return super().check_access(operation)

    def write(self, values):
        """Refuse toute écriture portail hors de la transition encapsulée."""
        if self.env.user.share:
            capability = self.env.context.get(_QUOTE_WRITE_CONTEXT_KEY)
            if (
                capability is not _QUOTE_WRITE_CAPABILITY
                or len(self) != 1
                or set(values) != _QUOTE_DECISION_WRITE_FIELDS
            ):
                raise AccessError(_("Portal quote writes are restricted."))
        return super().write(values)
