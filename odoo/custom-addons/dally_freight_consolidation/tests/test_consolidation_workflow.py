# -*- coding: utf-8 -*-
"""Cycle de vie d'une consolidation aérienne.

Chaque transition métier a un chemin unique et interdit les sauts. Ces tests
mesurent le comportement observable, pas la structure interne du dictionnaire
de transitions — si demain la matrice change, seule la matrice bouge, ces
tests décrivent ce qui reste vrai pour l'opérateur.
"""

import re

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import ConsolidationCommon
from ..models.consolidation import _CONSOLIDATION_BYPASS_TOKEN, _CONSOLIDATION_STATE_WRITE_TOKEN


@tagged("post_install", "-at_install", "dally_freight")
class TestConsolidationLifecycle(ConsolidationCommon):

    def _route_existing_suffixes(self, origin, destination, year):
        """Return valid existing suffixes in one allocator namespace."""
        prefix = f"AIR-{origin}-{destination}-{year}-"
        records = self.env["dally.freight.consolidation"].with_context(
            active_test=False
        ).search([
            ("company_id", "=", self.env.company.id),
            ("name", "like", prefix + "%"),
        ])
        pattern = rf"AIR-{re.escape(origin)}-{re.escape(destination)}-{year}-(\d{{3}})"
        return [
            int(match.group(1))
            for name in records.mapped("name")
            if (match := re.fullmatch(pattern, name))
        ]

    def test_creation_automatique_de_la_reference(self):
        """Une consolidation créée sans nom reçoit une référence route + année."""
        consolidation = self.env["dally.freight.consolidation"].create({
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_city": "Paris",
            "destination_location": "CDG",
        })
        # Le format « AIR-DSS-CDG-YYYY-NNN » est stable dans le temps ; on ne
        # dépend pas d'une année précise pour ne pas casser en 2027.
        self.assertRegex(consolidation.name, r"^AIR-DSS-CDG-\d{4}-\d{3}$")

    def test_creation_batch_reserve_des_references_uniques(self):
        model = self.env["dally.freight.consolidation"]
        year = fields.Date.context_today(model).year
        prefix = f"AIR-DSS-CDG-{year}-"
        previous_max = max(self._route_existing_suffixes("DSS", "CDG", year), default=0)
        vals = [{
            "transport_mode": "air", "direction": "export",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
        } for _ in range(3)]
        records = self.env["dally.freight.consolidation"].create(vals)
        names = records.mapped("name")
        self.assertEqual(len(set(names)), 3)
        self.assertTrue(all(name.startswith(prefix) for name in names))
        suffixes = [int(name.rsplit("-", 1)[1]) for name in names]
        self.assertEqual(suffixes, list(range(previous_max + 1, previous_max + 4)))

    def test_creation_batch_routes_differentes_garde_les_sequences(self):
        model = self.env["dally.freight.consolidation"]
        year = fields.Date.context_today(model).year
        routes = (("DSS", "CDG"), ("CDG", "DSS"))
        previous = {
            route: max(self._route_existing_suffixes(*route, year), default=0)
            for route in routes
        }
        records = self.env["dally.freight.consolidation"].create([
            {"transport_mode": "air", "direction": "export", "origin_city": "Dakar", "origin_location": "DSS", "destination_city": "Paris", "destination_location": "CDG"},
            {"transport_mode": "air", "direction": "export", "origin_city": "Paris", "origin_location": "CDG", "destination_city": "Dakar", "destination_location": "DSS"},
        ])
        self.assertNotEqual(records[0].name, records[1].name)
        self.assertEqual(records[0].name.rsplit("-", 1)[0], f"AIR-DSS-CDG-{year}")
        self.assertEqual(records[1].name.rsplit("-", 1)[0], f"AIR-CDG-DSS-{year}")
        self.assertEqual(int(records[0].name.rsplit("-", 1)[1]), previous[("DSS", "CDG")] + 1)
        self.assertEqual(int(records[1].name.rsplit("-", 1)[1]), previous[("CDG", "DSS")] + 1)

    def test_route_oracle_includes_archived_current_company(self):
        model = self.env["dally.freight.consolidation"]
        year = fields.Date.context_today(model).year
        record = model.create({
            "name": f"AIR-XXX-YYY-{year}-987",
            "transport_mode": "air",
            "direction": "export",
            "origin_location": "XXX",
            "destination_location": "YYY",
            "active": False,
        })
        self.assertIn(987, self._route_existing_suffixes("XXX", "YYY", year))
        record.unlink()

    def test_route_oracle_ignores_other_company(self):
        model = self.env["dally.freight.consolidation"]
        year = fields.Date.context_today(model).year
        other_company = self.env["res.company"].create({
            "name": f"Oracle company {fields.Datetime.now()}"
        })
        model.with_company(other_company).create({
            "name": f"AIR-XXX-YYY-{year}-998",
            "company_id": other_company.id,
            "transport_mode": "air",
            "direction": "export",
            "origin_location": "XXX",
            "destination_location": "YYY",
        })
        self.assertNotIn(998, self._route_existing_suffixes("XXX", "YYY", year))

    def test_route_oracle_ignores_malformed_suffix(self):
        model = self.env["dally.freight.consolidation"]
        year = fields.Date.context_today(model).year
        model.create({
            "name": f"AIR-XXX-YYY-{year}-1000",
            "transport_mode": "air",
            "direction": "export",
            "origin_location": "XXX",
            "destination_location": "YYY",
        })
        self.assertEqual(self._route_existing_suffixes("XXX", "YYY", year), [])

    def test_ouvrir_puis_cloturer_la_collecte(self):
        consolidation = self._consolidation()
        consolidation.action_close_collection()
        self.assertEqual(consolidation.state, "collection_closed")
        self.assertTrue(consolidation.loading_closed_on)

    def test_transition_non_adjacente_est_refusee(self):
        consolidation = self._consolidation()
        with self.assertRaises(UserError):
            consolidation.write({"state": "departed"})

    def test_marquer_prete_sans_ligne_est_refuse(self):
        """Une consolidation vide ne peut pas être « prête au départ »."""
        consolidation = self._consolidation()
        consolidation.action_close_collection()
        with self.assertRaises(UserError):
            consolidation.action_mark_ready()

    def test_reouverture_collecte_exige_manager_et_raison(self):
        consolidation = self._consolidation()
        consolidation.action_close_collection()

        # Un logisticien ne peut pas rouvrir.
        with self.assertRaises(AccessError):
            consolidation.action_reopen_collection()

        # Un manager sans raison est refusé.
        self.env.user.group_ids += self.env.ref("dally_core.group_dally_manager")
        with self.assertRaises(UserError):
            consolidation.action_reopen_collection()

        consolidation.with_context(reopen_reason="MAWB déplacée").action_reopen_collection()
        self.assertEqual(consolidation.state, "collecting")
        self.assertFalse(consolidation.loading_closed_on)

    def test_creation_etat_terminal_est_refusee(self):
        with self.assertRaises(UserError):
            self.env["dally.freight.consolidation"].create({
                "transport_mode": "air", "direction": "export", "state": "departed",
            })

    def test_creation_prochain_depart_reinitialise_les_champs_operationnels(self):
        consolidation = self._consolidation()
        consolidation.write({
            "mawb_number": "297-99999999",
            "flight_number": "SN0207",
        })
        consolidation.with_context(_dally_consolidation_state_write=_CONSOLIDATION_STATE_WRITE_TOKEN, _dally_consolidation_bypass=_CONSOLIDATION_BYPASS_TOKEN).write({"state": "departed"})
        action = consolidation.action_create_next_departure()
        successor = self.env["dally.freight.consolidation"].browse(action["res_id"])
        self.assertNotEqual(successor.id, consolidation.id)
        self.assertEqual(successor.state, "collecting")
        self.assertFalse(successor.mawb_number)
        self.assertFalse(successor.flight_number)
        self.assertFalse(successor.line_ids)

    def test_ecart_manifeste_est_recompute_sans_toucher_aux_colis_client(self):
        consolidation = self._consolidation()
        shipment = self._shipment(reference="ECART-1")
        package = shipment.package_ids
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": package.id,
            "quantity_loaded": 2,
        })

        # 2 colis x 5 kg = 10 kg côté client. La MAWB rapporte 12 kg brut
        # dont 1.5 kg d'emballage maître. L'écart réconcilié doit être 0.5.
        consolidation.write({
            "master_gross_weight_kg": 12.0,
            "master_packaging_weight_kg": 1.5,
        })
        self.assertAlmostEqual(consolidation.client_weight_kg, 10.0, places=3)
        self.assertAlmostEqual(consolidation.manifest_mawb_difference_kg, 2.0, places=3)
        self.assertAlmostEqual(consolidation.reconciled_difference_kg, 0.5, places=3)

        # Les poids des colis clients n'ont jamais été touchés.
        self.assertAlmostEqual(package.total_weight_kg, 10.0, places=3)
