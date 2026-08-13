# -*- coding: utf-8 -*-
"""Operation types, and the business rules attached to each — declared once.

## Why this file exists

DallyTrading does six different things that all look like "a deal". They are not
interchangeable:

- an **achat-revente** buys and resells, so it has a purchase side and a sale side;
- a **courtage** introduces a buyer to a seller and is paid a fee. It never buys
  anything, so forcing a ``purchase.order`` on it would invent a liability;
- a **commission** produces commission revenue and nothing else;
- a **distribution** buys and resells under an ongoing arrangement;
- an **import-export** buys and resells across a border, with logistics;
- a **représentation commerciale** acts for a principal and is paid for it.

The tempting implementation is a branch per type wherever behaviour differs. That
scatters the rules across the codebase, and the day a seventh type is added nobody can
enumerate what must change. So the rules live here, as data, and every model reads them
through :func:`operation_rules`.

## What a rule may and may not say

A rule states what a type *structurally requires* — a supplier, a customer, a principal,
whether a purchase order is meaningful, where revenue comes from. It says nothing about
amounts, rates, thresholds or currencies: those are commercial decisions and belong to
configuration or to the operator. There is deliberately no default commission rate and
no default margin here.
"""

from odoo import _

#: The six operation types, with their French labels.
#:
#: The technical keys are English and stable — they end up in the database, in API
#: payloads and in record rules. The labels are what an operator reads.
OPERATION_TYPES = [
    ("purchase_resale", "Achat-revente"),
    ("brokerage", "Courtage"),
    ("commission", "Commission"),
    ("distribution", "Distribution"),
    ("import_export", "Import-Export"),
    ("commercial_representation", "Représentation commerciale"),
]

OPERATION_TYPE_KEYS = tuple(key for key, _label in OPERATION_TYPES)

#: How revenue arises, per type. Determines which figures are meaningful at all.
#:
#: - ``trade_margin`` — DallyTrading buys and resells; revenue is sale minus purchase
#:   minus costs.
#: - ``commission`` — revenue is a commission on a transaction between two other
#:   parties. There is no purchase price to subtract.
#: - ``fee`` — revenue is a fee for a service rendered (an introduction, a mandate).
REVENUE_TRADE_MARGIN = "trade_margin"
REVENUE_COMMISSION = "commission"
REVENUE_FEE = "fee"

#: The rules themselves.
#:
#: ``requires_*`` is checked when the deal is structured, not on creation: an intake
#: form cannot know who the supplier will be.
_RULES = {
    "purchase_resale": {
        "revenue_model": REVENUE_TRADE_MARGIN,
        "requires_supplier": True,
        "requires_customer": True,
        "requires_principal": False,
        "has_purchase_side": True,
        "has_sale_side": True,
        "allows_purchase_order": True,
        "allows_sale_order": True,
        "allows_commission": False,
        "description": _(
            "DallyTrading buys the goods and resells them. It carries the purchase, "
            "so both sides are priced and both orders are meaningful."
        ),
    },
    "brokerage": {
        "revenue_model": REVENUE_FEE,
        "requires_supplier": True,
        "requires_customer": True,
        "requires_principal": False,
        "has_purchase_side": False,
        "has_sale_side": False,
        "allows_purchase_order": False,
        "allows_sale_order": True,
        "allows_commission": True,
        "description": _(
            "DallyTrading introduces a buyer to a seller and is paid a fee. It never "
            "takes ownership, so no purchase order is raised — one would record a "
            "liability DallyTrading does not have."
        ),
    },
    "commission": {
        "revenue_model": REVENUE_COMMISSION,
        "requires_supplier": False,
        "requires_customer": False,
        "requires_principal": True,
        "has_purchase_side": False,
        "has_sale_side": False,
        "allows_purchase_order": False,
        "allows_sale_order": True,
        "allows_commission": True,
        "description": _(
            "Revenue is a commission on a transaction between other parties. There is "
            "no purchase price, so there is no trade margin to compute."
        ),
    },
    "distribution": {
        "revenue_model": REVENUE_TRADE_MARGIN,
        "requires_supplier": True,
        "requires_customer": True,
        "requires_principal": False,
        "has_purchase_side": True,
        "has_sale_side": True,
        "allows_purchase_order": True,
        "allows_sale_order": True,
        "allows_commission": True,
        "description": _(
            "Buying and reselling under an ongoing arrangement with the supplier. "
            "Structurally an achat-revente; a commission may also be due."
        ),
    },
    "import_export": {
        "revenue_model": REVENUE_TRADE_MARGIN,
        "requires_supplier": True,
        "requires_customer": True,
        "requires_principal": False,
        "has_purchase_side": True,
        "has_sale_side": True,
        "allows_purchase_order": True,
        "allows_sale_order": True,
        "allows_commission": False,
        "description": _(
            "Buying and reselling across a border. The freight, customs and insurance "
            "belong to the cost lines, and the shipment itself to dally_freight."
        ),
    },
    "commercial_representation": {
        "revenue_model": REVENUE_COMMISSION,
        "requires_supplier": False,
        "requires_customer": True,
        "requires_principal": True,
        "has_purchase_side": False,
        "has_sale_side": False,
        "allows_purchase_order": False,
        "allows_sale_order": True,
        "allows_commission": True,
        "description": _(
            "DallyTrading acts for a principal in a territory and is paid for it. The "
            "principal is required; DallyTrading does not buy."
        ),
    },
}


def operation_rules(operation_type):
    """Return the rule set for ``operation_type``.

    Raises :class:`KeyError` for an unknown type rather than returning a default. A
    silent fallback would mean an unrecognised type quietly behaved like an
    achat-revente, which is exactly the class of bug this file exists to prevent.
    """
    return _RULES[operation_type]


def operation_rule(operation_type, rule):
    """Return one rule, or ``None`` when the type is not set yet.

    Used by computed fields, which run on records where ``operation_type`` may still
    be empty. Those must not raise.
    """
    if not operation_type:
        return None
    return _RULES[operation_type][rule]
