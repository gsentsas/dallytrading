# -*- coding: utf-8 -*-
"""Prépare un dossier facturé pour l'E2E d'ajout tardif.

Le fixture réutilise le départ E2E aérien déjà présent. Il ne crée donc jamais
un départ supplémentaire dans la liste de réception. S'il existe déjà un
dossier fixture avec facture principale comptabilisée, il le réutilise.
"""

from uuid import uuid4

DEPART = "AIR-DSS-CDG-TEST-001"
MARQUEUR = "Pagne et parfum E2E tardif fixture"

if globals().get("env") is None:
    raise RuntimeError("À exécuter dans `odoo shell` sur la base de banc.")

operator = env["res.users"].sudo().search(
    [("login", "=", "gilles.banc")], limit=1)
assert operator, "Compte gilles.banc absent du banc"
company = operator.company_id

consolidation = env["dally.freight.consolidation"].sudo().search([
    ("name", "=", DEPART),
    ("company_id", "=", company.id),
], limit=1)
assert consolidation, f"Départ de banc absent : {DEPART}"
assert consolidation.active and consolidation.state == "collecting"
assert consolidation.transport_mode == "air"

package = env["dally.shipment.package"].sudo().search([
    ("description", "=", MARQUEUR),
    ("shipment_id.intake_consolidation_id", "=", consolidation.id),
], order="id desc", limit=1)
shipment = package.shipment_id if package else env["dally.shipment"]

if not shipment or not shipment.invoice_id or shipment.invoice_id.state != "posted":
    euro = env.ref("base.EUR")
    if not euro.active:
        euro.active = True

    family = env["dally.freight.tariff.family"].sudo().search(
        [("code", "=", "non_food")], limit=1)
    assert family, "Famille tarifaire non_food absente du banc"

    partner = env["res.partner"].sudo().search(
        [("name", "=", "Aissatou Kandji")], limit=1)
    assert partner, "Client Aissatou Kandji absent du banc"
    handle = env["dally.ops.customer.handle"].sudo().search([
        ("partner_id", "=", partner.id),
        ("company_id", "=", company.id),
    ], limit=1)
    if not handle:
        handle = env["dally.ops.customer.handle"].sudo().create({
            "partner_id": partner.id,
            "company_id": company.id,
        })

    result = (
        env["dally.ops.intake.service"]
        .with_user(operator)
        .with_company(company)
        .create_intake({
            "request_uuid": str(uuid4()),
            "consolidation_reference": DEPART,
            "customer_reference": handle.token,
            "received_on": "2026-08-29",
            "line": {
                "line_uuid": str(uuid4()),
                "package_type": "parcel",
                "goods_category": "Non alimentaire",
                "description": MARQUEUR,
                "quantity": 1,
                "announced_weight_kg": None,
                "exact_weight_kg": 3.55,
                "length_cm": None,
                "width_cm": None,
                "height_cm": None,
                "billing_method": "real",
                "tariff_family_code": family.code,
                "customs_value_xof": 25000,
            },
        })
    )
    reference = result["intake"]["reference"]
    shipment = env["dally.shipment"].sudo().search(
        [("external_reference", "=", reference)], limit=1)
    invoice = shipment.action_prepare_native_freight_invoice()
    invoice.action_post()
    env.cr.commit()
else:
    reference = shipment.external_reference

summary = (
    env["dally.ops.reconciliation.service"]
    .with_user(operator)
    .with_company(company)
    .summary_for(shipment)
)
assert "add_late_package" in summary["allowed_actions"]
assert round(summary["billing"]["primary_invoice_amount"], 2) == 17.75
print(f"OPS_E2E_LATE_REFERENCE={reference}")
