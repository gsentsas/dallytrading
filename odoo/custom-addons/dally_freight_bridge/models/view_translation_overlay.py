"""French UI overlay for translatable tk_freight view architectures."""

from odoo import models


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    def dally_apply_tk_freight_fr_overlay(self):
        """Correct reviewed vendor wording without changing en_US or behaviour."""
        replacements = (
            ("Cliente", "Client"), ("Clientes", "Clients"),
            ("Emballer", "Colis"), ("Paquets", "Colis"),
            ("Suivie", "Suivi"), ("Citation", "Cotations"),
            ("Atterrir", "Terrestre"), ("Océan", "Maritime"),
            ("Notifier", "Partie à notifier"),
            ("Société politique", "Compagnie d’assurance"),
            ("Risques politiques", "Risques assurés"),
            ("Expéditrices", "Expéditeurs"), ("Vendeuses", "Fournisseurs"),
        )
        xmlids = (
            "tk_freight.freight_shipment_form_view",
            "tk_freight.freight_booking_form_view",
            "tk_freight.shipment_quot_form_view",
            "tk_freight.shipment_package_line_view_form",
            "tk_freight.package_form_view", "tk_freight.package_tree_view",
            "tk_freight.freight_success", "tk_freight.portal_booking_create",
            "tk_freight.freight_quotation_inherit",
            "tk_freight.res_partner_form_inherit_view",
            "tk_freight.policy_risk_tree_view",
            "tk_freight.shipment_tracking_view_form",
            "tk_freight.shipment_tracking_template_view_form",
            "tk_freight.shipment_tracking_template_view_tree",
        )
        for xmlid in xmlids:
            view = self.env.ref(xmlid, raise_if_not_found=False)
            if not view:
                continue
            french_view = view.with_context(lang="fr_FR")
            arch = french_view.arch_db
            corrected = arch
            for source, target in replacements:
                corrected = corrected.replace(source, target)
            if corrected != arch:
                french_view.write({"arch_db": corrected})
        return True
