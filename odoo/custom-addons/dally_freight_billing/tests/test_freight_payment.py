# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install", "dally")
class TestFreightPaymentCollection(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # AccountTestInvoicingCommon deliberately runs with its own accounting
        # test user.  That user has accounting fixture rights but none of the
        # DallyTrading Freight ACLs, so creating the shipment used by these
        # business-behaviour tests fails before the payment code is reached.
        #
        # Grant only the roles required by this model-level scenario.  These
        # additions live inside the transactional test fixture; they do not
        # alter module ACLs, integration users or production permissions.
        cls.env.user.group_ids += cls.env.ref("dally_core.group_dally_manager")
        cls.env.user.group_ids += cls.env.ref("sales_team.group_sale_salesman")
        cls.env.user.group_ids += cls.env.ref("account.group_account_invoice")

        # Use Odoo's accounting-test helper instead of toggling currencies by
        # hand in every test. It activates multi-currency consistently and
        # creates deterministic rates for the payment register wizard.
        cls.eur = cls.setup_other_currency("EUR")
        cls.xof = cls.setup_other_currency("XOF")
        cls.food = cls.env.ref("dally_freight_billing.tariff_family_food")

    def _ready_shipment(self, reference):
        shipment = self.env["dally.shipment"].create({
            "partner_id": self.partner_a.id,
            "external_reference": reference,
            "transport_mode": "air",
            "direction": "export",
            "customer_segment_snapshot": "individual",
        })
        line = self.env["dally.shipment.package"].create({
            "shipment_id": shipment.id,
            "external_line_key": "%s|A|1" % reference,
            "package_type": "parcel",
            "description": "Café Touba",
            "quantity": 1,
            "unit_weight_kg": 10.0,
            "billing_method": "real",
            "tariff_family_id": self.food.id,
        })
        line.action_apply_freight_tariff()
        return shipment

    def _collection_values(self, shipment, key, amount=10.0, currency=None, method="wave"):
        currency = currency or self.eur
        return {
            "external_payment_key": key,
            "shipment_id": shipment.id,
            "amount": amount,
            "currency_id": currency.id,
            "payment_date": "2026-08-21",
            "source_method": method,
            "source": "google_sheets",
            "collected_by_name": "Test Collector",
        }

    def _configure_channel(self, currency=None, code="wave"):
        currency = currency or self.eur
        journal = self.company_data["default_journal_bank"]
        method_line = journal.inbound_payment_method_line_ids[:1]
        self.assertTrue(method_line, "Accounting test setup must provide an inbound payment method")
        return self.env["dally.freight.payment.channel"].create({
            "name": "%s %s" % (code.title(), currency.name),
            "code": code,
            "company_id": self.env.company.id,
            "currency_id": currency.id,
            "journal_id": journal.id,
            "payment_method_line_id": method_line.id,
        })

    def test_collection_before_invoice_is_kept_pending(self):
        shipment = self._ready_shipment("PAY-PENDING")
        collection, created = self.env["dally.freight.collection"].upsert_from_sync(
            self._collection_values(shipment, "BF-PENDING-001")
        )
        self.assertTrue(created)
        self.assertEqual(collection.state, "pending")
        self.assertFalse(collection.payment_id)
        self.assertIn("invoice", (collection.error_message or "").lower())

    def test_same_business_key_is_idempotent_before_accounting(self):
        shipment = self._ready_shipment("PAY-IDEMPOTENT")
        values = self._collection_values(shipment, "BF-IDEMPOTENT-001")
        first, created_first = self.env["dally.freight.collection"].upsert_from_sync(values)
        second, created_second = self.env["dally.freight.collection"].upsert_from_sync(values)
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first, second)
        self.assertEqual(
            self.env["dally.freight.collection"].search_count([
                ("external_payment_key", "=", "BF-IDEMPOTENT-001")
            ]),
            1,
        )

    def test_pending_collection_can_be_corrected_before_accounting(self):
        shipment = self._ready_shipment("PAY-CORRECT")
        values = self._collection_values(shipment, "BF-CORRECT-001", amount=10.0)
        collection, _created = self.env["dally.freight.collection"].upsert_from_sync(values)
        values["amount"] = 12.5
        same, created = self.env["dally.freight.collection"].upsert_from_sync(values)
        self.assertFalse(created)
        self.assertEqual(collection, same)
        self.assertAlmostEqual(same.amount, 12.5, places=2)
        self.assertFalse(same.payment_id)

    def test_posting_invoice_promotes_pending_collection_to_native_payment(self):
        shipment = self._ready_shipment("PAY-POST")
        self._configure_channel(self.eur, "wave")
        collection, _created = self.env["dally.freight.collection"].upsert_from_sync(
            self._collection_values(shipment, "BF-POST-001", amount=10.0)
        )
        self.assertEqual(collection.state, "pending")

        invoice = shipment.action_prepare_native_freight_invoice()
        self.assertEqual(invoice.state, "draft")
        invoice.action_post()

        collection.invalidate_recordset()
        invoice.invalidate_recordset()
        self.assertEqual(collection.state, "registered")
        self.assertTrue(collection.payment_id)
        self.assertEqual(collection.payment_id.dally_external_payment_key, "BF-POST-001")
        self.assertEqual(collection.payment_id.dally_freight_shipment_id, shipment)
        self.assertEqual(collection.payment_id.state, "in_process")
        self.assertIn(invoice.payment_state, ("partial", "in_payment", "paid"))

    def test_posted_invoice_without_channel_keeps_cash_entry_visible(self):
        shipment = self._ready_shipment("PAY-NO-CHANNEL")
        invoice = shipment.action_prepare_native_freight_invoice()
        invoice.action_post()
        collection, created = self.env["dally.freight.collection"].upsert_from_sync(
            self._collection_values(shipment, "BF-NO-CHANNEL-001", amount=10.0, method="wave_missing")
        )
        self.assertTrue(created)
        self.assertFalse(collection.payment_id)
        self.assertEqual(collection.state, "pending")
        self.assertIn("No payment channel", collection.error_message or "")

    def test_registered_collection_is_immutable(self):
        shipment = self._ready_shipment("PAY-IMMUTABLE")
        self._configure_channel(self.eur, "cash")
        invoice = shipment.action_prepare_native_freight_invoice()
        invoice.action_post()
        values = self._collection_values(
            shipment,
            "BF-IMMUTABLE-001",
            amount=10.0,
            method="cash",
        )
        collection, _created = self.env["dally.freight.collection"].upsert_from_sync(values)
        self.assertTrue(collection.payment_id)

        same, created = self.env["dally.freight.collection"].upsert_from_sync(values)
        self.assertFalse(created)
        self.assertEqual(same, collection)

        changed = dict(values, amount=11.0)
        with self.assertRaises(UserError):
            self.env["dally.freight.collection"].upsert_from_sync(changed)
        with self.assertRaises(UserError):
            collection.write({"amount": 12.0})
        with self.assertRaises(UserError):
            collection.unlink()

    def test_xof_collection_is_preserved_as_xof(self):
        shipment = self._ready_shipment("PAY-XOF")
        collection, created = self.env["dally.freight.collection"].upsert_from_sync(
            self._collection_values(
                shipment,
                "BF-XOF-001",
                amount=25000.0,
                currency=self.xof,
                method="wave",
            )
        )
        self.assertTrue(created)
        self.assertEqual(collection.currency_id, self.xof)
        self.assertAlmostEqual(collection.amount, 25000.0, places=2)
        self.assertEqual(collection.state, "pending")
