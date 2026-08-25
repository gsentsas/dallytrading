# -*- coding: utf-8 -*-
"""Tests de non-régression sur les findings CodeRabbit du 2026-08-25 (PR #6).

Chaque test cible un invariant que la revue a désigné comme faible. Ils sont
écrits en préalable à la correction, comme TDD : ils échouent sur le code
courant (avant patch) et doivent passer une fois la correction appliquée.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from unittest.mock import patch

from odoo.addons.dally_freight.tests.common import set_shipment_state

from .common import ConsolidationCommon


@tagged("post_install", "-at_install", "dally_freight")
class TestPartialDepartureRefused(ConsolidationCommon):
    """Finding #2 : un dossier ne devient jamais `departed` s'il reste des colis
    non chargés dans cette consolidation.

    On teste l'invariant au plus bas niveau — sur
    `_shipment_partial_departure_blockers` — pour ne pas mélanger avec la
    gate financière (couverte par `test_departure_gate.py`). Le test
    d'atomicité de `action_record_departure` reste bout-en-bout.
    """

    def test_colis_partiellement_charge_est_signale(self):
        """quantity=3 mais seulement 2 chargées → le blocker partial existe."""
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-PART-2SUR3")
        shipment = self._shipment(reference="PART-2SUR3")
        package = shipment.package_ids
        package.quantity = 3
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": package.id,
            "quantity_loaded": 2,
        })
        blockers = consolidation._shipment_partial_departure_blockers()
        self.assertTrue(blockers, "Un chargement partiel doit produire un blocker.")
        self.assertTrue(any("partiel" in b.lower() for b in blockers))

    def test_reliquat_sur_autre_consolidation_est_signale(self):
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-PART-SPLIT")
        shipment = self._shipment(reference="PART-SPLIT")
        package = shipment.package_ids
        # Deux consolidations actives se partagent le même colis.
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": package.id,
            "quantity_loaded": 1,
        })
        autre = self._consolidation(name="AIR-DSS-CDG-2026-PART-SPLIT-AUTRE")
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": autre.id,
            "package_id": package.id,
            "quantity_loaded": 1,
        })
        blockers = consolidation._shipment_partial_departure_blockers()
        self.assertTrue(blockers)
        self.assertTrue(any("consolidation" in b.lower() for b in blockers))

    def test_colis_absent_de_la_consolidation_est_signale(self):
        """Un colis d'un dossier partiellement rattaché à la consolidation.

        Le premier colis est chargé, le deuxième colis du même dossier ne
        l'est pas. Ce cas doit bloquer le départ du dossier.
        """
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-PART-MISSING")
        shipment = self._shipment(reference="PART-MISSING")
        package_a = shipment.package_ids
        package_b_vals = {
            "shipment_id": shipment.id,
            "external_line_key": "PART-MISSING|B|2",
            "package_type": "parcel",
            "description": "Second colis",
            "quantity": 1,
            "unit_weight_kg": 3.0,
        }
        if "billing_method" in self.env["dally.shipment.package"]._fields:
            package_b_vals.update({"billing_method": "real", "applied_unit_price_eur": 5.0})
        package_b = self.env["dally.shipment.package"].create(package_b_vals)
        # On ne charge que package_a.
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": package_a.id,
            "quantity_loaded": package_a.quantity,
        })
        blockers = consolidation._shipment_partial_departure_blockers()
        self.assertTrue(blockers, "Le second colis absent doit produire un blocker.")

    def test_tous_les_colis_charges_ne_produisent_aucun_blocker(self):
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-PART-FULL")
        shipment = self._shipment(reference="PART-FULL")
        package = shipment.package_ids
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": package.id,
            "quantity_loaded": package.quantity,
        })
        self.assertFalse(consolidation._shipment_partial_departure_blockers())

    def test_atomicite_du_depart_bloque_toute_la_consolidation(self):
        """Un seul dossier partiel doit empêcher l'ensemble de partir.

        On utilise `_write_historical_state` pour bypasser proprement la
        gate financière ; le test isole ici le comportement d'atomicité.
        """
        self.env.user.group_ids += self.env.ref("dally_core.group_dally_manager")
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-PART-ATOMIC")
        ok_shipment = self._shipment(reference="ATOMIC-OK")
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": ok_shipment.package_ids.id,
            "quantity_loaded": ok_shipment.package_ids.quantity,
        })
        ko_shipment = self._shipment(reference="ATOMIC-KO")
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": ko_shipment.package_ids.id,
            "quantity_loaded": 1,   # sur 2 → partiel
        })
        # Set state ready sur les deux dossiers via l'helper de setup —
        # évite la gate financière qui n'est pas ce qu'on teste ici.
        for shipment in (ok_shipment, ko_shipment):
            set_shipment_state(shipment, "ready")
        consolidation.action_close_collection()
        consolidation.action_mark_ready()

        with self.assertRaises(UserError):
            consolidation.action_record_departure()

        self.assertEqual(ok_shipment.state, "ready",
                         "Le dossier OK ne doit pas partir seul si un autre bloque.")
        self.assertEqual(ko_shipment.state, "ready")
        self.assertEqual(consolidation.state, "ready")


@tagged("post_install", "-at_install", "dally_freight")
class TestOperationalCompatibility(ConsolidationCommon):
    """Finding #3 : la ligne refuse tout couple incompatible société/mode/
    direction/route au niveau modèle, sans dépendre du wizard."""

    def _other_route_shipment(self, transport_mode="air", direction="export",
                              origin_city="Casablanca", origin_location="CMN",
                              destination_city="Paris", destination_location="CDG",
                              company_id=None, reference="INCOMPAT"):
        vals = {
            "partner_id": self.business.id,
            "external_reference": reference,
            "transport_mode": transport_mode,
            "direction": direction,
            "origin_city": origin_city,
            "origin_location": origin_location,
            "destination_city": destination_city,
            "destination_location": destination_location,
            "goods_description": "Café",
        }
        if company_id:
            vals["company_id"] = company_id
        shipment = self.env["dally.shipment"].create(vals)
        pkg = {
            "shipment_id": shipment.id,
            "external_line_key": "%s|A|1" % reference,
            "package_type": "parcel",
            "description": "Test",
            "quantity": 1,
            "unit_weight_kg": 5.0,
        }
        if "billing_method" in self.env["dally.shipment.package"]._fields:
            pkg["billing_method"] = "real"
            pkg["applied_unit_price_eur"] = 5.0
        self.env["dally.shipment.package"].create(pkg)
        return shipment

    def test_filtres_route_utilisent_les_champs_structures(self):
        arch = self.env.ref("dally_freight_consolidation.client_package_view_search").arch_db
        self.assertIn("shipment_id.origin_city", arch)
        self.assertIn("shipment_id.destination_city", arch)
        self.assertNotIn("route_summary','ilike','Dakar", arch)

    def test_autre_mode_refuse(self):
        consolidation = self._consolidation()
        shipment = self._other_route_shipment(transport_mode="sea", reference="MODE-KO")
        with self.assertRaises(UserError):
            self.env["dally.freight.consolidation.line"].create({
                "consolidation_id": consolidation.id,
                "package_id": shipment.package_ids.id,
                "quantity_loaded": 1,
            })

    def test_autre_direction_refuse(self):
        consolidation = self._consolidation()
        shipment = self._other_route_shipment(direction="import", reference="DIR-KO")
        with self.assertRaises(UserError):
            self.env["dally.freight.consolidation.line"].create({
                "consolidation_id": consolidation.id,
                "package_id": shipment.package_ids.id,
                "quantity_loaded": 1,
            })

    def test_autre_origine_refuse(self):
        consolidation = self._consolidation()
        shipment = self._other_route_shipment(
            origin_city="Casablanca", origin_location="CMN", reference="ORG-KO",
        )
        with self.assertRaises(UserError):
            self.env["dally.freight.consolidation.line"].create({
                "consolidation_id": consolidation.id,
                "package_id": shipment.package_ids.id,
                "quantity_loaded": 1,
            })

    def test_autre_destination_refuse(self):
        consolidation = self._consolidation()
        shipment = self._other_route_shipment(
            destination_city="Bruxelles", destination_location="BRU", reference="DST-KO",
        )
        with self.assertRaises(UserError):
            self.env["dally.freight.consolidation.line"].create({
                "consolidation_id": consolidation.id,
                "package_id": shipment.package_ids.id,
                "quantity_loaded": 1,
            })

    def test_cas_compatible_est_accepte(self):
        consolidation = self._consolidation()
        shipment = self._shipment(reference="COMPAT-OK")
        line = self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": shipment.package_ids.id,
            "quantity_loaded": 1,
        })
        self.assertTrue(line.id)

    def test_meme_ville_aeroports_differents_refuse(self):
        consolidation = self._consolidation()
        shipment = self._other_route_shipment(destination_city="Paris", destination_location="ORY", reference="ORY-KO")
        with self.assertRaises(UserError):
            self.env["dally.freight.consolidation.line"].create({
                "consolidation_id": consolidation.id, "package_id": shipment.package_ids.id,
                "quantity_loaded": 1,
            })



    def test_move_package_synchronise_shipment_id_et_ignore_payload_forge(self):
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-MOVE-SYNC")
        shipment_a = self._shipment(reference="MOVE-SYNC-A")
        shipment_b = self._shipment(reference="MOVE-SYNC-B")
        line = self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id, "package_id": shipment_a.package_ids.id,
            "quantity_loaded": 1,
        })
        line.write({"package_id": shipment_b.package_ids.id, "shipment_id": shipment_a.id})
        self.assertEqual(line.package_id, shipment_b.package_ids)
        self.assertEqual(line.shipment_id, shipment_b)

    def test_move_package_incompatible_reste_refuse(self):
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-MOVE-KO")
        shipment = self._shipment(reference="MOVE-KO-A")
        incompatible = self._other_route_shipment(destination_city="Lyon", destination_location="LYS", reference="MOVE-KO-B")
        line = self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id, "package_id": shipment.package_ids.id,
            "quantity_loaded": 1,
        })
        with self.assertRaises(UserError):
            line.write({"package_id": incompatible.package_ids.id})

    def test_maritime_sans_mawb_ni_vol_accepte(self):
        consolidation = self.env["dally.freight.consolidation"].create({
            "name": "SEA-DKR-MRS-2026-OK", "transport_mode": "sea", "direction": "export",
            "origin_city": "Dakar", "origin_location": "Port de Dakar",
            "destination_city": "Marseille", "destination_location": "FOS",
            "carrier_name": "MSC", "state": "collecting",
        })
        shipment = self._other_route_shipment(transport_mode="sea", origin_city="Dakar", origin_location="Port de Dakar", destination_city="Marseille", destination_location="FOS", reference="SEA-OK")
        line = self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id, "package_id": shipment.package_ids.id, "quantity_loaded": 1,
        })
        self.assertTrue(line.id)
        self.assertFalse(consolidation.mawb_number)
        self.assertFalse(consolidation.flight_number)

    def test_maritime_port_different_refuse(self):
        consolidation = self.env["dally.freight.consolidation"].create({
            "name": "SEA-DKR-MRS-2026-KO", "transport_mode": "sea", "direction": "export",
            "origin_city": "Dakar", "origin_location": "Port de Dakar",
            "destination_city": "Marseille", "destination_location": "FOS",
            "carrier_name": "MSC", "state": "collecting",
        })
        shipment = self._other_route_shipment(transport_mode="sea", origin_city="Dakar", origin_location="Port de Dakar", destination_city="Marseille", destination_location="MRS", reference="SEA-KO")
        with self.assertRaises(UserError):
            self.env["dally.freight.consolidation.line"].create({
                "consolidation_id": consolidation.id, "package_id": shipment.package_ids.id, "quantity_loaded": 1,
            })


@tagged("post_install", "-at_install", "dally_freight")
class TestLinesFrozenOutsideCollecting(ConsolidationCommon):
    """Finding #5 : create/write/unlink refusés dès que l'état sort de
    « collecting »."""

    def _line_at(self, name_suffix):
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-FROZEN-%s" % name_suffix)
        shipment = self._shipment(reference="FROZEN-%s" % name_suffix)
        line = self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": shipment.package_ids.id,
            "quantity_loaded": 1,
        })
        return consolidation, shipment, line

    def test_write_refuse_en_collection_closed(self):
        consolidation, _, line = self._line_at("CLOSED")
        consolidation.action_close_collection()
        with self.assertRaises(UserError):
            line.write({"quantity_loaded": 2})

    def test_unlink_refuse_en_collection_closed(self):
        consolidation, _, line = self._line_at("UNLINK")
        consolidation.action_close_collection()
        with self.assertRaises(UserError):
            line.unlink()

    def test_write_refuse_en_ready(self):
        consolidation, _, line = self._line_at("READY")
        consolidation.action_close_collection()
        consolidation.action_mark_ready()
        with self.assertRaises(UserError):
            line.write({"quantity_loaded": 2})

    def test_deplacement_vers_consolidation_hors_collecting_refuse(self):
        _consolidation_src, _shipment, line = self._line_at("MOVE-SRC")
        # Une consolidation cible existe, en `ready` — elle ne doit pas accepter
        # une ligne déplacée depuis une consolidation ouverte.
        cible = self._consolidation(name="AIR-DSS-CDG-2026-FROZEN-CIBLE-READY")
        other_shipment = self._shipment(reference="FROZEN-CIBLE-FILLER")
        # remplir un peu la cible pour pouvoir passer ready sans lignes vides.
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": cible.id,
            "package_id": other_shipment.package_ids.id,
            "quantity_loaded": 1,
        })
        cible.action_close_collection()
        cible.action_mark_ready()
        # Déplacement source→cible ; cible n'est plus en collecting.
        with self.assertRaises(UserError):
            line.write({"consolidation_id": cible.id})

    def test_reouverture_puis_modification_permise(self):
        consolidation, _, line = self._line_at("REOPEN")
        consolidation.action_close_collection()
        self.env.user.group_ids += self.env.ref("dally_core.group_dally_manager")
        consolidation.with_context(reopen_reason="Correction test").action_reopen_collection()
        # Après réouverture, l'écriture redevient possible.
        line.write({"quantity_loaded": 2})
        self.assertEqual(line.quantity_loaded, 2)


@tagged("post_install", "-at_install", "dally_freight")
class TestAddToConsolidationServerRecheck(ConsolidationCommon):
    """Finding #7 : action_confirm ne fait pas confiance au contexte RPC."""

    def test_context_force_ne_permet_pas_de_rattacher_a_une_incompatible(self):
        # Une consolidation légitime (DSS→CDG, air, export).
        good = self._consolidation(name="AIR-DSS-CDG-2026-WIZ-OK")
        # Une consolidation incompatible : mode maritime.
        bad = self.env["dally.freight.consolidation"].create({
            "name": "SEA-DKR-MRS-2026-WIZ-BAD",
            "transport_mode": "sea",
            "direction": "export",
            "origin_city": "Dakar",
            "destination_city": "Marseille",
            "carrier_name": "MSC",
            "state": "collecting",
        })
        shipment = self._shipment(reference="WIZ-FORGED")
        set_shipment_state(shipment, "goods_received")

        wizard = self.env["dally.add.to.consolidation.wizard"].with_context(
            compatible_consolidation_ids=[bad.id],
            default_shipment_id=shipment.id,
            default_consolidation_id=bad.id,
        ).create({
            "shipment_id": shipment.id,
            "consolidation_id": bad.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertFalse(self.env["dally.freight.consolidation.line"].search([
            ("consolidation_id", "=", bad.id),
        ]))

    def test_dossier_sans_colis_refuse_avec_message_metier(self):
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-WIZ-NO-PACKAGE")
        shipment = self.env["dally.shipment"].create({
            "partner_id": self.business.id,
            "external_reference": "WIZ-NO-PACKAGE",
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_city": "Paris", "destination_location": "CDG",
            "customer_segment_snapshot": "business",
        })
        set_shipment_state(shipment, "goods_received")
        wizard = self.env["dally.add.to.consolidation.wizard"].create({
            "shipment_id": shipment.id, "consolidation_id": consolidation.id,
        })
        with self.assertRaisesRegex(UserError, "aucun colis à charger"):
            wizard.action_confirm()
        self.assertFalse(self.env["dally.freight.consolidation.line"].search([
            ("shipment_id", "=", shipment.id),
        ]))

    def test_dossier_en_ready_refuse_par_le_wizard(self):
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-WIZ-READY")
        shipment = self._shipment(reference="WIZ-STATE-KO")
        set_shipment_state(shipment, "ready")
        wizard = self.env["dally.add.to.consolidation.wizard"].create({
            "shipment_id": shipment.id,
            "consolidation_id": consolidation.id,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_server_compatible_propage_les_exceptions_inattendues(self):
        shipment = self._shipment(reference="WIZ-EXC")
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-WIZ-EXC")
        wizard = self.env["dally.add.to.consolidation.wizard"].new({"shipment_id": shipment.id})
        with patch(
            "odoo.addons.dally_freight_consolidation.models.consolidation.DallyFreightConsolidationLine._check_operational_compatibility",
            side_effect=RuntimeError("unexpected"),
        ):
            with self.assertRaises(RuntimeError):
                wizard._server_compatible(shipment)

    def test_server_compatible_filtre_validation_et_user_error(self):
        shipment = self._shipment(reference="WIZ-EXPECTED")
        self._consolidation(name="AIR-DSS-CDG-2026-WIZ-EXPECTED")
        wizard = self.env["dally.add.to.consolidation.wizard"].new({"shipment_id": shipment.id})
        for error in (ValidationError("validation"), UserError("user")):
            with patch(
                "odoo.addons.dally_freight_consolidation.models.consolidation.DallyFreightConsolidationLine._check_operational_compatibility",
                side_effect=error,
            ):
                self.assertFalse(wizard._server_compatible(shipment))


@tagged("post_install", "-at_install", "dally_freight")
class TestBackfillFiltersRoute(ConsolidationCommon):
    """Finding #8 : la preview filtre aussi sur direction + origine + destination."""

    def test_dossier_meme_mode_autre_route_est_exclu(self):
        self.env.user.group_ids += self.env.ref("dally_core.group_dally_manager")
        historical = self.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-2026-BACKFILL-ROUTE",
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Dakar",
            "origin_location": "DSS",
            "destination_city": "Paris",
            "destination_location": "CDG",
            "carrier_name": "Air France",
            "mawb_number": "057-1",
            "state": "collecting",
        })
        # Dossier sur la même route : doit apparaître dans la preview.
        on_route = self._shipment(reference="ROUTE-ON")
        on_route.write({"goods_received_on": "2026-08-01"})
        # Dossier même société, même mode, MAIS route différente.
        other = self._other_shipment_air_other_route(reference="ROUTE-OFF")
        other.write({"goods_received_on": "2026-08-02"})

        wizard = self.env["dally.consolidation.backfill.wizard"].create({
            "consolidation_id": historical.id,
            "cutoff_date": "2026-08-25",
        })
        wizard.action_preview()

        candidates = wizard.candidate_line_ids.mapped("shipment_id")
        self.assertIn(on_route, candidates)
        self.assertNotIn(other, candidates,
                         "Un dossier hors route ne doit pas figurer dans la preview.")

    def test_meme_pays_autre_ville_est_exclu_et_dss_dakar_est_inclus(self):
        Senegal = self.env["res.country"].search([("code", "=", "SN")], limit=1)
        France = self.env["res.country"].search([("code", "=", "FR")], limit=1)
        historical = self.env["dally.freight.consolidation"].create({
            "name": "AIR-DSS-CDG-2026-BACKFILL-COUNTRY",
            "transport_mode": "air", "direction": "export",
            "origin_country_id": Senegal.id, "origin_city": "Dakar",
            "origin_location": "DSS", "destination_country_id": France.id,
            "destination_city": "Paris", "destination_location": "CDG",
            "state": "collecting",
        })
        on_route = self._shipment(reference="ROUTE-COUNTRY-ON")
        on_route.write({"origin_country_id": Senegal.id, "destination_country_id": France.id, "goods_received_on": "2026-08-01"})
        other = self._other_shipment_air_other_route(reference="ROUTE-COUNTRY-OFF")
        other.write({"origin_country_id": Senegal.id, "destination_country_id": France.id, "goods_received_on": "2026-08-02"})
        wizard = self.env["dally.consolidation.backfill.wizard"].create({"consolidation_id": historical.id, "cutoff_date": "2026-08-25"})
        wizard.action_preview()
        candidates = wizard.candidate_line_ids.mapped("shipment_id")
        self.assertIn(on_route, candidates)
        self.assertNotIn(other, candidates)

    def _other_shipment_air_other_route(self, reference):
        shipment = self.env["dally.shipment"].create({
            "partner_id": self.business.id,
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
            "origin_city": "Casablanca",
            "origin_location": "CMN",
            "destination_city": "Bruxelles",
            "destination_location": "BRU",
            "goods_description": "Test",
        })
        pkg = {
            "shipment_id": shipment.id,
            "external_line_key": "%s|A|1" % reference,
            "package_type": "parcel",
            "description": "Test",
            "quantity": 1,
            "unit_weight_kg": 5.0,
        }
        if "billing_method" in self.env["dally.shipment.package"]._fields:
            pkg["billing_method"] = "real"
            pkg["applied_unit_price_eur"] = 5.0
        self.env["dally.shipment.package"].create(pkg)
        return shipment


@tagged("post_install", "-at_install", "dally_freight")
class TestCancelAfterDeparture(ConsolidationCommon):
    """Finding #9 : action_cancel doit rester opérant post-départ (hors
    `delivered`)."""

    def _advance(self, shipment, target):
        """Bypass historique de setup — évite les gates opérationnelles
        (consolidation aérienne obligatoire, tarification, paiement…) qui
        ne concernent pas le comportement d'annulation testé ici."""
        set_shipment_state(shipment, target)

    def test_cancel_depuis_departed(self):
        shipment = self._shipment(reference="CANCEL-DEP")
        self._advance(shipment, "departed")
        shipment.action_cancel()
        self.assertEqual(shipment.state, "cancelled")

    def test_cancel_depuis_in_transit(self):
        shipment = self._shipment(reference="CANCEL-INT")
        self._advance(shipment, "in_transit")
        shipment.action_cancel()
        self.assertEqual(shipment.state, "cancelled")

    def test_cancel_depuis_arrived(self):
        shipment = self._shipment(reference="CANCEL-ARR")
        self._advance(shipment, "arrived")
        shipment.action_cancel()
        self.assertEqual(shipment.state, "cancelled")

    def test_cancel_depuis_out_for_delivery(self):
        shipment = self._shipment(reference="CANCEL-OFD")
        self._advance(shipment, "out_for_delivery")
        shipment.action_cancel()
        self.assertEqual(shipment.state, "cancelled")

    def test_cancel_depuis_delivered_refuse(self):
        shipment = self._shipment(reference="CANCEL-DEL")
        self._advance(shipment, "delivered")
        with self.assertRaises(UserError):
            shipment.action_cancel()


@tagged("post_install", "-at_install", "dally_freight")
class TestPaymentGateNotBypassable(ConsolidationCommon):
    """Finding #10 : la projection tk → Dally ne doit pas contourner le
    contrôle de paiement pour `departed`."""

    def test_operational_sync_ne_rouvre_pas_delivered(self):
        shipment = self._shipment(reference="OPSYNC-CLOSED-DEL")
        set_shipment_state(shipment, "delivered")
        with self.assertRaises(UserError):
            shipment._write_state_from_operational_source("in_transit")
        self.assertEqual(shipment.state, "delivered")

    def test_operational_sync_ne_rouvre_pas_cancelled(self):
        shipment = self._shipment(reference="OPSYNC-CLOSED-CAN")
        set_shipment_state(shipment, "cancelled")
        with self.assertRaises(UserError):
            shipment._write_state_from_operational_source("preparing")
        self.assertEqual(shipment.state, "cancelled")

    def test_write_state_from_operational_source_refuse_departed_sans_facture(self):
        """L'entrée privée du bridge doit re-vérifier la gate financière."""
        shipment = self._shipment(reference="OPSYNC-NOINV")
        # Aucune facture posée : la gate refuse le départ.
        with self.assertRaises(UserError):
            shipment._write_state_from_operational_source("departed")
        self.assertNotEqual(shipment.state, "departed")

    def test_write_state_from_operational_source_saut_non_adjacent_autorise(self):
        """L'objectif du bypass reste valide : la sync tk peut sauter des
        étapes intermédiaires, tant que la gate est satisfaite pour l'état
        cible. On sature ici toutes les préconditions de `ready`."""
        shipment = self._shipment(reference="OPSYNC-JUMP")
        # `ready` sur un dossier aérien exige une consolidation ouverte
        # compatible : on la rattache avant le saut.
        consolidation = self._consolidation(name="AIR-DSS-CDG-2026-OPSYNC-JUMP")
        self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": consolidation.id,
            "package_id": shipment.package_ids.id,
            "quantity_loaded": shipment.package_ids.quantity,
        })
        shipment._write_state_from_operational_source("ready")
        self.assertEqual(shipment.state, "ready")

    def test_write_historical_state_reste_un_bypass_complet(self):
        """Le chemin historique conserve son bypass complet (Manager only)."""
        shipment = self._shipment(reference="HIST-BYPASS")
        self.env.user.group_ids += self.env.ref("dally_core.group_dally_manager")
        shipment._write_historical_state("departed")
        self.assertEqual(shipment.state, "departed")
