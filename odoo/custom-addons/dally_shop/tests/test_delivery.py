# -*- coding: utf-8 -*-
"""E-commerce Pro Lot C : méthodes, frais, autorisation et suivi de remise."""

import json
import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_shop")
class TestShopDelivery(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "Client Livraison Boutique",
            "email": "delivery.shop@essai.invalid",
            "phone": "+221770000001",
            "street": "1 rue Livraison",
            "city": "Dakar",
            "zip": "11000",
            "country_id": cls.env.ref("base.sn").id,
        })
        cls.pricelist = cls.env["product.pricelist"].create({
            "name": "Tarif Boutique Lot C",
            "currency_id": cls.env.company.currency_id.id,
            "item_ids": [(0, 0, {
                "compute_price": "fixed",
                "fixed_price": 10000.0,
                "applied_on": "3_global",
            })],
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(cls.pricelist.id)
        )
        cls.product = cls.env["product.template"].create({
            "name": "Produit Livraison Lot C",
            "type": "consu",
            "sale_ok": True,
            "list_price": 99999.0,
            "dally_shop_slug": "produit-livraison-lot-c",
            "dally_published": True,
        })
        cls.group_operations = cls.env.ref("dally_shop.group_dally_shop_operations")
        cls.operator = cls.env["res.users"].create({
            "name": "Opérateur Livraison Boutique",
            "login": "shop.delivery.operator@essai.invalid",
            "email": "shop.delivery.operator@essai.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.group_operations.id,
            ])],
        })
        cls.readonly = cls.env["res.users"].create({
            "name": "Lecteur Livraison Boutique",
            "login": "shop.delivery.readonly@essai.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("dally_core.group_dally_readonly").id,
            ])],
        })
        cls.fixed_method = cls.env["dally.shop.delivery.method"].create({
            "name": "Dakar express",
            "code": "dakar-express",
            "kind": "delivery",
            "fee_policy": "fixed",
            "fixed_fee": 2500.0,
            "currency_id": cls.env.company.currency_id.id,
        })

    def _lines(self):
        return self.env["product.template"]._dally_shop_resolve_lines([
            (self.product.dally_shop_slug, 2),
        ])

    def _order(self, mode="pickup", shipping=None):
        return self.env["sale.order"].dally_shop_place_order(
            str(uuid.uuid4()),
            self.partner,
            self._lines(),
            mode,
            invite=False,
            shipping=shipping,
        )

    def _as_operator(self, order):
        return self.env["sale.order"].with_user(self.operator).browse(order.id)

    def test_methodes_par_defaut_et_projection_publique(self):
        pickup = self.env.ref("dally_shop.delivery_method_pickup")
        delivery = self.env.ref("dally_shop.delivery_method_delivery_to_confirm")
        self.assertEqual(pickup.kind, "pickup")
        self.assertEqual(pickup.fee_policy, "free")
        self.assertFalse(pickup.requires_address)
        self.assertEqual(delivery.kind, "delivery")
        self.assertEqual(delivery.fee_policy, "quote")
        self.assertTrue(delivery.requires_address)

        projection = self.env["dally.shop.delivery.method"]._dally_shop_public_methods()
        serialised = json.dumps(projection, default=str)
        self.assertIn("pickup", serialised)
        self.assertIn("delivery_to_confirm", serialised)
        self.assertNotIn('"id"', serialised)
        self.assertNotIn("company_id", serialised)

    def test_methode_inactive_nest_jamais_resolue(self):
        method = self.fixed_method.copy({"name": "Inactive", "code": "inactive-test", "active": False})
        self.assertFalse(self.env["dally.shop.delivery.method"]._dally_shop_resolve(method.code))
        with self.assertRaises(ValidationError):
            self._order(mode=method.code)

    def test_retrait_gratuit_fige_zero_et_reste_brouillon(self):
        order = self._order("pickup")
        self.assertEqual(order.dally_shop_delivery_method_id, self.env.ref("dally_shop.delivery_method_pickup"))
        self.assertEqual(order.dally_shop_delivery_fee_state, "free")
        self.assertEqual(order.dally_shop_delivery_fee, 0)
        self.assertEqual(order.dally_shop_fulfillment_state, "pending")
        self.assertFalse(order.dally_shop_fulfillment_authorized)
        self.assertEqual(order.state, "draft")
        self.assertFalse(order.picking_ids)
        self.assertFalse(order.invoice_ids)
        self.assertEqual(order._dally_shop_delivery_grand_total(), order.amount_total)

    def test_frais_fixes_viennent_dodoo_et_pas_du_navigateur(self):
        order = self._order("dakar-express")
        self.assertEqual(order.dally_shop_delivery_method_id, self.fixed_method)
        self.assertEqual(order.dally_shop_delivery_fee_state, "fixed")
        self.assertEqual(order.dally_shop_delivery_fee, 2500.0)
        self.assertEqual(order._dally_shop_delivery_grand_total(), order.amount_total + 2500.0)
        self.assertEqual(order.state, "draft")

    def test_livraison_a_coter_snapshotte_adresse_et_total_inconnu(self):
        order = self._order("delivery_to_confirm")
        self.assertEqual(order.dally_shop_delivery_fee_state, "pending_quote")
        self.assertEqual(order.dally_shop_shipping_name, self.partner.name)
        self.assertEqual(order.dally_shop_shipping_street, self.partner.street)
        self.assertEqual(order.dally_shop_shipping_city, "Dakar")
        self.assertEqual(order.dally_shop_shipping_country_code, "SN")
        self.assertIsNone(order._dally_shop_delivery_grand_total())

    def test_adresse_distincte_remplace_le_snapshot_du_profil(self):
        order = self._order("delivery_to_confirm", shipping={
            "name": "Dépôt destinataire",
            "phone": "+221770000002",
            "street": "99 avenue Livraison",
            "street2": "Hangar B",
            "city": "Thiès",
            "zip": "21000",
            "country_code": "SN",
        })
        self.assertEqual(order.dally_shop_shipping_name, "Dépôt destinataire")
        self.assertEqual(order.dally_shop_shipping_street, "99 avenue Livraison")
        self.assertEqual(order.dally_shop_shipping_street2, "Hangar B")
        self.assertEqual(order.dally_shop_shipping_city, "Thiès")

    def test_livraison_refuse_si_aucune_adresse_exploitable(self):
        partner = self.env["res.partner"].create({"name": "Sans Adresse"})
        with self.assertRaises(ValidationError):
            self.env["sale.order"].dally_shop_place_order(
                str(uuid.uuid4()), partner, self._lines(), "delivery_to_confirm"
            )

    def test_projection_checkout_ne_fuit_aucun_identifiant(self):
        order = self._order("delivery_to_confirm")
        projection = order._dally_shop_projection()
        self.assertEqual(projection["deliveryMode"], "delivery_to_confirm")
        self.assertIn("delivery", projection)
        self.assertIsNone(projection["delivery"]["fee"]["amount"])
        self.assertIsNone(projection["grandTotal"])
        payload = json.dumps(projection, default=str)
        self.assertNotIn("partner_id", payload)
        self.assertNotIn("delivery_method_id", payload)
        self.assertNotIn(str(self.partner.id), payload)

    def test_cotation_frais_ne_confirme_toujours_pas_la_vente(self):
        order = self._order("delivery_to_confirm")
        operated = self._as_operator(order)
        operated._dally_shop_set_delivery_fee(3500.0)
        order.invalidate_recordset()
        self.assertEqual(order.dally_shop_delivery_fee_state, "quoted")
        self.assertEqual(order.dally_shop_delivery_fee, 3500.0)
        self.assertEqual(order.state, "draft")
        self.assertFalse(order.picking_ids)
        self.assertFalse(order.invoice_ids)
        self.assertEqual(order._dally_shop_delivery_grand_total(), order.amount_total + 3500.0)

    def test_cotation_est_idempotente_mais_pas_reinscriptible(self):
        order = self._order("delivery_to_confirm")
        operated = self._as_operator(order)
        operated._dally_shop_set_delivery_fee(3500.0)
        self.assertTrue(operated._dally_shop_set_delivery_fee(3500.0))
        with self.assertRaises(ValidationError):
            operated._dally_shop_set_delivery_fee(3600.0)

    def test_preparation_refusee_tant_que_workflow_ou_frais_manquent(self):
        order = self._order("delivery_to_confirm")
        operated = self._as_operator(order)
        with self.assertRaises(ValidationError):
            operated.action_dally_shop_authorize_fulfillment()

        operated.action_dally_shop_validate()
        with self.assertRaises(ValidationError):
            operated.action_dally_shop_authorize_fulfillment()

        operated._dally_shop_set_delivery_fee(3500.0)
        self.assertEqual(order.state, "draft")

    def test_autorisation_est_unique_et_seul_point_qui_confirme_la_vente(self):
        order = self._order("delivery_to_confirm")
        operated = self._as_operator(order)
        operated.action_dally_shop_validate()
        operated._dally_shop_set_delivery_fee(3500.0)

        self.assertEqual(order.state, "draft")
        operated.action_dally_shop_authorize_fulfillment()
        order.invalidate_recordset()

        self.assertEqual(order.state, "sale")
        self.assertTrue(order.dally_shop_fulfillment_authorized)
        self.assertEqual(order.dally_shop_fulfillment_state, "preparing")
        self.assertTrue(order.dally_shop_fulfillment_authorized_at)
        self.assertEqual(order.dally_shop_fulfillment_authorized_by_id, self.operator)
        events = self.env["dally.shop.fulfillment.event"].search([
            ("order_id", "=", order.id),
        ])
        self.assertEqual(len(events), 1)
        self.assertEqual(events.to_state, "preparing")
        self.assertFalse(order.invoice_ids)

        operated.action_dally_shop_authorize_fulfillment()
        self.assertEqual(
            self.env["dally.shop.fulfillment.event"].search_count([("order_id", "=", order.id)]),
            1,
        )

    def test_parcours_livraison_est_borne(self):
        order = self._order("dakar-express")
        operated = self._as_operator(order)
        operated.action_dally_shop_validate()
        operated.action_dally_shop_authorize_fulfillment()
        operated.action_dally_shop_mark_ready()
        self.assertEqual(order.dally_shop_fulfillment_state, "ready")

        with self.assertRaises(ValidationError):
            operated.action_dally_shop_complete_fulfillment()

        operated.action_dally_shop_dispatch()
        self.assertEqual(order.dally_shop_fulfillment_state, "out_for_delivery")
        operated.action_dally_shop_complete_fulfillment()
        self.assertEqual(order.dally_shop_fulfillment_state, "delivered")

    def test_parcours_retrait_ne_peut_pas_etre_mis_en_livraison(self):
        order = self._order("pickup")
        operated = self._as_operator(order)
        operated.action_dally_shop_validate()
        operated.action_dally_shop_authorize_fulfillment()
        operated.action_dally_shop_mark_ready()
        with self.assertRaises(ValidationError):
            operated.action_dally_shop_dispatch()
        operated.action_dally_shop_complete_fulfillment()
        self.assertEqual(order.dally_shop_fulfillment_state, "picked_up")

    def test_annulation_metier_bloquee_apres_autorisation(self):
        order = self._order("pickup")
        operated = self._as_operator(order)
        operated.action_dally_shop_validate()
        operated.action_dally_shop_authorize_fulfillment()
        with self.assertRaises(ValidationError):
            operated._dally_shop_transition("cancelled", "Client absent")

    def test_lecteur_ne_peut_ni_coter_ni_autoriser(self):
        order = self._order("delivery_to_confirm")
        readonly = self.env["sale.order"].with_user(self.readonly).browse(order.id)
        with self.assertRaises(AccessError):
            readonly._dally_shop_set_delivery_fee(1000.0)
        with self.assertRaises(AccessError):
            readonly.action_dally_shop_authorize_fulfillment()

    def test_historique_remise_est_lecture_seule_pour_operateur(self):
        order = self._order("pickup")
        operated = self._as_operator(order)
        operated.action_dally_shop_validate()
        operated.action_dally_shop_authorize_fulfillment()
        event = order.dally_shop_fulfillment_event_ids.with_user(self.operator)
        self.assertTrue(event)
        with self.assertRaises(AccessError):
            event.write({"to_state": "ready"})
        with self.assertRaises(AccessError):
            event.unlink()
