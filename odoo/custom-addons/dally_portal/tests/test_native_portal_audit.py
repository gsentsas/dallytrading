# -*- coding: utf-8 -*-
"""Ce qu'un portail atteint via les ACL NATIVES d'Odoo, sans rien de DallyTrading.

Audit, pas correction. Odoo accorde de lui-même au groupe portail des accès sur
`sale.order`, `purchase.order`, `account.move` et `mail.message`, encadrés par ses
propres record rules. Ces tests mesurent la portée réelle de ces accès sur DES
DONNÉES DALLYTRADING, pour distinguer une exposition théorique d'une fuite.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally", "dally_portal")
class TestNativePortalAudit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        portal_group = cls.env.ref("base.group_portal")
        cls.company_a = Partner.create({"name": "NAT-A", "is_company": True})
        cls.company_b = Partner.create({"name": "NAT-B", "is_company": True})
        cls.user_a = cls.env["res.users"].create({
            "name": "NAT A1", "login": "nat.a1@portal-test.invalid",
            "partner_id": Partner.create({
                "name": "NAT A1", "parent_id": cls.company_a.id}).id,
            "group_ids": [(6, 0, [portal_group.id])],
        })
        # Une commande de vente et une commande d'achat rattachées à B.
        product = cls.env["product.product"].create({"name": "NAT produit", "type": "consu"})
        cls.so_b = cls.env["sale.order"].create({
            "partner_id": cls.company_b.id,
            "order_line": [(0, 0, {"product_id": product.id, "product_uom_qty": 1,
                                    "price_unit": 100.0})],
        })
        cls.po_b = cls.env["purchase.order"].create({
            "partner_id": cls.company_b.id,
            "order_line": [(0, 0, {"product_id": product.id, "product_qty": 1,
                                    "price_unit": 60.0,
                                    "name": "NAT", "date_planned": "2026-09-01"})],
        })

    def _reachable(self, model, domain=None):
        try:
            return self.env[model].with_user(self.user_a).search(domain or [])
        except AccessError:
            return None

    def test_audit_sale_order(self):
        found = self._reachable("sale.order")
        print(f"\n[AUDIT] sale.order    accessible={found is not None} "
              f"records={len(found) if found is not None else 'AccessError'}")
        if found is not None:
            self.assertNotIn(self.so_b, found,
                             "FUITE : un portail A voit la commande de vente de B")

    def test_audit_purchase_order(self):
        found = self._reachable("purchase.order")
        print(f"\n[AUDIT] purchase.order accessible={found is not None} "
              f"records={len(found) if found is not None else 'AccessError'}")
        if found is not None:
            self.assertNotIn(self.po_b, found,
                             "FUITE : un portail A voit la commande d'achat de B")

    def test_audit_account_move(self):
        found = self._reachable("account.move")
        print(f"\n[AUDIT] account.move  accessible={found is not None} "
              f"records={len(found) if found is not None else 'AccessError'}")

    def test_audit_mail_message(self):
        found = self._reachable("mail.message")
        n = len(found) if found is not None else "AccessError"
        print(f"\n[AUDIT] mail.message  accessible={found is not None} records={n}")
        if found is not None:
            models = set(found.mapped("model"))
            dally = sorted(m for m in models if m and m.startswith("dally."))
            print(f"[AUDIT] mail.message modèles dally atteints : {dally or 'aucun'}")
            self.assertFalse(
                dally, f"FUITE : messages internes lisibles sur {dally}")

    def test_audit_res_partner_scope(self):
        found = self._reachable("res.partner")
        n = len(found) if found is not None else "AccessError"
        print(f"\n[AUDIT] res.partner   accessible={found is not None} records={n}")
        if found is not None:
            self.assertNotIn(self.company_b, found,
                             "FUITE : un portail A voit le partenaire B")
