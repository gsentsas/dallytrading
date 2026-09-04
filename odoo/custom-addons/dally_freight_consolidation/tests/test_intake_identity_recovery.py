# -*- coding: utf-8 -*-
"""Le retrait d'une identité de collecte annulée, et ses refus.

Le scénario reproduit exactement l'incident du 02/09/2026 : une collecte saisie
depuis Ops réserve ``A034`` dans la consolidation, elle est annulée, puis la
même référence papier est attribuée à un autre client dans le classeur. Le
classeur ne peut plus se synchroniser tant que l'identité n'est pas rendue.
"""

import ast
import pathlib
from unittest.mock import patch

import psycopg2

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_freight_consolidation.models.intake_identity_recovery import (
    ARCHIVE_SEQUENCE_OFFSET,
    _local_ref,
)
from odoo.addons.dally_freight_consolidation.models.shipment import (
    _INTAKE_IDENTITY_TOKEN,
    _PLANNED_RETIRE_TOKEN,
)


class RecoveryFixtures(TransactionCase):
    """Tous les tests de cette classe vivent dans la société courante.

    On n'hérite pas d'``AccountTestInvoicingCommon`` : il déplace la classe sur
    une société qu'il crée lui-même, laquelle ne porte aucun journal dans cette
    base — et le service de synchronisation, lui, travaille dans
    ``env.company``. Le mélange des deux sociétés faisait échouer les gardes
    financiers sur l'absence de journal, pas sur la règle testée.
    """


    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.company = cls.env.company
        cls.sync = cls.env["dally.freight.sync.service"]
        cls.recovery = cls.env["dally.freight.intake.identity.recovery"]
        cls.ops_client = cls.env["res.partner"].create({
            "name": "Client Ops Annulé", "company_type": "person",
            "email": "ops-cancelled@test.invalid",
        })
        cls.sheet_client = cls.env["res.partner"].create({
            "name": "Client Classeur Légitime", "company_type": "person",
            "email": "sheet-legit@test.invalid",
        })

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def _consolidation(self, name):
        return self.env["dally.freight.consolidation"].create({
            "name": name, "company_id": self.company.id,
            "transport_mode": "air", "direction": "export",
            "origin_country_id": self.env.ref("base.sn").id,
            "origin_city": "Dakar", "origin_location": "DSS",
            "destination_country_id": self.env.ref("base.fr").id,
            "destination_city": "Paris", "destination_location": "CDG",
            "state": "collecting",
        })

    def _payload(self, key, consolidation, local_ref, partner, source, external=None):
        values = {
            "sync_source_key": key,
            "source": source,
            "planned_consolidation_ref": consolidation.name,
            "collection_local_ref": local_ref,
            "transport_mode": "air",
            "direction": "export",
            "state": "goods_received",
            "client": {"name": partner.name, "email": partner.email},
            "origin": {"country_code": "SN", "city": "Dakar", "location": "DSS"},
            "destination": {"country_code": "FR", "city": "Paris", "location": "CDG"},
            "lines": [{
                "external_line_key": "%s|A|1" % key,
                "package_type": "parcel",
                "description": "Valise test",
                "goods_category": "Non alimentaire",
                "quantity": 1,
                "announced_weight_kg": 23.0,
                "exact_weight_kg": 23.0,
                "billing_method": "real",
                "tariff_family_code": "non_food",
                "customs_value_xof": 25000,
            }],
        }
        if external:
            values["external_reference"] = external
        return values

    def _cancelled_ops_dossier(self, consolidation, key, local_ref):
        """Une collecte Ops qui a réservé `local_ref`, puis a été annulée."""
        _result, shipment = self.sync.upsert(
            self._payload(key, consolidation, local_ref, self.ops_client, "backoffice")
        )
        # On laisse délibérément les colis chargés dans la consolidation : c'est
        # l'état réel de 842 et 843 en production, l'annulation d'un dossier ne
        # déchargeant pas ses lignes. Les décharger ici rendrait le test plus
        # facile que la réalité — et c'est ce qui avait masqué une assertion
        # trop stricte.
        self.assertTrue(shipment.consolidation_line_ids)
        shipment.message_post(body="Réception saisie au comptoir.", subtype_xmlid="mail.mt_note")
        shipment.action_cancel()
        self.assertEqual(shipment.state, "cancelled")
        return shipment

    def _expected(self, shipment, consolidation):
        """La meme empreinte que celle figee dans le script de maintenance.

        Un attendu plus pauvre que celui de production rendrait les tests plus
        indulgents que la realite : un champ absent de l'attendu n'est jamais
        confronte, et le test qui le modifie ne prouve rien.
        """
        return {shipment.id: {
            "company_id": self.company.id,
            "partner_id": shipment.partner_id.id,
            "sync_source": shipment.sync_source,
            "intake_consolidation_id": consolidation.id,
            "planned_consolidation_id": shipment.planned_consolidation_id.id,
            "external_reference": shipment.external_reference,
            "collection_local_ref": shipment.collection_local_ref,
            "collection_sequence": shipment.collection_sequence,
            "sync_source_key": shipment.sync_source_key,
            "loaded_lines": [
                {"line_id": ligne.id, "consolidation_id": ligne.consolidation_id.id,
                 "package_id": ligne.package_id.id,
                 "quantity_loaded": ligne.quantity_loaded,
                 "weight_loaded": ligne.weight_loaded,
                 "volume_loaded": ligne.volume_loaded}
                for ligne in shipment.consolidation_line_ids
            ],
            # Ces tests tournent en `at_install`, avant le chargement de
            # `dally_ops_mobile` : il n'y a alors aucune projection. La liste
            # vide est une affirmation, pas une omission.
            "outbox": [
                {"outbox_id": ligne["outbox_id"],
                 "projection_type": ligne["projection_type"],
                 "business_key": ligne["business_key"],
                 "state": ligne["state"],
                 "resource_reference": ligne["resource_reference"]}
                for ligne in self.recovery._inspect(shipment.id, {})["outbox"]
            ],
        }}

    def _archive_refs(self, shipment, consolidation):
        sequence = ARCHIVE_SEQUENCE_OFFSET + shipment.id
        local = _local_ref(sequence)
        return sequence, local, "%s-%s" % (consolidation.name, local)

    def _collection(self, shipment, key):
        return self.env["dally.freight.collection"].create({
            "external_payment_key": key,
            "shipment_id": shipment.id,
            "amount": 25000.0,
            "currency_id": self.env.ref("base.XOF").id,
            "payment_date": "2026-09-03",
            "source_method": "wave",
            "source": "google_sheets",
        })

    def _journal(self, kind):
        """Un journal du type demandé, sans présumer de la société.

        Ces deux gardes ont besoin de comptabilité, pas d'une société précise.
        On cherche d'abord dans la société du dossier, puis n'importe où : une
        base de test sans plan comptable installé n'a aucun journal, et il vaut
        mieux le dire que faire échouer un test sur une cause étrangère à la
        règle qu'il mesure.
        """
        Journal = self.env["account.journal"].sudo()
        journal = Journal.search(
            [("company_id", "=", self.company.id), ("type", "=", kind)], limit=1)
        if not journal:
            journal = Journal.search([("type", "=", kind)], limit=1)
        if not journal:
            self.skipTest("aucun journal %s : base de test sans comptabilité" % kind)
        return journal

    def _account_payment(self, shipment):
        journal = self._journal("bank")
        return self.env["account.payment"].sudo().create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": shipment.partner_id.id,
            "amount": 100.0,
            "journal_id": journal.id,
            "company_id": journal.company_id.id,
        })

    # ------------------------------------------------------------------
    # Le scénario nominal, joué sur les deux références de l'incident
    # ------------------------------------------------------------------

    def _scenario(self, consolidation_name, local_ref, ops_key, sheet_key):
        consolidation = self._consolidation(consolidation_name)
        ops = self._cancelled_ops_dossier(consolidation, ops_key, local_ref)
        ancienne_externe = ops.external_reference
        messages_avant = len(ops.message_ids)
        colis_avant = len(ops.package_ids)

        # Avant réparation : le classeur ne peut pas reprendre la référence.
        with self.assertRaises(ValidationError):
            self.sync.upsert(self._payload(
                sheet_key, consolidation, local_ref, self.sheet_client,
                "google_sheets", external=ancienne_externe,
            ))

        sequence, local, externe = self._archive_refs(ops, consolidation)
        rapport = self.recovery.simulate([ops.id], expected=self._expected(ops, consolidation))
        self.assertTrue(rapport["dry_run_pass"], rapport["blocking"])
        detail = rapport["shipments"][0]
        self.assertEqual(detail["archive"]["collection_sequence"], sequence)
        self.assertEqual(detail["archive"]["collection_local_ref"], local)
        self.assertEqual(detail["archive"]["external_reference"], externe)
        self.assertTrue(detail["archive"]["sequence_free"])
        self.assertTrue(detail["archive"]["local_ref_free"])
        self.assertTrue(detail["archive"]["external_reference_free"])

        # La simulation n'écrit rien.
        self.assertEqual(ops.external_reference, ancienne_externe)

        self.recovery._apply_authorized_recovery(
            [ops.id], expected=self._expected(ops, consolidation),
            database=self.env.cr.dbname,
        )

        # L'ancien dossier est conservé, seulement déplacé.
        self.assertTrue(ops.exists())
        self.assertEqual(ops.state, "cancelled")
        self.assertEqual(ops.sync_source_key, ops_key, "la clé source ne doit jamais être réécrite")
        self.assertEqual(ops.intake_consolidation_id, consolidation)
        self.assertEqual(ops.collection_local_ref, local)
        self.assertEqual(ops.collection_sequence, sequence)
        self.assertEqual(ops.external_reference, externe)
        self.assertEqual(len(ops.package_ids), colis_avant, "aucun colis ne doit disparaître")
        self.assertGreater(len(ops.message_ids), messages_avant, "la trace doit être ajoutée")
        self.assertTrue(
            any(ancienne_externe in (message.body or "") for message in ops.message_ids),
            "le chatter doit conserver l'ancienne identité",
        )
        self.assertFalse(ops.sale_order_id)
        self.assertFalse(ops.invoice_id)

        # Le classeur peut désormais créer sa propre collecte sur la référence.
        _result, sheet = self.sync.upsert(self._payload(
            sheet_key, consolidation, local_ref, self.sheet_client, "google_sheets",
        ))
        self.assertNotEqual(sheet.id, ops.id, "aucun recyclage du record annulé")
        self.assertEqual(sheet.collection_local_ref, local_ref)
        self.assertEqual(sheet.external_reference, "%s-%s" % (consolidation.name, local_ref))
        self.assertEqual(sheet.partner_id, self.sheet_client)
        self.assertEqual(sheet.sync_source_key, sheet_key)
        return ops, sheet


