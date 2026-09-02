# -*- coding: utf-8 -*-
"""Regression coverage for immutable consolidation references."""

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import ConsolidationCommon


@tagged("post_install", "-at_install", "dally_freight")
class TestConsolidationReferenceImmutability(ConsolidationCommon):

    def _unlinked_consolidation(self):
        record = self.env["dally.freight.consolidation"].create({
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Dakar",
            "origin_location": "IMM",
            "destination_city": "Paris",
            "destination_location": "REF",
        })
        self.assertFalse(record.intake_shipment_ids)
        self.assertFalse(record.line_ids)
        return record

    def test_direct_placeholder_name_write_is_rejected_without_links(self):
        consolidation = self._unlinked_consolidation()
        original_name = consolidation.name

        with self.assertRaises(UserError):
            consolidation.write({"name": " Nouveau "})

        consolidation.invalidate_recordset(["name"])
        self.assertEqual(consolidation.name, original_name)

    def test_direct_valid_name_write_is_rejected_without_links(self):
        consolidation = self._unlinked_consolidation()
        original_name = consolidation.name

        with self.assertRaises(UserError):
            consolidation.write({"name": "AIR-IMM-REF-2099-999"})

        consolidation.invalidate_recordset(["name"])
        self.assertEqual(consolidation.name, original_name)
