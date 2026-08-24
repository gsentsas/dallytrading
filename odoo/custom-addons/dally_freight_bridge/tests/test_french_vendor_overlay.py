"""Non-regression tests for the French tk_freight UI overlay."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally_freight")
class TestFrenchVendorOverlay(TransactionCase):
    """The bridge corrects vendor wording in French only.

    The licensed vendor module and its catalog deliberately remain untouched.
    This test ensures that a bridge update reapplies the reviewed French
    terminology while retaining the original English architecture.
    """

    _XMLIDS = (
        "tk_freight.freight_shipment_form_view",
        "tk_freight.freight_booking_form_view",
        "tk_freight.shipment_quot_form_view",
        "tk_freight.shipment_package_line_view_form",
        "tk_freight.package_form_view",
        "tk_freight.package_tree_view",
        "tk_freight.freight_success",
        "tk_freight.portal_booking_create",
        "tk_freight.freight_quotation_inherit",
        "tk_freight.res_partner_form_inherit_view",
        "tk_freight.policy_risk_tree_view",
        "tk_freight.shipment_tracking_view_form",
        "tk_freight.shipment_tracking_template_view_form",
        "tk_freight.shipment_tracking_template_view_tree",
    )
    _INCORRECT_FRENCH = (
        "Cliente", "Clientes", "Emballer", "Paquets", "Suivie", "Citation",
        "Atterrir", "Océan", "Notifier", "Société politique",
        "Risques politiques", "Expéditrices", "Vendeuses",
    )

    def test_l_overlay_fr_corrige_les_vues_sans_modifier_la_source_anglaise(self):
        self.env["ir.ui.view"].dally_apply_tk_freight_fr_overlay()

        for xmlid in self._XMLIDS:
            with self.subTest(xmlid=xmlid):
                view = self.env.ref(xmlid, raise_if_not_found=False)
                if not view:
                    continue
                french_arch = view.with_context(lang="fr_FR").arch_db
                for label in self._INCORRECT_FRENCH:
                    self.assertNotIn(label, french_arch)

        source_arch = self.env.ref(
            "tk_freight.freight_shipment_form_view"
        ).with_context(lang="en_US").arch_db
        self.assertIn("Customer", source_arch)