class TestIntakeIdentityRecovery(RecoveryFixtures):
    """Le retrait nominal et tous ses refus qui n'exigent pas de comptabilité."""

    def test_a034_identity_is_recovered_for_the_sheet(self):
        self._scenario(
            "AIR-DSS-CDG-2099-034", "A034",
            "ops:test-a034-owner", "sheets:test-a034-claimant",
        )

    def test_a035_identity_is_recovered_for_the_sheet(self):
        self._scenario(
            "AIR-DSS-CDG-2099-035", "A035",
            "ops:test-a035-owner", "sheets:test-a035-claimant",
        )

    # ------------------------------------------------------------------
    # Les refus
    # ------------------------------------------------------------------

    def test_a_live_dossier_is_never_retired(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-101")
        _result, vivant = self.sync.upsert(self._payload(
            "ops:test-live", consolidation, "A012", self.ops_client, "backoffice",
        ))
        self.assertNotEqual(vivant.state, "cancelled")

        rapport = self.recovery.simulate([vivant.id], expected=self._expected(vivant, consolidation))
        self.assertFalse(rapport["dry_run_pass"])
        self.assertTrue(any("annulé" in motif for motif in rapport["blocking"]))
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [vivant.id], expected=self._expected(vivant, consolidation),
                database=self.env.cr.dbname,
            )
        self.assertEqual(vivant.collection_local_ref, "A012")

    def test_a_dossier_carrying_a_collection_is_never_retired(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-102")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-money", "A013")
        self._collection(ops, "test-money|P|1")

        rapport = self.recovery.simulate([ops.id], expected=self._expected(ops, consolidation))
        self.assertFalse(rapport["dry_run_pass"])
        self.assertTrue(any("encaissement" in motif for motif in rapport["blocking"]))
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], expected=self._expected(ops, consolidation),
                database=self.env.cr.dbname,
            )
        self.assertEqual(ops.collection_local_ref, "A013")


    def test_a_dossier_carrying_a_sale_order_is_never_retired(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-103")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-order", "A014")
        # `sudo` : l'utilisateur de test porte les groupes Dally, pas ceux de
        # Ventes. Ce test porte sur le refus du retrait, pas sur les ACL Ventes.
        order = self.env["sale.order"].sudo().create({"partner_id": ops.partner_id.id})
        ops.sale_order_id = order.id

        rapport = self.recovery.simulate([ops.id], expected=self._expected(ops, consolidation))
        self.assertFalse(rapport["dry_run_pass"])
        self.assertTrue(any("devis" in motif.lower() for motif in rapport["blocking"]))
        self.assertEqual(ops.collection_local_ref, "A014")


    def test_a_taken_archive_identity_is_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-104")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-taken", "A015")
        _sequence, _local, externe = self._archive_refs(ops, consolidation)
        # Un dossier occupe déjà la référence globale d'archive visée.
        self.env["dally.shipment"].create({
            "partner_id": self.sheet_client.id,
            "external_reference": externe,
            "transport_mode": "air",
            "direction": "export",
        })

        rapport = self.recovery.simulate([ops.id], expected=self._expected(ops, consolidation))
        self.assertFalse(rapport["dry_run_pass"])
        self.assertFalse(rapport["shipments"][0]["archive"]["external_reference_free"])
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], expected=self._expected(ops, consolidation),
                database=self.env.cr.dbname,
            )
        self.assertEqual(ops.collection_local_ref, "A015")

    def test_a_taken_archive_sequence_is_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-111")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-sequence-taken", "A022")
        sequence, local, _externe = self._archive_refs(ops, consolidation)
        # Le modèle impose la cohérence séquence/référence locale : on ne peut
        # pas occuper l'une sans l'autre. L'occupant porte donc la référence
        # locale d'archive, et une référence globale volontairement différente
        # pour que ce soit bien la séquence — et non la globale — qui bloque.
        self.env["dally.shipment"].with_context(
            _dally_intake_identity_token=_INTAKE_IDENTITY_TOKEN,
        ).create({
            "partner_id": self.sheet_client.id,
            "company_id": self.company.id,
            "external_reference": "AIR-DSS-CDG-2099-111-SQUAT",
            "collection_local_ref": local,
            "collection_sequence": sequence,
            "intake_consolidation_id": consolidation.id,
            "transport_mode": "air",
            "direction": "export",
        })

        rapport = self.recovery.simulate([ops.id], expected=self._expected(ops, consolidation))
        self.assertFalse(rapport["dry_run_pass"])
        self.assertFalse(rapport["shipments"][0]["archive"]["sequence_free"])
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], expected=self._expected(ops, consolidation),
                database=self.env.cr.dbname,
            )
        self.assertEqual(ops.collection_local_ref, "A022")

    def test_a_diverging_expectation_aborts(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-105")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-diverge", "A016")
        attendu = self._expected(ops, consolidation)
        attendu[ops.id]["collection_local_ref"] = "A099"

        rapport = self.recovery.simulate([ops.id], expected=attendu)
        self.assertFalse(rapport["dry_run_pass"])
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery([ops.id], expected=attendu, database=self.env.cr.dbname)

    def test_a_wrong_database_name_aborts(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-106")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-db", "A017")
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], expected=self._expected(ops, consolidation),
                database="une-autre-base",
            )
        self.assertEqual(ops.collection_local_ref, "A017")

    def test_a_non_manager_cannot_apply(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-107")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-acl", "A018")
        # L'attente est calculée AVANT de retirer le groupe : sans le groupe
        # Manager, l'utilisateur ne peut plus même lire le dossier, et le test
        # échouerait sur la lecture au lieu de mesurer le refus.
        attendu = self._expected(ops, consolidation)
        self.env.user.group_ids -= self.env.ref("dally_core.group_dally_manager")
        with self.assertRaises(AccessError):
            self.recovery._apply_authorized_recovery([ops.id], expected=attendu, database=self.env.cr.dbname)
        self.assertEqual(ops.sudo().collection_local_ref, "A018")

    def test_loaded_packages_do_not_block_but_are_reported(self):
        """Le chargement est l'état normal d'une entrée annulée : il se rapporte.

        Le retrait ne touche ni `package_id` ni `quantity_loaded`. Bloquer
        là-dessus refuserait exactement les deux dossiers réels à réparer.
        """
        consolidation = self._consolidation("AIR-DSS-CDG-2099-112")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-loaded", "A023")
        charge = sum(ops.consolidation_line_ids.mapped("quantity_loaded"))
        self.assertGreater(charge, 0, "le colis doit rester chargé, comme en production")

        rapport = self.recovery.simulate([ops.id], expected=self._expected(ops, consolidation))

        self.assertTrue(rapport["dry_run_pass"], rapport["blocking"])
        self.assertEqual(rapport["shipments"][0]["loaded_quantity_total"], charge)

    def test_a_consolidation_no_longer_collecting_blocks_the_retirement(self):
        """Un manifeste imprimé ne doit pas perdre la référence qu'il porte."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-113")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-departed", "A024")
        # Par l'action métier : le statut d'une consolidation n'est pas
        # écrivable directement, et un test qui forcerait l'état mesurerait
        # autre chose que la réalité.
        consolidation.action_close_collection()
        self.assertNotEqual(consolidation.state, "collecting")

        rapport = self.recovery.simulate([ops.id], expected=self._expected(ops, consolidation))

        self.assertFalse(rapport["dry_run_pass"])
        self.assertTrue(any("collecte" in motif for motif in rapport["blocking"]))
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], expected=self._expected(ops, consolidation),
                database=self.env.cr.dbname,
            )
        self.assertEqual(ops.collection_local_ref, "A024")

    def test_intake_identity_stays_immutable_outside_the_service(self):
        """La réparation reste le seul chemin : l'ORM nu refuse toujours."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-108")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-immutable", "A019")
        with self.assertRaises(AccessError):
            ops.write({"collection_local_ref": "A900000", "collection_sequence": 900000})

    # ------------------------------------------------------------------
    # Le test qui compte : sortir de la composition du vrai départ
    # ------------------------------------------------------------------

    def test_the_retired_test_dossier_leaves_the_departure_composition(self):
        """Reproduit la production : un faux dossier pollue un départ vivant.

        Retirer la seule identité ne suffisait pas. Tant que le dossier annulé
        reste planifié et chargé, `_expected_shipments()` le réclame,
        `_departure_blockers()` exige qu'il soit « prête à partir » — ce qu'un
        dossier annulé ne sera jamais — et son poids compte dans le manifeste.
        """
        consolidation = self._consolidation("AIR-DSS-CDG-2099-300")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-manifeste", "A034")
        colis_avant = ops.package_ids
        poids_test = sum(ops.consolidation_line_ids.mapped("weight_loaded"))

        # Avant : le faux dossier fait partie du départ, et pèse dans le manifeste.
        self.assertIn(ops, consolidation._expected_shipments())
        self.assertEqual(ops.planned_consolidation_id, consolidation)
        self.assertGreater(poids_test, 0)
        self.assertAlmostEqual(consolidation.client_weight_kg, poids_test, places=3)
        self.assertTrue(
            any(ops.external_reference in (motif or "")
                for motif in consolidation._departure_blockers()),
            "le dossier annulé doit bloquer le départ avant réparation",
        )

        attendu = self._expected(ops, consolidation)
        rapport = self.recovery.simulate([ops.id], expected=attendu)
        detail = rapport["shipments"][0]
        self.assertTrue(rapport["dry_run_pass"], rapport["blocking"])
        self.assertEqual(
            sorted(detail["loaded_lines_to_remove"]),
            sorted(ops.consolidation_line_ids.ids),
        )
        self.assertEqual(detail["planned_consolidation_to_clear"]["id"], consolidation.id)
        self.assertEqual(detail["planned_consolidation_to_clear"]["state"], "collecting")
        # La simulation n'a rien touché.
        self.assertEqual(ops.planned_consolidation_id, consolidation)
        self.assertTrue(ops.consolidation_line_ids)

        self.recovery._apply_authorized_recovery([ops.id], expected=attendu, database=self.env.cr.dbname)

        consolidation.invalidate_recordset()
        # Le dossier survit, son historique aussi.
        self.assertTrue(ops.exists())
        self.assertEqual(ops.state, "cancelled")
        self.assertEqual(ops.package_ids, colis_avant, "les colis doivent rester")
        self.assertEqual(ops.intake_consolidation_id, consolidation,
                         "la consolidation d'entrée reste l'historique de réception")
        self.assertEqual(ops.sync_source_key, "ops:test-manifeste")

        # Mais il quitte la composition du départ.
        self.assertFalse(ops.consolidation_line_ids)
        self.assertFalse(ops.planned_consolidation_id)
        self.assertNotIn(ops, consolidation._expected_shipments())
        self.assertAlmostEqual(consolidation.client_weight_kg, 0.0, places=3)
        self.assertEqual(consolidation.client_package_count, 0)
        self.assertFalse(
            any(ops.external_reference in (motif or "")
                for motif in consolidation._departure_blockers()),
            "le dossier retiré ne doit plus bloquer le départ",
        )
        self.assertFalse(
            any("A034" in (motif or "") for motif in consolidation._departure_blockers()),
            "aucun blocage ne doit plus citer la référence libérée",
        )

        # Le vrai dossier du classeur peut alors prendre A034, seul.
        _result, vrai = self.sync.upsert(self._payload(
            "sheets:test-manifeste-vrai", consolidation, "A034",
            self.sheet_client, "google_sheets",
        ))
        consolidation.invalidate_recordset()
        self.assertNotEqual(vrai.id, ops.id)
        self.assertEqual(vrai.collection_local_ref, "A034")
        self.assertEqual(vrai.external_reference, "%s-A034" % consolidation.name)
        self.assertEqual(ops.collection_local_ref, _local_ref(ARCHIVE_SEQUENCE_OFFSET + ops.id))
        self.assertIn(vrai, consolidation._expected_shipments())
        self.assertNotIn(ops, consolidation._expected_shipments())
        # Aucun double comptage : seul le poids du vrai dossier reste.
        self.assertAlmostEqual(
            consolidation.client_weight_kg,
            sum(vrai.consolidation_line_ids.mapped("weight_loaded")), places=3)

    # ------------------------------------------------------------------
    # Le chemin privé de retrait du départ prévu
    # ------------------------------------------------------------------

    def test_clearing_the_planned_departure_is_refused_without_the_token(self):
        """Le comportement normal du modèle ne doit pas s'assouplir."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-301")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-jeton", "A040")
        ops.consolidation_line_ids.unlink()
        with self.assertRaises(ValidationError):
            ops.write({"planned_consolidation_id": False})
        self.assertEqual(ops.planned_consolidation_id, consolidation)

    def test_the_token_alone_does_not_authorise_a_live_dossier(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-302")
        _result, vivant = self.sync.upsert(self._payload(
            "ops:test-jeton-vivant", consolidation, "A041", self.ops_client, "backoffice",
        ))
        vivant.consolidation_line_ids.unlink()
        self.assertNotEqual(vivant.state, "cancelled")
        with self.assertRaises(ValidationError):
            vivant.with_context(
                _dally_planned_retire_token=_PLANNED_RETIRE_TOKEN
            ).write({"planned_consolidation_id": False})
        self.assertEqual(vivant.planned_consolidation_id, consolidation)

    def test_the_token_refuses_while_a_loading_line_remains(self):
        """Le plan ne se vide qu'après le chargement, jamais avant."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-303")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-jeton-charge", "A042")
        self.assertTrue(ops.consolidation_line_ids)
        with self.assertRaises(ValidationError):
            ops.with_context(
                _dally_planned_retire_token=_PLANNED_RETIRE_TOKEN
            ).write({"planned_consolidation_id": False})
        self.assertEqual(ops.planned_consolidation_id, consolidation)

    def test_the_token_refuses_a_dossier_carrying_money(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-304")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-jeton-argent", "A043")
        ops.consolidation_line_ids.unlink()
        self._collection(ops, "test-jeton-argent|P|1")
        with self.assertRaises(ValidationError):
            ops.with_context(
                _dally_planned_retire_token=_PLANNED_RETIRE_TOKEN
            ).write({"planned_consolidation_id": False})
        self.assertEqual(ops.planned_consolidation_id, consolidation)

    def test_the_token_refuses_when_the_departure_is_no_longer_collecting(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-305")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-jeton-ferme", "A044")
        ops.consolidation_line_ids.unlink()
        consolidation.action_close_collection()
        with self.assertRaises(ValidationError):
            ops.with_context(
                _dally_planned_retire_token=_PLANNED_RETIRE_TOKEN
            ).write({"planned_consolidation_id": False})
        self.assertEqual(ops.planned_consolidation_id, consolidation)

    def test_a_diverging_loaded_line_expectation_aborts(self):
        """Les lignes à retirer sont déclarées, pas découvertes."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-306")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-lignes", "A045")
        attendu = self._expected(ops, consolidation)
        attendu[ops.id]["loaded_line_ids"] = [999999]

        rapport = self.recovery.simulate([ops.id], expected=attendu)

        self.assertFalse(rapport["dry_run_pass"])
        self.assertTrue(any("chargement" in motif for motif in rapport["blocking"]))
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery([ops.id], expected=attendu, database=self.env.cr.dbname)
        self.assertTrue(ops.consolidation_line_ids)

    def test_a_diverging_planned_departure_expectation_aborts(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-307")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-plan", "A046")
        attendu = self._expected(ops, consolidation)
        attendu[ops.id]["planned_consolidation_id"] = 999999

        rapport = self.recovery.simulate([ops.id], expected=attendu)

        self.assertFalse(rapport["dry_run_pass"])
        self.assertTrue(any("Départ prévu" in motif for motif in rapport["blocking"]))
        self.assertEqual(ops.planned_consolidation_id, consolidation)

    # ------------------------------------------------------------------
    # L'empreinte de production : chaque champ audité doit correspondre
    # ------------------------------------------------------------------

    def _divergence_refusee(self, consolidation, ops, mutation, extrait):
        """Applique une divergence à l'attendu et exige un refus net."""
        attendu = self._expected(ops, consolidation)
        mutation(attendu[ops.id])
        rapport = self.recovery.simulate([ops.id], expected=attendu)
        self.assertFalse(rapport["dry_run_pass"], "la divergence devait bloquer")
        self.assertTrue(
            any(extrait in motif for motif in rapport["blocking"]),
            "motif attendu « %s », obtenu %s" % (extrait, rapport["blocking"]),
        )
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], attendu, self.env.cr.dbname)
        return attendu

    def test_a_diverging_partner_aborts(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-401")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-partner", "A050")
        self._divergence_refusee(
            consolidation, ops,
            lambda att: att.update({"partner_id": 999999}), "Client")
        self.assertEqual(ops.collection_local_ref, "A050")

    def test_a_diverging_sync_source_aborts(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-402")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-source", "A051")
        self._divergence_refusee(
            consolidation, ops,
            lambda att: att.update({"sync_source": "legacy_xlsx"}), "sync_source")
        self.assertEqual(ops.collection_local_ref, "A051")

    def test_a_line_with_the_right_id_but_the_wrong_package_aborts(self):
        """Un identifiant de ligne identique ne dit pas que le colis l'est."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-403")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-colis", "A052")
        ligne = ops.consolidation_line_ids[0]
        self._divergence_refusee(
            consolidation, ops,
            lambda att: att.update({"loaded_lines": [{
                "line_id": ligne.id, "consolidation_id": ligne.consolidation_id.id,
                "package_id": ligne.package_id.id + 100000,
                "quantity_loaded": ligne.quantity_loaded,
                "weight_loaded": ligne.weight_loaded,
                "volume_loaded": ligne.volume_loaded}]}),
            "colis")
        self.assertEqual(ops.collection_local_ref, "A052")

    def test_a_line_with_a_changed_weight_aborts(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-404")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-poids", "A053")
        ligne = ops.consolidation_line_ids[0]
        self._divergence_refusee(
            consolidation, ops,
            lambda att: att.update({"loaded_lines": [{
                "line_id": ligne.id, "consolidation_id": ligne.consolidation_id.id,
                "package_id": ligne.package_id.id,
                "quantity_loaded": ligne.quantity_loaded,
                "weight_loaded": ligne.weight_loaded + 5.0,
                "volume_loaded": ligne.volume_loaded}]}),
            "poids")
        self.assertEqual(ops.collection_local_ref, "A053")

    def test_a_line_with_a_changed_quantity_aborts(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-405")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-quantite", "A054")
        ligne = ops.consolidation_line_ids[0]
        self._divergence_refusee(
            consolidation, ops,
            lambda att: att.update({"loaded_lines": [{
                "line_id": ligne.id, "consolidation_id": ligne.consolidation_id.id,
                "package_id": ligne.package_id.id,
                "quantity_loaded": ligne.quantity_loaded + 7,
                "weight_loaded": ligne.weight_loaded,
                "volume_loaded": ligne.volume_loaded}]}),
            "quantité")
        self.assertEqual(ops.collection_local_ref, "A054")

    def test_a_weight_within_the_business_precision_is_accepted(self):
        """La comparaison ne doit pas se briser sur la représentation binaire."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-406")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-precision", "A055")
        ligne = ops.consolidation_line_ids[0]
        attendu = self._expected(ops, consolidation)
        attendu[ops.id]["loaded_lines"] = [{
            "line_id": ligne.id, "consolidation_id": ligne.consolidation_id.id,
            "package_id": ligne.package_id.id,
            "quantity_loaded": ligne.quantity_loaded,
            # Un écart très en dessous du gramme : la même marchandise.
            "weight_loaded": ligne.weight_loaded + 0.00001,
            "volume_loaded": ligne.volume_loaded,
        }]

        rapport = self.recovery.simulate([ops.id], expected=attendu)

        self.assertTrue(rapport["dry_run_pass"], rapport["blocking"])

    # ------------------------------------------------------------------
    # La surface mutante : privée, et sans complaisance
    # ------------------------------------------------------------------

    def test_the_mutating_entry_point_is_not_public(self):
        """Une maintenance ne doit pas offrir de second chemin public."""
        service = self.env["dally.freight.intake.identity.recovery"]
        self.assertFalse(hasattr(service, "apply"),
                         "aucune méthode `apply` publique ne doit subsister")
        self.assertTrue(hasattr(service, "_apply_authorized_recovery"))
        self.assertTrue(hasattr(service, "simulate"), "la simulation reste publique")

    def test_the_mutating_entry_point_refuses_missing_expectations(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-407")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-sans-attente", "A056")
        for attentes in ({}, None, {999999: {"company_id": self.company.id}}):
            with self.assertRaises(UserError):
                self.recovery._apply_authorized_recovery(
                    [ops.id], attentes, self.env.cr.dbname)
        self.assertEqual(ops.collection_local_ref, "A056")

    def test_the_mutating_entry_point_refuses_a_missing_database(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-408")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-sans-base", "A057")
        attendu = self._expected(ops, consolidation)
        for base in (None, "", "une-autre-base"):
            with self.assertRaises(UserError):
                self.recovery._apply_authorized_recovery([ops.id], attendu, base)
        self.assertEqual(ops.collection_local_ref, "A057")

    def test_the_final_revalidation_cannot_trust_a_stale_cache(self):
        """Le verrou ne vaut rien si la revalidation relit le cache d'avant.

        L'appelant simule presque toujours avant d'autoriser, et cette lecture
        peuple le cache ORM. On modifie donc la base en SQL brut — donc sans
        toucher au cache — entre la simulation et le retrait : si le service
        relisait le cache, il ne verrait rien et appliquerait sur un instantané
        périmé.
        """
        consolidation = self._consolidation("AIR-DSS-CDG-2099-411")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-cache", "A060")
        attendu = self._expected(ops, consolidation)

        # 1. La simulation passe, et peuple le cache.
        rapport = self.recovery.simulate([ops.id], expected=attendu)
        self.assertTrue(rapport["dry_run_pass"], rapport["blocking"])
        self.assertEqual(ops.partner_id, self.ops_client)

        # 2. La base bouge sous nos pieds, hors ORM : le cache garde l'ancien.
        self.env.cr.execute(
            "UPDATE dally_shipment SET partner_id = %s WHERE id = %s",
            (self.sheet_client.id, ops.id))
        self.assertEqual(ops.partner_id, self.ops_client,
                         "le cache doit encore porter l'ancienne valeur")

        # 2 bis. Le discriminant du test : la simulation, elle, se laisse
        # tromper par ce cache. C'est precisement pourquoi une simulation ne
        # vaut jamais autorisation — et cela prouve qu'au moment du retrait, le
        # cache EST perime. Sans cette assertion, le test passerait aussi bien
        # si le service ne relisait rien.
        self.assertTrue(
            self.recovery.simulate([ops.id], expected=attendu)["dry_run_pass"],
            "le cache doit encore tromper la simulation a ce stade",
        )

        # 3. Le retrait doit relire sous verrou, voir la divergence et refuser.
        with self.assertRaises(UserError) as capture:
            self.recovery._apply_authorized_recovery(
                [ops.id], attendu, self.env.cr.dbname)
        self.assertIn("Client", str(capture.exception))

        self.env.invalidate_all()
        self.assertEqual(ops.collection_local_ref, "A060")
        self.assertEqual(ops.planned_consolidation_id, consolidation)
        self.assertTrue(ops.consolidation_line_ids)

    def test_the_targets_are_locked_without_waiting(self):
        """Le verrou doit renoncer, pas attendre — et couvrir tout le périmètre.

        Une maintenance qui attend son tour reprend la main sur un état qu'elle
        n'a pas audité : ses assertions portent alors sur un instantané périmé.
        On vérifie donc la forme exacte des verrous pris.

        La contention réelle n'est pas simulable ici : `TransactionCase` ne
        committe jamais, et un second curseur ne voit pas le dossier — il ne
        peut donc pas entrer en conflit. Ce test contrôle les requêtes émises,
        le suivant contrôle la réaction au conflit.
        """
        consolidation = self._consolidation("AIR-DSS-CDG-2099-409")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-verrou", "A058")
        requetes = []
        vrai_execute = self.env.cr.execute

        def espion(query, params=None, *args, **kwargs):
            if "FOR UPDATE NOWAIT" in query:
                requetes.append((query, params))
            return vrai_execute(query, params, *args, **kwargs)

        with patch.object(self.env.cr, "execute", espion):
            self.recovery._verrouiller_cibles(
                [ops.id], self._expected(ops, consolidation))

        # Fragments explicites : « dally_freight_consolidation » seul serait
        # satisfait par la table des lignes, et le test ne prouverait rien.
        tables = [
            "FROM dally_shipment WHERE",
            "FROM dally_freight_consolidation WHERE",
            "FROM dally_freight_consolidation_line WHERE",
        ]
        if "dally.ops.sheet.outbox" in self.env:
            # Ces tests tournent en `at_install` pour ce module, donc avant le
            # chargement de `dally_ops_mobile` : la table des projections
            # n'existe pas encore et le service la saute a juste titre. Le
            # verrou correspondant est couvert cote `dally_ops_mobile`.
            tables.append("FROM dally_ops_sheet_outbox WHERE")
        jointes = " ".join(requete for requete, _params in requetes)
        for table in tables:
            self.assertIn(table, jointes, "le verrou doit couvrir %s" % table)
        self.assertEqual(len(requetes), len(tables),
                         "un verrou par table ciblee, ni plus ni moins")
        for requete, _params in requetes:
            self.assertIn("FOR UPDATE NOWAIT", requete)
            self.assertIn("ORDER BY id", requete,
                          "l'ordre fixe evite tout interblocage entre maintenances")

    def test_a_lock_conflict_aborts_and_mutates_nothing(self):
        """Un conflit de verrou doit devenir un refus lisible, pas une attente."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-410")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-conflit", "A059")
        attendu = self._expected(ops, consolidation)
        vrai_execute = self.env.cr.execute

        def espion_en_conflit(query, params=None, *args, **kwargs):
            if "FOR UPDATE NOWAIT" in query:
                raise psycopg2.errors.LockNotAvailable("conflit simule")
            return vrai_execute(query, params, *args, **kwargs)

        with patch.object(self.env.cr, "execute", espion_en_conflit):
            with self.assertRaises(UserError) as capture:
                self.recovery._apply_authorized_recovery(
                    [ops.id], attendu, self.env.cr.dbname)
        self.assertIn("autre transaction", str(capture.exception))

        self.env.invalidate_all()
        self.assertEqual(ops.collection_local_ref, "A059")
        self.assertEqual(ops.planned_consolidation_id, consolidation)
        self.assertTrue(ops.consolidation_line_ids)

    # ------------------------------------------------------------------
    # L'attente doit être complète, pas seulement présente
    # ------------------------------------------------------------------

    def _attente_creuse_refusee(self, ops, mutation, extrait):
        """Ampute l'attente d'un champ et exige un refus avant toute mutation."""
        attendu = self._expected(ops, ops.intake_consolidation_id)
        mutation(attendu[ops.id])
        with self.assertRaises(UserError) as capture:
            self.recovery._apply_authorized_recovery(
                [ops.id], attendu, self.env.cr.dbname)
        self.assertIn("incomplète", str(capture.exception))
        self.assertIn(extrait, str(capture.exception))
        # Rien n'a bougé : le refus précède le verrou et la mutation.
        self.env.invalidate_all()
        self.assertTrue(ops.consolidation_line_ids)
        self.assertTrue(ops.planned_consolidation_id)

    def test_an_empty_expectation_is_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-501")
        ops = self._cancelled_ops_dossier(consolidation, "ops:schema-vide", "A070")
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], {ops.id: {}}, self.env.cr.dbname)
        self.assertEqual(ops.collection_local_ref, "A070")

    def test_a_missing_partner_expectation_is_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-502")
        ops = self._cancelled_ops_dossier(consolidation, "ops:schema-partner", "A071")
        self._attente_creuse_refusee(
            ops, lambda att: att.pop("partner_id"), "partner_id")

    def test_a_missing_sync_source_expectation_is_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-503")
        ops = self._cancelled_ops_dossier(consolidation, "ops:schema-source", "A072")
        self._attente_creuse_refusee(
            ops, lambda att: att.pop("sync_source"), "sync_source")

    def test_a_missing_loaded_lines_expectation_is_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-504")
        ops = self._cancelled_ops_dossier(consolidation, "ops:schema-lignes", "A073")
        self._attente_creuse_refusee(
            ops, lambda att: att.pop("loaded_lines"), "loaded_lines")

    def test_a_missing_outbox_expectation_is_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-505")
        ops = self._cancelled_ops_dossier(consolidation, "ops:schema-outbox", "A074")
        self._attente_creuse_refusee(
            ops, lambda att: att.pop("outbox"), "outbox")

    def test_a_missing_planned_consolidation_expectation_is_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-506")
        ops = self._cancelled_ops_dossier(consolidation, "ops:schema-plan", "A075")
        self._attente_creuse_refusee(
            ops, lambda att: att.pop("planned_consolidation_id"),
            "planned_consolidation_id")

    def test_a_loaded_line_without_package_id_is_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-507")
        ops = self._cancelled_ops_dossier(consolidation, "ops:schema-colis", "A076")

        def amputer(attente):
            for ligne in attente["loaded_lines"]:
                ligne.pop("package_id")

        self._attente_creuse_refusee(ops, amputer, "package_id")

    def test_an_outbox_expectation_without_business_key_is_refused(self):
        """La clé métier identifie la projection : l'omettre la rend anonyme."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-508")
        ops = self._cancelled_ops_dossier(consolidation, "ops:schema-cle", "A077")
        attendu = self._expected(ops, consolidation)
        # `at_install` ne porte aucune projection : on en déclare une, amputée.
        attendu[ops.id]["outbox"] = [{
            "outbox_id": 1, "projection_type": "freight_dossier",
            "state": "pending", "resource_reference": "X",
        }]
        with self.assertRaises(UserError) as capture:
            self.recovery._apply_authorized_recovery(
                [ops.id], attendu, self.env.cr.dbname)
        self.assertIn("business_key", str(capture.exception))
        self.assertEqual(ops.collection_local_ref, "A077")

    def test_an_empty_list_is_a_valid_expectation(self):
        """Déclarer « aucune projection » doit rester possible et suffisant."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-509")
        ops = self._cancelled_ops_dossier(consolidation, "ops:schema-liste", "A078")
        attendu = self._expected(ops, consolidation)
        self.assertEqual(attendu[ops.id]["outbox"], [],
                         "aucune projection en at_install")

        rapport = self.recovery.simulate([ops.id], expected=attendu)

        self.assertTrue(rapport["dry_run_pass"], rapport["blocking"])
        self.recovery._apply_authorized_recovery(
            [ops.id], attendu, self.env.cr.dbname)
        self.assertFalse(ops.planned_consolidation_id)

    def test_a_line_loaded_on_another_departure_blocks_the_retirement(self):
        """Une vraie ligne sur un autre départ, pas une attente falsifiée.

        Un dossier peut porter des colis chargés sur plusieurs départs. Le
        retrait ne vise que le départ prévu : délester un autre manifeste
        ferait disparaître de la marchandise d'un départ qui la compte, sans
        que son exploitation ait rien demandé.
        """
        consolidation = self._consolidation("AIR-DSS-CDG-2099-601")
        autre = self._consolidation("AIR-DSS-CDG-2099-602")
        ops = self._cancelled_ops_dossier(consolidation, "ops:autre-depart", "A080")

        # Un second colis du MEME dossier, réellement chargé sur l'autre départ.
        colis = self.env["dally.shipment.package"].create({
            "shipment_id": ops.id,
            "external_line_key": "ops:autre-depart|A|2",
            "package_type": "parcel",
            "description": "Colis charge ailleurs",
            "goods_category": "Non alimentaire",
            "quantity": 1,
            "unit_weight_kg": 4.0,
            "billing_method": "real",
            "applied_unit_price_eur": 5.0,
        })
        ligne_ailleurs = self.env["dally.freight.consolidation.line"].create({
            "consolidation_id": autre.id,
            "package_id": colis.id,
            "quantity_loaded": 1,
        })
        self.assertEqual(ligne_ailleurs.shipment_id, ops)
        self.assertEqual(ligne_ailleurs.consolidation_id, autre)

        attendu = self._expected(ops, consolidation)
        rapport = self.recovery.simulate([ops.id], expected=attendu)

        self.assertFalse(rapport["dry_run_pass"])
        self.assertTrue(
            any("autre départ" in motif for motif in rapport["blocking"]),
            rapport["blocking"])
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], attendu, self.env.cr.dbname)

        # Les deux départs sont intacts.
        self.env.invalidate_all()
        self.assertTrue(ligne_ailleurs.exists())
        self.assertEqual(ligne_ailleurs.consolidation_id, autre)
        self.assertEqual(ops.collection_local_ref, "A080")
        self.assertEqual(ops.planned_consolidation_id, consolidation)
        self.assertEqual(len(ops.consolidation_line_ids), 2)

    def test_a_line_with_a_changed_volume_aborts(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-603")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-volume", "A081")
        ligne = ops.consolidation_line_ids[0]
        self._divergence_refusee(
            consolidation, ops,
            lambda att: att.update({"loaded_lines": [{
                "line_id": ligne.id, "consolidation_id": ligne.consolidation_id.id,
                "package_id": ligne.package_id.id,
                "quantity_loaded": ligne.quantity_loaded,
                "weight_loaded": ligne.weight_loaded,
                "volume_loaded": ligne.volume_loaded + 0.5}]}),
            "volume")
        self.assertEqual(ops.collection_local_ref, "A081")

    def test_a_falsified_consolidation_in_the_expectation_aborts(self):
        """L'empreinte compare aussi le départ de chaque ligne."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-604")
        autre = self._consolidation("AIR-DSS-CDG-2099-605")
        ops = self._cancelled_ops_dossier(consolidation, "ops:faux-depart", "A082")
        ligne = ops.consolidation_line_ids[0]
        self._divergence_refusee(
            consolidation, ops,
            lambda att: att.update({"loaded_lines": [{
                "line_id": ligne.id, "consolidation_id": autre.id,
                "package_id": ligne.package_id.id,
                "quantity_loaded": ligne.quantity_loaded,
                "weight_loaded": ligne.weight_loaded,
                "volume_loaded": ligne.volume_loaded}]}),
            "départ")
        self.assertEqual(ops.collection_local_ref, "A082")

    def test_a_wildcard_none_is_not_a_valid_expectation(self):
        """`None` ne doit jamais valoir « n'importe quelle valeur »."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-606")
        ops = self._cancelled_ops_dossier(consolidation, "ops:jokers", "A083")
        ligne = ops.consolidation_line_ids[0]
        for champ in ("consolidation_id", "package_id", "quantity_loaded",
                      "weight_loaded", "volume_loaded"):
            with self.subTest(champ=champ):
                attendu = self._expected(ops, consolidation)
                attendu[ops.id]["loaded_lines"][0][champ] = None
                with self.assertRaises(UserError) as capture:
                    self.recovery._apply_authorized_recovery(
                        [ops.id], attendu, self.env.cr.dbname)
                self.assertIn(champ, str(capture.exception))
        self.assertEqual(ops.collection_local_ref, "A083")
        self.assertEqual(ligne.consolidation_id, consolidation)

    def test_duplicate_ids_in_the_expectation_are_refused(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-607")
        ops = self._cancelled_ops_dossier(consolidation, "ops:doublons", "A084")
        attendu = self._expected(ops, consolidation)
        attendu[ops.id]["loaded_lines"] = (
            attendu[ops.id]["loaded_lines"] + attendu[ops.id]["loaded_lines"])
        with self.assertRaises(UserError) as capture:
            self.recovery._apply_authorized_recovery(
                [ops.id], attendu, self.env.cr.dbname)
        self.assertIn("double", str(capture.exception))

        attendu2 = self._expected(ops, consolidation)
        projection = {
            "outbox_id": 7, "projection_type": "freight_dossier",
            "business_key": "ops:doublons", "state": "pending",
            "resource_reference": "X",
        }
        attendu2[ops.id]["outbox"] = [projection, dict(projection)]
        with self.assertRaises(UserError) as capture:
            self.recovery._apply_authorized_recovery(
                [ops.id], attendu2, self.env.cr.dbname)
        self.assertIn("double", str(capture.exception))
        self.assertEqual(ops.collection_local_ref, "A084")

    def test_the_package_advisory_locks_are_pre_acquired_without_waiting(self):
        """`unlink` prendra un verrou colis BLOQUANT : on le prend d'avance.

        Sans cette pré-acquisition, le retrait détiendrait ses verrous de
        lignes puis attendrait le verrou colis. Une transaction qui tiendrait
        ce verrou et attendrait nos lignes formerait un cycle — interblocage,
        ou au mieux une attente qui contredit le contrat NOWAIT.
        """
        consolidation = self._consolidation("AIR-DSS-CDG-2099-701")
        ops = self._cancelled_ops_dossier(consolidation, "ops:verrou-colis", "A090")
        attendu = self._expected(ops, consolidation)
        colis_attendus = sorted(
            ligne["package_id"] for ligne in attendu[ops.id]["loaded_lines"])
        self.assertTrue(colis_attendus)
        requetes = []
        vrai_execute = self.env.cr.execute

        def espion(query, params=None, *args, **kwargs):
            if "advisory" in query:
                requetes.append((query, list(params or [])))
            return vrai_execute(query, params, *args, **kwargs)

        with patch.object(self.env.cr, "execute", espion):
            self.recovery._verrouiller_cibles([ops.id], attendu)

        self.assertEqual(len(requetes), len(colis_attendus))
        for requete, _params in requetes:
            self.assertIn("pg_try_advisory_xact_lock", requete)
            self.assertNotIn("pg_advisory_xact_lock(", requete,
                             "le garde ne doit jamais prendre un verrou bloquant")
        cles = [params[0] for _requete, params in requetes]
        self.assertEqual(
            cles,
            ["consolidation-package:%s" % identifiant for identifiant in colis_attendus],
            "memes cles que _lock_package, et ids tries",
        )

    def test_a_package_advisory_conflict_aborts_and_mutates_nothing(self):
        """Un colis deja verrouille ailleurs : on renonce, on n'attend pas."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-702")
        ops = self._cancelled_ops_dossier(consolidation, "ops:colis-occupe", "A091")
        attendu = self._expected(ops, consolidation)
        lignes_avant = {
            ligne.id: (ligne.package_id.id, ligne.quantity_loaded)
            for ligne in ops.consolidation_line_ids
        }
        vrai_execute = self.env.cr.execute
        vrai_fetchone = self.env.cr.fetchone
        etat = {"try_lock": False}

        def espion(query, params=None, *args, **kwargs):
            etat["try_lock"] = "pg_try_advisory_xact_lock" in query
            return vrai_execute(query, params, *args, **kwargs)

        def fetchone_force():
            # Le SQL est reellement execute ; seul le verdict est force, pour
            # reproduire un colis deja tenu par une autre transaction.
            if etat["try_lock"]:
                etat["try_lock"] = False
                return (False,)
            return vrai_fetchone()

        with patch.object(self.env.cr, "execute", espion), \
                patch.object(self.env.cr, "fetchone", fetchone_force):
            with self.assertRaises(UserError) as capture:
                self.recovery._apply_authorized_recovery(
                    [ops.id], attendu, self.env.cr.dbname)
        self.assertIn("autre transaction", str(capture.exception))

        self.env.invalidate_all()
        self.assertEqual(ops.collection_local_ref, "A091")
        self.assertEqual(ops.planned_consolidation_id, consolidation)
        self.assertEqual(
            {ligne.id: (ligne.package_id.id, ligne.quantity_loaded)
             for ligne in ops.consolidation_line_ids},
            lignes_avant,
        )

    def test_unlink_still_works_after_the_lock_is_pre_acquired(self):
        """Le nominal doit rester nominal : re-prendre un verrou detenu est immediat."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-703")
        ops = self._cancelled_ops_dossier(consolidation, "ops:colis-nominal", "A092")
        attendu = self._expected(ops, consolidation)

        self.recovery._apply_authorized_recovery(
            [ops.id], attendu, self.env.cr.dbname)

        self.env.invalidate_all()
        self.assertFalse(ops.consolidation_line_ids, "le dechargement doit avoir eu lieu")
        self.assertFalse(ops.planned_consolidation_id)
        self.assertEqual(
            ops.collection_local_ref, _local_ref(ARCHIVE_SEQUENCE_OFFSET + ops.id))
        self.assertTrue(ops.package_ids, "les colis restent")

    # ------------------------------------------------------------------
    # L'ordre des etapes, sous REPEATABLE READ
    # ------------------------------------------------------------------

    def test_the_locks_come_before_any_other_business_read(self):
        """Le premier acces metier fige le snapshot : ce doit etre le verrou.

        Odoo travaille en REPEATABLE READ. Le snapshot PostgreSQL est fige au
        premier acces de la transaction ; si c'etait la lecture d'habilitation,
        tout ce qui suit serait relu dans un snapshot pris AVANT nos verrous.
        """
        consolidation = self._consolidation("AIR-DSS-CDG-2099-801")
        ops = self._cancelled_ops_dossier(consolidation, "ops:ordre", "A100")
        attendu = self._expected(ops, consolidation)
        journal = []
        Service = type(self.recovery)
        Env = type(self.env)
        vrais = {
            "verrous": Service._verrouiller_cibles,
            "colis": Service._pre_acquerir_verrous_colis,
            "manager": Service._exiger_manager,
            "revalidation": Service.simulate,
            "invalidation": Env.invalidate_all,
        }

        def tracer(nom, vrai, sur_env=False):
            def enveloppe(*args, **kwargs):
                journal.append(nom)
                return vrai(*args, **kwargs)
            return enveloppe

        with patch.object(Service, "_verrouiller_cibles",
                          tracer("verrous", vrais["verrous"])), \
             patch.object(Service, "_pre_acquerir_verrous_colis",
                          tracer("colis", vrais["colis"])), \
             patch.object(Service, "_exiger_manager",
                          tracer("manager", vrais["manager"])), \
             patch.object(Service, "simulate",
                          tracer("revalidation", vrais["revalidation"])), \
             patch.object(Env, "invalidate_all",
                          tracer("invalidation", vrais["invalidation"])):
            self.recovery._apply_authorized_recovery(
                [ops.id], attendu, self.env.cr.dbname)

        # `_verrouiller_cibles` appelle lui-meme la pre-acquisition des colis.
        self.assertEqual(journal[0], "verrous",
                         "le verrouillage doit etre la premiere etape")
        self.assertLess(journal.index("colis"), journal.index("invalidation"))
        self.assertLess(journal.index("invalidation"), journal.index("manager"),
                        "l'invalidation precede toute relecture")
        self.assertLess(journal.index("manager"), journal.index("revalidation"),
                        "l'habilitation precede la revalidation et les mutations")
        self.assertLess(journal.index("colis"), journal.index("revalidation"),
                        "les verrous colis precedent la revalidation")

    def test_a_non_manager_cannot_mutate_even_after_taking_locks(self):
        """Le risque concede est borne : des verrous, jamais une mutation."""
        consolidation = self._consolidation("AIR-DSS-CDG-2099-802")
        ops = self._cancelled_ops_dossier(consolidation, "ops:ordre-acl", "A101")
        attendu = self._expected(ops, consolidation)
        self.env.user.group_ids -= self.env.ref("dally_core.group_dally_manager")

        with self.assertRaises(AccessError):
            self.recovery._apply_authorized_recovery(
                [ops.id], attendu, self.env.cr.dbname)

        self.env.invalidate_all()
        dossier = ops.sudo()
        self.assertEqual(dossier.collection_local_ref, "A101")
        self.assertTrue(dossier.planned_consolidation_id)
        self.assertTrue(dossier.consolidation_line_ids)

    def test_the_maintenance_script_discards_the_dry_run_transaction(self):
        """Le script ne doit jamais appliquer dans la transaction du dry-run.

        Sous REPEATABLE READ, `invalidate_all()` vide le cache ORM mais relit
        le meme snapshot PostgreSQL. Seul un `rollback()` en ouvre un neuf.
        On lit donc l'ordre reel des appels dans le source du script.
        """
        chemin = pathlib.Path(__file__).resolve().parent.parent / "scripts" / (
            "retire_cancelled_intake_identity.py")
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        principal = next(
            noeud for noeud in arbre.body
            if isinstance(noeud, ast.FunctionDef) and noeud.name == "principal")

        appels = []
        for noeud in ast.walk(principal):
            if not isinstance(noeud, ast.Call):
                continue
            cible = noeud.func
            if isinstance(cible, ast.Attribute):
                appels.append(cible.attr)

        for attendu_appel in ("rollback", "invalidate_all",
                              "_apply_authorized_recovery", "commit"):
            self.assertIn(attendu_appel, appels,
                          "le script doit appeler %s" % attendu_appel)
        self.assertLess(appels.index("rollback"),
                        appels.index("_apply_authorized_recovery"),
                        "le snapshot du dry-run doit etre jete AVANT l'application")
        self.assertLess(appels.index("invalidate_all"),
                        appels.index("_apply_authorized_recovery"))
        self.assertLess(appels.index("_apply_authorized_recovery"),
                        appels.index("commit"),
                        "on ne committe qu'apres succes")


@tagged("post_install", "-at_install")
class TestIntakeIdentityRecoveryAccounting(RecoveryFixtures):
    """Les deux gardes qui exigent de la comptabilité réelle.

    Ces tests tournent en ``post_install`` : les journaux naissent avec le plan
    comptable, à la fin de l'installation. Joués en ``at_install``, ils
    échouaient sur l'absence de journal — donc sur une cause étrangère à la
    règle mesurée — et non sur le refus qu'ils sont censés prouver.
    """

    def test_a_dossier_carrying_an_account_payment_is_never_retired(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-109")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-payment", "A020")
        collection = self._collection(ops, "test-payment|P|1")
        collection.write({"payment_id": self._account_payment(ops).id})

        rapport = self.recovery.simulate([ops.id], expected=self._expected(ops, consolidation))
        self.assertFalse(rapport["dry_run_pass"])
        self.assertTrue(any("paiements comptables" in motif.lower() for motif in rapport["blocking"]))
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], expected=self._expected(ops, consolidation),
                database=self.env.cr.dbname,
            )
        self.assertEqual(ops.collection_local_ref, "A020")

    def test_a_dossier_carrying_an_invoice_is_never_retired(self):
        consolidation = self._consolidation("AIR-DSS-CDG-2099-110")
        ops = self._cancelled_ops_dossier(consolidation, "ops:test-invoice", "A021")
        journal = self._journal("sale")
        invoice = self.env["account.move"].sudo().create({
            "move_type": "out_invoice",
            "partner_id": ops.partner_id.id,
            "company_id": journal.company_id.id,
            "journal_id": journal.id,
            "invoice_date": "2026-09-03",
        })
        ops.invoice_id = invoice.id

        rapport = self.recovery.simulate([ops.id], expected=self._expected(ops, consolidation))
        self.assertFalse(rapport["dry_run_pass"])
        self.assertTrue(any("facture" in motif.lower() for motif in rapport["blocking"]))
        with self.assertRaises(UserError):
            self.recovery._apply_authorized_recovery(
                [ops.id], expected=self._expected(ops, consolidation),
                database=self.env.cr.dbname,
            )
        self.assertEqual(ops.collection_local_ref, "A021")
