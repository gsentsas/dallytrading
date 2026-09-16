# -*- coding: utf-8 -*-
"""Natural dossier ordering inside a consolidation."""

from .common import ConsolidationCommon


class TestConsolidationDossierOrder(ConsolidationCommon):

    def _shipment_with_local_ref(self, consolidation, sequence):
        local_ref = "A%03d" % sequence
        shipment = self.env["dally.shipment"]._create_with_intake_identity({
            "partner_id": self.business.id,
            "external_reference": "%s-%s" % (consolidation.name, local_ref),
            "transport_mode": "air",
            "direction": "export",
            "customer_segment_snapshot": "business",
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_city": "Paris",
            "destination_location": "CDG",
            "goods_description": "Test order",
            "intake_consolidation_id": consolidation.id,
            "planned_consolidation_id": consolidation.id,
            "collection_sequence": sequence,
            "collection_local_ref": local_ref,
        })
        package = self.env["dally.shipment.package"].create({
            "shipment_id": shipment.id,
            "external_line_key": "%s|A|1" % shipment.external_reference,
            "package_type": "parcel",
            "description": "Colis %s" % local_ref,
            "quantity": 1,
            "unit_weight_kg": 1.0,
            "unit_volume_cbm": 0.01,
        })
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": package.id,
            "quantity_loaded": 1,
        })
        return shipment

    def test_dossiers_and_manifest_are_sorted_by_local_number(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2026-ORDER")
        shipments = [
            self._shipment_with_local_ref(consolidation, 10),
            self._shipment_with_local_ref(consolidation, 2),
            self._shipment_with_local_ref(consolidation, 1),
        ]

        ordered_shipments = self.env["dally.shipment"].search(
            [("id", "in", [shipment.id for shipment in shipments])],
            order="dossier_sort_key asc, id asc",
        )
        self.assertEqual(
            ordered_shipments.mapped("collection_local_ref"),
            ["A001", "A002", "A010"],
        )

        ordered_lines = self.env["dally.freight.consolidation.line"].search([
            ("consolidation_id", "=", consolidation.id),
        ])
        self.assertEqual(
            ordered_lines.mapped("shipment_id.collection_local_ref"),
            ["A001", "A002", "A010"],
        )

        action = consolidation.action_view_shipments()
        ordered_view = self.env.ref(
            "dally_freight_consolidation.consolidation_shipment_view_list"
        )
        self.assertEqual(action["views"][0], (ordered_view.id, "list"))
        self.assertIn(
            'default_order="dossier_sort_key asc, id asc"',
            ordered_view.arch_db,
        )

        form_view = self.env.ref(
            "dally_freight_consolidation.consolidation_view_form"
        )
        self.assertIn(
            'default_order="shipment_dossier_sort_key asc, sequence asc, id asc"',
            form_view.arch_db,
        )
