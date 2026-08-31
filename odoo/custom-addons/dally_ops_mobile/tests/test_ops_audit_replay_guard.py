# -*- coding: utf-8 -*-
"""L'idempotence du journal, garantie par le modèle et non par ses appelants.

## Pourquoi ce test existe séparément

Une campagne de mutations a tenté de faire journaliser deux fois le même geste
depuis le service d'avancement d'état. La mutation n'a rien cassé — et c'est la
bonne nouvelle : `dally.ops.audit.event.create` reconnaît un rejeu et rend
l'événement déjà écrit au lieu d'en créer un second.

Le mutant est donc **équivalent** : le service peut appeler `_journaliser` deux
fois sans conséquence. Mais une protection qu'aucun test ne nomme finit par
disparaître au premier remaniement. Ce fichier la nomme.

## Ce qu'il prouve exactement

Que l'invariant « un geste, un événement » tient au niveau du **modèle** :
la lecture avant écriture de `create`, doublée par la contrainte
`UNIQUE(company_id, action, request_uuid)` en base. Pas par un retour anticipé
du service d'état, qui n'est qu'une commodité.
"""

import uuid

from odoo import fields
from odoo.tests import TransactionCase, tagged
from psycopg2 import errors
from psycopg2.errorcodes import UNIQUE_VIOLATION

from odoo.tools import mute_logger


@tagged("post_install", "-at_install", "dally")
class TestOpsAuditReplayGuard(TransactionCase):

    ACTION = "intake_state_advanced"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.societe = cls.env.company
        cls.partenaire = cls.env["res.partner"].create({
            "name": "Client Journal Rejeu", "company_id": cls.societe.id})
        cls.dossier = cls.env["dally.shipment"].sudo().create({
            "partner_id": cls.partenaire.id, "company_id": cls.societe.id,
            "external_reference": "AIR-AUDIT-REJEU-%s" % uuid.uuid4().hex[:8].upper(),
            "transport_mode": "air", "direction": "export",
        })

    def _valeurs(self, request_uuid):
        return {
            "company_id": self.societe.id,
            "operator_user_id": self.env.uid,
            "action": self.ACTION,
            "entity_model": "dally.shipment",
            "entity_res_id": self.dossier.id,
            "shipment_id": self.dossier.id,
            "request_uuid": request_uuid,
            "changes_json": [{
                "field": "state",
                "old_value": "goods_received",
                "new_value": "preparing",
            }],
            "created_at": fields.Datetime.now(),
        }

    def _journal(self, request_uuid):
        return self.env["dally.ops.audit.event"].sudo().search([
            ("company_id", "=", self.societe.id),
            ("action", "=", self.ACTION),
            ("request_uuid", "=", request_uuid),
        ])

    def test_journaliser_deux_fois_le_meme_geste_nen_ecrit_quun(self):
        """Le cœur de l'invariant : deux appels, un seul événement."""
        identifiant = str(uuid.uuid4())
        premier = self.env["dally.ops.audit.event"].sudo().create(
            self._valeurs(identifiant))
        second = self.env["dally.ops.audit.event"].sudo().create(
            self._valeurs(identifiant))

        self.assertEqual(len(self._journal(identifiant)), 1)
        # Le second appel ne crée pas : il rend l'existant.
        self.assertEqual(second, premier)
        self.assertEqual(premier.changes_json, [{
            "field": "state", "old_value": "goods_received",
            "new_value": "preparing",
        }])

    def test_la_garde_ne_depend_pas_du_service_detat(self):
        """Elle vit dans le modèle : le journal est appelé directement ici.

        Aucun service d'avancement d'état n'intervient. Si la protection était
        un retour anticipé de ce service, ce test verrait deux événements.
        """
        identifiant = str(uuid.uuid4())
        for _essai in range(4):
            self.env["dally.ops.audit.event"].sudo().create(
                self._valeurs(identifiant))
        self.assertEqual(len(self._journal(identifiant)), 1)

    def test_la_base_refuse_un_doublon_meme_en_contournant_create(self):
        """La ceinture après les bretelles : la contrainte existe en base.

        On écrit directement en SQL pour court-circuiter la lecture préalable
        de `create`. PostgreSQL doit alors refuser — c'est ce qui rend
        l'invariant vrai même pour un appelant qui n'utiliserait pas l'ORM.
        """
        identifiant = str(uuid.uuid4())
        evenement = self.env["dally.ops.audit.event"].sudo().create(
            self._valeurs(identifiant))
        self.env.flush_all()

        with self.assertRaises(errors.lookup(UNIQUE_VIOLATION)), \
                mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self.env.cr.execute(
                """
                INSERT INTO dally_ops_audit_event
                    (event_uuid, company_id, operator_user_id, action,
                     request_uuid, created_at)
                VALUES (%s, %s, %s, %s, %s, now())
                """,
                [str(uuid.uuid4()), self.societe.id, self.env.uid,
                 self.ACTION, identifiant],
            )
        self.assertEqual(len(self._journal(identifiant)), 1)
        self.assertTrue(evenement.exists())

    def test_deux_gestes_distincts_produisent_deux_evenements(self):
        """L'unicité ne doit pas écraser de vraies opérations concurrentes."""
        premier, second = str(uuid.uuid4()), str(uuid.uuid4())
        self.env["dally.ops.audit.event"].sudo().create(self._valeurs(premier))
        self.env["dally.ops.audit.event"].sudo().create(self._valeurs(second))
        self.assertEqual(len(self._journal(premier)), 1)
        self.assertEqual(len(self._journal(second)), 1)
        self.assertNotEqual(self._journal(premier), self._journal(second))
