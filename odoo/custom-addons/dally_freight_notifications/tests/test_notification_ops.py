# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_freight.tests.common import set_shipment_state


@tagged("post_install", "-at_install", "dally")
class TestFreightNotificationOps(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Notification = self.env["dally.shipment.notification"]
        self.Policy = self.env["dally.freight.state.policy"]
        self.service = self.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1)
        self.partner = self.env["res.partner"].create({
            "name": "Client opérations notifications",
            "email": "ops@example.invalid",
            "lang": "fr_FR",
        })
        Users = self.env["res.users"].with_context(no_reset_password=True)
        self.manager = Users.create({
            "name": "Manager notifications",
            "login": "notif.manager@dallytrading.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("dally_core.group_dally_manager").id,
            ])],
        })
        self.reader = Users.create({
            "name": "Lecteur notifications",
            "login": "notif.reader@dallytrading.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("dally_core.group_dally_readonly").id,
            ])],
        })

    def _shipment(self):
        return self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "service_type_id": self.service.id,
            "transport_mode": "sea",
            "origin_city": "Le Havre",
            "destination_city": "Dakar",
        })

    def _pending(self):
        shipment = self._shipment()
        set_shipment_state(shipment, "in_transit")
        notification = self.Notification.search(
            [("shipment_id", "=", shipment.id)], limit=1)
        self.assertEqual(notification.status, "pending")
        return shipment, notification

    def test_compteurs_refletent_exactement_la_file_du_dossier(self):
        shipment, pending = self._pending()
        set_shipment_state(shipment, "arrived")
        notifications = self.Notification.search([
            ("shipment_id", "=", shipment.id),
        ])
        self.assertEqual(len(notifications), 2)

        second = notifications - pending
        second.write({"status": "failed", "attempts": 5, "last_error": "SMTP"})
        shipment.invalidate_recordset()

        self.assertEqual(shipment.notification_count, 2)
        self.assertEqual(shipment.notification_pending_count, 1)
        self.assertEqual(shipment.notification_failed_count, 1)

    def test_actions_du_dossier_filtrent_la_bonne_file(self):
        shipment, pending = self._pending()
        pending.write({"status": "failed", "attempts": 5, "last_error": "SMTP"})

        all_action = shipment.action_view_notifications()
        self.assertEqual(all_action["domain"], [("shipment_id", "=", shipment.id)])

        failed_action = shipment.action_view_failed_notifications()
        self.assertIn(("shipment_id", "=", shipment.id), failed_action["domain"])
        self.assertIn(("status", "=", "failed"), failed_action["domain"])

        pending.write({"status": "pending"})
        pending_action = shipment.action_view_pending_notifications()
        self.assertIn(("shipment_id", "=", shipment.id), pending_action["domain"])
        self.assertIn(("status", "=", "pending"), pending_action["domain"])

    def test_manager_peut_remettre_un_echec_en_file_sans_envoyer(self):
        _shipment, notification = self._pending()
        notification.write({
            "status": "failed",
            "attempts": 5,
            "last_error": "RuntimeError: SMTP indisponible",
        })

        result = notification.with_user(self.manager).action_retry_delivery()
        self.assertTrue(result)
        notification.invalidate_recordset()
        self.assertEqual(notification.status, "pending")
        self.assertEqual(notification.attempts, 0)
        self.assertFalse(notification.last_error)
        self.assertFalse(notification.mail_id)
        self.assertFalse(notification.sent_at)
        self.assertEqual(notification.manual_retry_count, 1)
        self.assertTrue(notification.last_retry_at)

    def test_lecteur_ne_peut_pas_relancer(self):
        _shipment, notification = self._pending()
        notification.write({"status": "failed", "attempts": 5})
        with self.assertRaises(AccessError):
            notification.with_user(self.reader).action_retry_delivery()

    def test_un_statut_non_failed_ne_peut_pas_etre_relance(self):
        _shipment, notification = self._pending()
        with self.assertRaises(UserError):
            notification.with_user(self.manager).action_retry_delivery()

    def test_relance_revalide_opt_out_et_policy(self):
        _shipment, notification = self._pending()
        notification.write({"status": "failed", "attempts": 5})
        self.partner.dally_freight_notify = False
        with self.assertRaises(UserError):
            notification.with_user(self.manager).action_retry_delivery()

        self.partner.dally_freight_notify = True
        self.Policy._dally_policy_for("in_transit").notify_customer = False
        with self.assertRaises(UserError):
            notification.with_user(self.manager).action_retry_delivery()

    def test_compteurs_internes_ne_sont_pas_exposes_au_portail(self):
        portal_user = self.env["res.users"].with_context(
            no_reset_password=True
        ).create({
            "name": "Client portail compteur",
            "login": "notif.counter.portal@dallytrading.invalid",
            "partner_id": self.partner.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        fields = self.env["dally.shipment"].with_user(portal_user).fields_get()
        self.assertNotIn("notification_count", fields)
        self.assertNotIn("notification_pending_count", fields)
        self.assertNotIn("notification_failed_count", fields)

    def test_vues_et_filtres_operations_sont_chargeables(self):
        search = self.env.ref(
            "dally_freight_notifications.dally_shipment_notification_view_search"
        )
        form = self.env.ref(
            "dally_freight_notifications.dally_shipment_notification_view_form_ops"
        )
        shipment_form = self.env.ref(
            "dally_freight_notifications.dally_shipment_view_form_notification_ops"
        )
        self.assertTrue(search.arch_db)
        self.assertIn("filter_failed", search.arch_db)
        self.assertIn("action_retry_delivery", form.arch_db)
        self.assertIn("action_view_failed_notifications", shipment_form.arch_db)
