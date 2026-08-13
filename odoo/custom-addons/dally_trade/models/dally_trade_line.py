# -*- coding: utf-8 -*-
"""Trade lines — what is being traded, priced on each side separately.

## Why the two sides are separate fields, not one price and a margin

A trade line has a purchase price in one currency and a sale price in another. Storing
one price plus a margin percentage would force the second to be derived, and a derived
figure is a figure nobody decided. It would also make the currency ambiguous: a margin
of 20 % on a CNY purchase sold in EUR means nothing without a rate.

So both prices are stored, both are entered explicitly, and neither is computed from
the other. The purchase price carries ``groups=``: a commercial user can price a sale
without learning what it cost.

## Why ``product.product`` rather than a ``dally.trade.product``

Odoo's product catalogue already handles units, categories, taxes, purchase and sale
defaults, and it is what ``purchase.order.line`` and ``sale.order.line`` require. A
parallel product model would need all of that re-implemented, and would give two
answers to "what do we sell". The line therefore points at ``product.product``, and
carries a free-text description for the specification the catalogue does not hold.

A line may exist *without* a product: a deal is often described before it is mapped to
the catalogue. That is why the product is optional here and required only at
conversion, where an order line genuinely cannot exist without one.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

#: The purchase side is internal, consistently with the opportunity.
INTERNAL_GROUPS = "dally_trade.group_dally_trade_manager,dally_core.group_dally_finance"


class DallyTradeLine(models.Model):
    _name = "dally.trade.line"
    _description = "DallyTrading Trade Line"
    _order = "opportunity_id, sequence, id"

    opportunity_id = fields.Many2one(
        comodel_name="dally.trade.opportunity",
        string="Opération",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="opportunity_id.company_id", store=True, index=True, readonly=True,
    )
    sequence = fields.Integer(default=10)

    # ─── What ────────────────────────────────────────────────────────
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Produit",
        index=True,
        help="Optional while the deal is being described, required before an order "
             "can be raised: an order line needs a real product, and creating one "
             "automatically would fill the catalogue with near-duplicates nobody "
             "curated.",
    )
    description = fields.Char(
        string="Désignation",
        required=True,
        help="What is actually being traded. Kept even when a product is set: "
             "« panneaux solaires » and « monocristallin 400 W, garantie 10 ans » are "
             "not the same deal.",
    )
    specifications = fields.Text(string="Spécifications")

    quantity = fields.Float(
        string="Quantité", digits=(16, 3), required=True, default=1.0,
    )
    uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unité",
        help="Odoo's own unit of measure. Left empty on an order line so Odoo derives "
             "it from the product, which is its source of truth.",
    )

    # ─── Purchase side (internal) ────────────────────────────────────
    purchase_currency_id = fields.Many2one(
        related="opportunity_id.purchase_currency_id",
        string="Devise d'achat",
        readonly=True,
        groups=INTERNAL_GROUPS,
    )
    purchase_unit_price = fields.Monetary(
        string="Prix d'achat unitaire",
        currency_field="purchase_currency_id",
        groups=INTERNAL_GROUPS,
        help="Entered explicitly. Never derived from the sale price, and never "
             "defaulted: an invented purchase price makes every margin below it "
             "fiction.",
    )
    purchase_subtotal = fields.Monetary(
        string="Sous-total achat",
        currency_field="purchase_currency_id",
        compute="_compute_subtotals",
        store=True,
        groups=INTERNAL_GROUPS,
    )

    # ─── Sale side ───────────────────────────────────────────────────
    sale_currency_id = fields.Many2one(
        related="opportunity_id.sale_currency_id",
        string="Devise de vente",
        readonly=True,
    )
    sale_unit_price = fields.Monetary(
        string="Prix de vente unitaire",
        currency_field="sale_currency_id",
        help="Entered explicitly. There is no default margin applied to the purchase "
             "price: a price the company quotes must be one someone chose.",
    )
    sale_subtotal = fields.Monetary(
        string="Sous-total vente",
        currency_field="sale_currency_id",
        compute="_compute_subtotals",
        store=True,
    )

    notes = fields.Text(string="Notes", groups="dally_core.group_dally_readonly")

    # ─── Computes ────────────────────────────────────────────────────

    @api.depends("quantity", "purchase_unit_price", "sale_unit_price")
    def _compute_subtotals(self):
        """Plain multiplication, per side, with no conversion.

        Each subtotal stays in its own currency. Bringing them together is the
        opportunity's job, and only once a conversion has been declared.
        """
        for line in self:
            line.purchase_subtotal = line.quantity * line.purchase_unit_price
            line.sale_subtotal = line.quantity * line.sale_unit_price

    # ─── Validation ──────────────────────────────────────────────────

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(
                    _(
                        "La ligne « %s » doit porter une quantité strictement "
                        "positive.",
                        line.description or _("sans désignation"),
                    )
                )

    @api.constrains("purchase_unit_price", "sale_unit_price")
    def _check_prices_not_negative(self):
        for line in self:
            if line.purchase_unit_price < 0 or line.sale_unit_price < 0:
                raise ValidationError(
                    _(
                        "Les prix de la ligne « %s » ne peuvent pas être négatifs. Un "
                        "prix négatif est un avoir, pas une ligne de vente.",
                        line.description or _("sans désignation"),
                    )
                )

    @api.constrains("opportunity_id", "purchase_unit_price", "sale_unit_price")
    def _check_prices_match_operation_type(self):
        """Run the parent-side rule when a line itself is created or edited."""
        self.mapped("opportunity_id")._check_lines_match_operation_type()

    # ─── Conversion into order lines ─────────────────────────────────

    def _dally_order_line_blockers(self, side):
        """Return the reasons this line cannot become an order line on ``side``.

        An empty list means it can. Returning reasons rather than a boolean is what
        lets the opportunity tell the operator exactly what to supply, instead of
        refusing with a generic message they cannot act on.
        """
        self.ensure_one()
        blockers = []
        if not self.product_id:
            blockers.append(_("aucun produit catalogue"))
        if self.quantity <= 0:
            blockers.append(_("quantité nulle"))
        price = (
            self.purchase_unit_price if side == "purchase" else self.sale_unit_price
        )
        if price <= 0:
            blockers.append(
                _("prix d'achat nul") if side == "purchase"
                else _("prix de vente nul")
            )
        return blockers

    def _dally_line_description(self):
        """Description for the order line: the designation, plus the specification.

        The product name alone loses the specification, which is often the whole point
        of the deal.
        """
        self.ensure_one()
        parts = [self.description or self.product_id.display_name or _("Article")]
        if self.specifications:
            specification = " ".join(self.specifications.split())
            if len(specification) > 300:
                specification = specification[:300] + "…"
            parts.append(specification)
        return "\n".join(parts)

    def _dally_purchase_order_line_values(self):
        """Values for a ``purchase.order.line``.

        The unit of measure is deliberately omitted: Odoo derives it from the product,
        which is its own source of truth, and forcing a value here could contradict
        the product's purchase UoM.
        """
        self.ensure_one()
        return {
            "product_id": self.product_id.id,
            "name": self._dally_line_description(),
            "product_qty": self.quantity,
            "price_unit": self.purchase_unit_price,
        }

    def _dally_sale_order_line_values(self):
        """Values for a ``sale.order.line``. Same reasoning on the unit of measure."""
        self.ensure_one()
        return {
            "product_id": self.product_id.id,
            "name": self._dally_line_description(),
            "product_uom_qty": self.quantity,
            "price_unit": self.sale_unit_price,
        }
