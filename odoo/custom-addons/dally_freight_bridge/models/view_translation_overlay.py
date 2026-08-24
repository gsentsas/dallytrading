"""French UI overlay for translatable tk_freight view architectures."""

from odoo import models


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    def dally_apply_tk_freight_fr_overlay(self):
        """Correct reviewed vendor wording without changing en_US or behaviour."""
        language = self.env["res.lang"].search(
            [("code", "=", "fr_FR"), ("active", "=", True)], limit=1
        )
        # A new Odoo database does not necessarily enable French before module
        # installation. The next bridge update after language activation will
        # apply this idempotent overlay; a translated ORM write now would fail.
        if not language:
            return True

        menu_labels = (
            ("tk_freight.freight_root", "Gestion du fret"),
            ("tk_freight.dasboard_id", "Tableau de bord"),
            ("tk_freight.menu_shipment_quot", "Cotations"),
            ("tk_freight.freight_house_freight_booking", "Réservations"),
            ("tk_freight.menu_freight_shipment", "Expéditions"),
            ("tk_freight.freight_all_operation", "Toutes les expéditions"),
            ("tk_freight.freight_air_operation", "Aérien"),
            ("tk_freight.freight_ocean_operation", "Maritime"),
            ("tk_freight.freight_land_operation", "Terrestre"),
            ("tk_freight.menu_freight_package_id", "Colis"),
            ("tk_freight.menu_freight_invoicing", "Facturation"),
            ("tk_freight.menu_policy_company", "Compagnie d’assurance"),
            ("tk_freight.menu_freight_archive", "Archives"),
            ("tk_freight.menu_consignee_customer", "Clients"),
            ("tk_freight.menu_shipper", "Expéditeurs"),
            ("tk_freight.menu_consignee", "Destinataires"),
            ("tk_freight.menu_vendors", "Fournisseurs"),
            ("tk_freight.menu_agent", "Agents"),
            ("tk_freight.menu_partner_vendors", "Fournisseurs"),
            ("tk_freight.menu_partner_notify", "Parties à notifier"),
            ("tk_freight.menu_fleet", "Flotte"),
            ("tk_freight.menu_land", "Terrestre"),
            ("tk_freight.menu_fleet_details", "Véhicules"),
            ("tk_freight.menu_ocean", "Maritime"),
            ("tk_freight.menu_freight_vessel_id", "Navires"),
            ("tk_freight.menu_air", "Aérien"),
            ("tk_freight.menu_freight_airline_id", "Compagnies aériennes"),
            ("tk_freight.menu_services", "Services"),
            ("tk_freight.freight_configuration", "Configuration"),
            ("tk_freight.menu_port_locations", "Ports / emplacements"),
            ("tk_freight.menu_freight_port_id", "Ports / emplacements"),
            ("tk_freight.menu_freight_frequent_route", "Itinéraires fréquents"),
            ("tk_freight.menu_other_details", "Autres paramètres"),
            ("tk_freight.menu_freight_move_type_id", "Types de mouvement"),
            ("tk_freight.menu_freight_document_type_id", "Types de documents"),
            ("tk_freight.menu_freight_incoterms_id", "Incoterms"),
            ("tk_freight.menu_stages_details", "Étapes"),
            ("tk_freight.menu_stages", "Étapes"),
            ("tk_freight.menu_policy_details", "Assurance"),
            ("tk_freight.menu_policy_risk", "Risques assurés"),
            ("tk_freight.menu_shipment_tracking", "Suivi des expéditions"),
            ("tk_freight.menu_shipment_tracking_location", "Lieux de suivi"),
            ("tk_freight.menu_shipment_tracking_activity", "Activités de suivi"),
            ("tk_freight.menu_shipment_tracking_template", "Modèles de suivi"),
            ("tk_freight.menu_freight_statement", "Relevés de règlement"),
            ("tk_freight.menu_freight_invoice_receivable", "Factures clients"),
            ("tk_freight.menu_freight_invoice_payable", "Factures fournisseurs"),
        )
        for xmlid, label in menu_labels:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                menu.with_context(lang="fr_FR").write({"name": label})

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
