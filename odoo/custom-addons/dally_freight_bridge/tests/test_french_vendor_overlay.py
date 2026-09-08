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

        self.assertEqual(
            self.env.ref("tk_freight.menu_freight_package_id")
            .with_context(lang="fr_FR").name,
            "Colis",
        )


@tagged("post_install", "-at_install", "dally_freight")
class TestFrenchShipmentScreen(TransactionCase):
    """L'écran Expéditions, en français, et rien de cassé en anglais.

    Le fournisseur livre bien un catalogue français ; il est incomplet et
    parfois faux. Ces tests fixent les deux moitiés du problème : ce qui restait
    en anglais, et ce qui était traduit de travers. Ils fixent aussi ce qu'il ne
    faut surtout pas casser — la source anglaise, qui reste la référence du
    fournisseur.
    """

    #: Libellés absents du catalogue du fournisseur : ils s'affichaient en
    #: anglais sur un écran par ailleurs francisé.
    _RESTAIENT_EN_ANGLAIS = (
        "Address Type", "Agent Details", "Freight Insurance", "Statements",
        "Storage", "Estimate Pickup", "Estimate Arrival", "Chargeable Weight",
        "Gross Weight(KG)", "Net Weight(KG)", "Volume(CBM)", "MAWB No.",
        "Voyage No.", "Truck Ref", "Ship Owner", "Warehouse", "Street",
        "Safety and Handling", "Logistics and Compliance",
    )

    #: Traductions fautives du fournisseur. « Create Date » arrivait en
    #: « créer un rendez-vous » sur un champ date : c'est le pire des cas, une
    #: phrase plausible qui décrit autre chose.
    _TRADUCTIONS_FAUTIVES = (
        "créer un rendez-vous",
        "Type de déplacement",
        "Estimer l’heure de prise en charge",
        "Estimer l’heure d’arrivée",
    )

    def setUp(self):
        super().setUp()
        self.env["ir.ui.view"].dally_apply_tk_freight_fr_overlay()
        self.vue = self.env.ref(
            "tk_freight.freight_shipment_form_view", raise_if_not_found=False)

    def test_plus_aucun_libelle_anglais_dans_l_ecran_expeditions(self):
        if not self.vue:
            self.skipTest("tk_freight absent de cette base")
        arch_fr = self.vue.with_context(lang="fr_FR").arch_db
        for libelle in self._RESTAIENT_EN_ANGLAIS:
            with self.subTest(libelle=libelle):
                self.assertNotIn('string="%s"' % libelle, arch_fr)

    def test_les_traductions_fautives_sont_remplacees(self):
        if not self.vue:
            self.skipTest("tk_freight absent de cette base")
        arch_fr = self.vue.with_context(lang="fr_FR").arch_db
        for fautif in self._TRADUCTIONS_FAUTIVES:
            with self.subTest(fautif=fautif):
                self.assertNotIn('string="%s"' % fautif, arch_fr)

    def test_les_libelles_de_champs_sont_corriges(self):
        attendus = (
            ("freight.shipment", "create_datetime", "Date de création"),
            ("freight.shipment", "shipper_id", "Expéditeur"),
            ("freight.shipment", "pickup_datetime", "Enlèvement estimé"),
            ("freight.shipment", "move_type", "Type d’acheminement"),
            ("freight.shipment", "freight_packages", "Colis"),
        )
        Field = self.env["ir.model.fields"].sudo()
        for model_name, field_name, libelle in attendus:
            with self.subTest(champ="%s.%s" % (model_name, field_name)):
                champ = Field.search(
                    [("model", "=", model_name), ("name", "=", field_name)], limit=1)
                if not champ:
                    self.skipTest("%s absent" % model_name)
                self.assertEqual(
                    champ.with_context(lang="fr_FR").field_description, libelle)

    def test_la_source_anglaise_reste_intacte(self):
        if not self.vue:
            self.skipTest("tk_freight absent de cette base")
        arch_en = self.vue.with_context(lang="en_US").arch_db
        # Le fournisseur doit retrouver son écran mot pour mot.
        for libelle in ("Address Type", "Freight Insurance", "Create Date"):
            self.assertIn('string="%s"' % libelle, arch_en)
        champ = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "freight.shipment"), ("name", "=", "create_datetime")],
            limit=1)
        if champ:
            self.assertEqual(
                champ.with_context(lang="en_US").field_description, "Create Date")

    def test_l_overlay_est_idempotent(self):
        if not self.vue:
            self.skipTest("tk_freight absent de cette base")
        premier = self.vue.with_context(lang="fr_FR").arch_db
        self.env["ir.ui.view"].dally_apply_tk_freight_fr_overlay()
        self.env["ir.ui.view"].dally_apply_tk_freight_fr_overlay()
        self.assertEqual(self.vue.with_context(lang="fr_FR").arch_db, premier,
                         "une seconde passe ne doit plus rien changer")
