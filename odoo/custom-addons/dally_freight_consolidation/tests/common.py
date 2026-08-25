# -*- coding: utf-8 -*-
"""Fixtures partagées pour les tests de consolidation.

On garde un socle minimal :

- un client business et un client particulier ;
- un helper qui crée un dossier prêt à partir (colis, poids, désignation) ;
- un helper qui crée une consolidation aérienne « collecting » sur la
  route de référence (Dakar → Paris).

Les tests qui touchent au paiement héritent d'``AccountTestInvoicingCommon``
et créent leurs factures eux-mêmes ; ici on reste au niveau modèle.
"""

from odoo.tests import TransactionCase


class ConsolidationCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_logistics")

        cls.business = cls.env["res.partner"].create({
            "name": "Business Client",
            "company_type": "company",
            "email": "business@test.invalid",
        })
        cls.individual = cls.env["res.partner"].create({
            "name": "Individual Client",
            "company_type": "person",
            "email": "individual@test.invalid",
        })

    @classmethod
    def _shipment(cls, partner=None, reference="TST-SHP-1", segment="business"):
        partner = partner or cls.business
        shipment = cls.env["dally.shipment"].create({
            "partner_id": partner.id,
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
            "customer_segment_snapshot": segment,
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_city": "Paris",
            "destination_location": "CDG",
            "goods_description": "Café",
        })
        package_vals = {
            "shipment_id": shipment.id,
            "external_line_key": "%s|A|1" % reference,
            "package_type": "parcel",
            "description": "Café Touba 5kg",
            "quantity": 2,
            "unit_weight_kg": 5.0,
            "unit_volume_cbm": 0.02,
        }
        # dally_freight_billing ajoute une gate « tarification » sur le passage
        # à `ready`. Sans ces champs, chaque test devrait rejouer la tarification.
        # `real` + prix unitaire suffit à passer le contrôle sans exiger de
        # facture ni de devis lié.
        if "billing_method" in cls.env["dally.shipment.package"]._fields:
            package_vals["billing_method"] = "real"
            package_vals["applied_unit_price_eur"] = 5.0
        cls.env["dally.shipment.package"].create(package_vals)
        return shipment

    @classmethod
    def _consolidation(cls, name=None):
        return cls.env["dally.freight.consolidation"].create({
            "name": name or "AIR-DSS-CDG-2026-TEST",
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_city": "Paris",
            "destination_location": "CDG",
            "carrier_name": "Air Sénégal",
            "mawb_number": "297-12345678",
            "state": "collecting",
        })
