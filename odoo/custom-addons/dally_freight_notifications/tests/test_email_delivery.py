# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_freight_notifications.models.dally_shipment_notification import (
    CRON_BATCH_SIZE,
    MAX_ATTEMPTS,
    MOTIF_NON_PUBLIE,
    MOTIF_POLITIQUE,
    MOTIF_REFUS_CLIENT,
    MOTIF_SANS_ADRESSE,
    MOTIF_SANS_GABARIT,
)


@tagged("post_install", "-at_install", "dally")
class TestFreightEmailDelivery(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Notification = self.env["dally.shipment.notification"]
        self.Policy = self.env["dally.freight.state.policy"]
        self.service = self.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1)
        self.partner = self.env["res.partner"].create({
            "name": "Client notifications",
            "email": "client@example.invalid",
            "lang": "fr_FR",
        })

    def _shipment(self):
        return self.env["dally.shipment"].create({
            "partner_id": self.partner.id,
            "service_type_id": self.service.id,
            "transport_mode": "sea",
            "origin_city": "Le Havre",
            "destination_city": "Dakar",
        })

    def _pending(self, state="in_transit"):
        shipment = self._shipment()
        shipment.write({"state": state})
        notification = self.Notification.search(
            [("shipment_id", "=", shipment.id)], limit=1)
        return shipment, notification

    def _mail(self):
        return self.env["mail.mail"].create({
            "subject": "Test",
            "body_html": "<p>Test</p>",
            "email_from": "noreply@dallytrading.test",
            "email_to": "client@example.invalid",
        })

    def _patch_send(self, template, **kwargs):
        return patch.object(type(template), "send_mail", autospec=True, **kwargs)

    def test_cinq_templates_et_douze_policies_liees(self):
        templates = [
            self.env.ref("dally_freight_notifications.mail_template_prise_en_charge"),
            self.env.ref("dally_freight_notifications.mail_template_depart"),
            self.env.ref("dally_freight_notifications.mail_template_arrivee"),
            self.env.ref("dally_freight_notifications.mail_template_livraison"),
            self.env.ref("dally_freight_notifications.mail_template_annulation"),
        ]
        self.assertEqual(len(set(templates.ids)), 5)
        self.assertEqual(
            self.Policy.search_count([
                ("notify_customer", "=", True),
                ("email_template_id", "!=", False),
            ]),
            12,
        )
        self.assertFalse(self.Policy._dally_policy_for("draft").email_template_id)
        self.assertFalse(self.Policy._dally_policy_for("preparing").email_template_id)

    def test_templates_ne_naviguent_vers_aucune_relation_metier(self):
        forbidden = (
            "object.partner_id", "object.shipment_id", "object.event_id",
            "supplier", "margin", "purchase", "internal_notes", "carrier",
        )
        templates = self.env["mail.template"].browse([
            self.env.ref("dally_freight_notifications.mail_template_prise_en_charge").id,
            self.env.ref("dally_freight_notifications.mail_template_depart").id,
            self.env.ref("dally_freight_notifications.mail_template_arrivee").id,
            self.env.ref("dally_freight_notifications.mail_template_livraison").id,
            self.env.ref("dally_freight_notifications.mail_template_annulation").id,
        ])
        for template in templates:
            source = " ".join(filter(None, [
                template.subject, template.email_to, template.lang,
                str(template.body_html or ""),
            ])).lower()
            for term in forbidden:
                self.assertNotIn(term.lower(), source, "%s: %s" % (template.name, term))

    def test_langue_est_figee_dans_le_snapshot(self):
        _shipment, notification = self._pending()
        self.assertEqual(notification.language_code, "fr_FR")
        self.partner.lang = "en_US"
        self.assertEqual(notification.language_code, "fr_FR")

    def test_langue_retombe_sur_celle_de_la_societe(self):
        company_lang = self.env.company.partner_id.lang or self.env.lang or "fr_FR"
        self.partner.lang = False
        _shipment, notification = self._pending()
        self.assertEqual(notification.language_code, company_lang)

    def test_pending_devient_sent_avec_mail_id(self):
        _shipment, notification = self._pending()
        self.assertEqual(notification.status, "pending")
        mail = self._mail()
        template = self.Policy._dally_policy_for(notification.state).email_template_id
        with self._patch_send(template, return_value=mail.id) as mocked:
            self.assertTrue(notification._dally_deliver_one())
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(notification.status, "sent")
        self.assertEqual(notification.mail_id, mail)
        self.assertTrue(notification.sent_at)
        self.assertEqual(notification.attempts, 1)
        self.assertFalse(notification.last_error)

    def test_rejouer_une_notification_sent_ne_renvoie_rien(self):
        _shipment, notification = self._pending()
        mail = self._mail()
        template = self.Policy._dally_policy_for(notification.state).email_template_id
        with self._patch_send(template, return_value=mail.id) as mocked:
            notification._dally_deliver_one()
            notification._dally_deliver_one()
        self.assertEqual(mocked.call_count, 1)

    def test_opt_out_tardif_devient_skipped(self):
        _shipment, notification = self._pending()
        self.partner.dally_freight_notify = False
        notification._dally_deliver_one()
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_REFUS_CLIENT)

    def test_policy_desactivee_tardivement_devient_skipped(self):
        _shipment, notification = self._pending()
        self.Policy._dally_policy_for("in_transit").notify_customer = False
        notification._dally_deliver_one()
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_POLITIQUE)

    def test_template_retire_tardivement_devient_skipped(self):
        _shipment, notification = self._pending()
        self.Policy._dally_policy_for("in_transit").email_template_id = False
        notification._dally_deliver_one()
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_SANS_GABARIT)

    def test_email_retire_tardivement_devient_skipped(self):
        _shipment, notification = self._pending()
        self.partner.email = False
        notification._dally_deliver_one()
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_SANS_ADRESSE)

    def test_email_corrige_avant_envoi_est_utilise(self):
        _shipment, notification = self._pending()
        self.partner.email = "nouveau@example.invalid"
        mail = self._mail()
        template = self.Policy._dally_policy_for(notification.state).email_template_id
        with self._patch_send(template, return_value=mail.id):
            notification._dally_deliver_one()
        self.assertEqual(notification.email, "nouveau@example.invalid")

    def test_un_echec_reste_pending_et_incremente_attempts(self):
        _shipment, notification = self._pending()
        template = self.Policy._dally_policy_for(notification.state).email_template_id
        with self._patch_send(template, side_effect=RuntimeError("SMTP indisponible")):
            self.assertFalse(notification._dally_deliver_one())
        self.assertEqual(notification.status, "pending")
        self.assertEqual(notification.attempts, 1)
        self.assertIn("RuntimeError", notification.last_error)

    def test_cinquieme_echec_devient_failed(self):
        _shipment, notification = self._pending()
        template = self.Policy._dally_policy_for(notification.state).email_template_id
        with self._patch_send(template, side_effect=RuntimeError("SMTP indisponible")):
            for _index in range(MAX_ATTEMPTS):
                notification._dally_deliver_one()
        self.assertEqual(notification.status, "failed")
        self.assertEqual(notification.attempts, MAX_ATTEMPTS)

    def test_retry_peut_reussir_avant_la_cinquieme_tentative(self):
        _shipment, notification = self._pending()
        mail = self._mail()
        template = self.Policy._dally_policy_for(notification.state).email_template_id
        with self._patch_send(
            template,
            side_effect=[RuntimeError("temporaire"), mail.id],
        ):
            self.assertFalse(notification._dally_deliver_one())
            self.assertTrue(notification._dally_deliver_one())
        self.assertEqual(notification.status, "sent")
        self.assertEqual(notification.attempts, 2)
        self.assertEqual(notification.mail_id, mail)

    def test_erreur_ne_conserve_jamais_le_token_de_tracking(self):
        _shipment, notification = self._pending()
        token = notification.tracking_url.split("t=", 1)[-1]
        template = self.Policy._dally_policy_for(notification.state).email_template_id
        with self._patch_send(
            template,
            side_effect=RuntimeError("échec sur %s" % notification.tracking_url),
        ):
            notification._dally_deliver_one()
        self.assertNotIn(token, notification.last_error)
        self.assertNotIn(notification.tracking_url, notification.last_error)

    def test_preparing_ne_produit_jamais_un_mail(self):
        _shipment, notification = self._pending("preparing")
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_POLITIQUE)
        self.assertFalse(notification.mail_id)

    def test_evenement_vendor_projete_reste_inenvoyable(self):
        shipment = self._shipment()
        event = self.env["dally.shipment.event"].create({
            "shipment_id": shipment.id,
            "status": "in_transit",
            "description": "Projection fournisseur",
            "visible_to_customer": False,
            "is_automatic": True,
        })
        notification = self.Notification.search([("event_id", "=", event.id)])
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_NON_PUBLIE)
        self.assertFalse(notification.mail_id)

    def test_reecriture_du_meme_etat_ne_cree_pas_un_second_mail(self):
        shipment, notification = self._pending()
        shipment.write({"state": "in_transit"})
        shipment.write({"state": "in_transit"})
        self.assertEqual(
            self.Notification.search_count([("shipment_id", "=", shipment.id)]),
            1,
        )
        self.assertEqual(notification.status, "pending")

    def test_cron_est_borne_et_utilise_skip_locked(self):
        import inspect
        source = inspect.getsource(type(self.Notification)._cron_process_pending_notifications)
        self.assertIn("FOR UPDATE SKIP LOCKED", source)
        self.assertEqual(CRON_BATCH_SIZE, 100)
        self.assertEqual(MAX_ATTEMPTS, 5)

    def test_cron_xml_est_actif_toutes_les_quinze_minutes(self):
        cron = self.env.ref(
            "dally_freight_notifications.ir_cron_dally_freight_notification_delivery")
        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_number, 15)
        self.assertEqual(cron.interval_type, "minutes")

    def test_templates_ne_contiennent_aucune_donnee_sensible(self):
        forbidden = ("cost", "margin", "supplier", "purchase", "internal", "carrier")
        for xmlid in (
            "mail_template_prise_en_charge", "mail_template_depart",
            "mail_template_arrivee", "mail_template_livraison",
            "mail_template_annulation",
        ):
            template = self.env.ref("dally_freight_notifications.%s" % xmlid)
            rendered_source = "%s %s %s" % (
                template.subject or "", template.email_to or "", template.body_html or "")
            for term in forbidden:
                self.assertNotIn(term, rendered_source.lower(), "%s: %s" % (xmlid, term))
