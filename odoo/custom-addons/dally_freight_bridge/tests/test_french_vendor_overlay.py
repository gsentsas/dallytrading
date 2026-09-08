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


@tagged("post_install", "-at_install", "dally_freight")
class TestRepairVendorSourceArch(TransactionCase):
    """La réparation de la source anglaise abîmée.

    Le correctif empêche que l'overlay réécrive `en_US` ; il ne défait pas ce
    qui a déjà été écrit. Cinq vues du fournisseur, en production, portent du
    français dans leur langue source.

    Ce test reproduit la panne, puis la répare, puis vérifie les deux langues.
    Reproduire compte autant que réparer : sans cela, on ne saurait pas que le
    remède agit sur le bon mal.
    """

    _VUE = "tk_freight.freight_shipment_form_view"

    def setUp(self):
        super().setUp()
        self.vue = self.env.ref(self._VUE, raise_if_not_found=False)
        if not self.vue:
            self.skipTest("tk_freight absent de cette base")

    def _abimer_la_source(self):
        """Reproduit l'ÉTAT que porte la production, pas la manœuvre qui l'a créé.

        Écrire un seul terme dans le contexte français ne suffit pas à salir
        `en_US` — mesuré : la valeur anglaise reste intacte. La corruption est
        née d'une réécriture en bloc de l'architecture, sur une base où
        l'alignement des termes ne tenait plus, et je ne sais pas la rejouer
        fidèlement.

        Ce qui compte pour valider le remède est l'état d'arrivée, et il est
        connu précisément : cinq vues portent du français dans leur langue
        source, « Cotationss » sur ce formulaire. On l'écrit donc directement,
        et on répare.
        """
        anglais = self.vue.with_context(lang="en_US")
        anglais.write({"arch_db": anglais.arch_db.replace(
            'string="Quotations"', 'string="Cotationss"')})

    def test_une_source_abimee_est_rendue_au_fournisseur(self):
        self.assertIn('string="Address Type"',
                      self.vue.with_context(lang="en_US").arch_db)

        self._abimer_la_source()
        self.assertIn(
            'string="Cotationss"',
            self.vue.with_context(lang="en_US").arch_db,
            "l'état à réparer doit bien être en place, sinon le test ne prouve rien",
        )

        # --- le remède ---
        reparees = self.env["ir.ui.view"]._dally_repair_tk_freight_source_arch()
        self.assertIn(self._VUE, reparees)

        anglais_apres = self.vue.with_context(lang="en_US").arch_db
        self.assertNotIn('string="Cotationss"', anglais_apres)
        self.assertIn('string="Address Type"', anglais_apres)

    def test_le_francais_survit_a_la_reparation(self):
        self.env["ir.ui.view"].dally_apply_tk_freight_fr_overlay()
        self._abimer_la_source()
        self.env["ir.ui.view"]._dally_repair_tk_freight_source_arch()
        # La remise à zéro efface les traductions ; l'overlay est rejoué dans la
        # foulée, donc l'écran reste français.
        arch_fr = self.vue.with_context(lang="fr_FR").arch_db
        self.assertIn('string="Type d’adresse"', arch_fr)
        self.assertIn('string="Date de création"', arch_fr)

    def test_sur_une_base_saine_la_reparation_ne_touche_rien(self):
        self.env["ir.ui.view"].dally_apply_tk_freight_fr_overlay()
        anglais = self.vue.with_context(lang="en_US").arch_db
        francais = self.vue.with_context(lang="fr_FR").arch_db

        self.assertEqual(
            self.env["ir.ui.view"]._dally_repair_tk_freight_source_arch(), [],
            "rien à réparer ne doit rien réparer")
        self.assertEqual(self.vue.with_context(lang="en_US").arch_db, anglais)
        self.assertEqual(self.vue.with_context(lang="fr_FR").arch_db, francais)

    def test_la_reparation_n_est_pas_appelable_par_rpc(self):
        # Le souligné n'est pas décoratif : Odoo refuse d'exposer une méthode
        # privée aux appels distants. Réparer une base est un geste
        # d'exploitation, pas un bouton.
        self.assertFalse(
            hasattr(self.env["ir.ui.view"], "dally_repair_tk_freight_source_arch"),
            "aucun nom public ne doit subsister",
        )
        self.assertTrue(
            hasattr(self.env["ir.ui.view"], "_dally_repair_tk_freight_source_arch"))

    def test_une_divergence_sans_marqueur_n_est_jamais_reinitialisee(self):
        """Le fail-closed de la réparation.

        `reset_arch(mode="hard")` réécrit tout depuis le fichier du module :
        sans précondition, cette méthode effacerait n'importe quelle divergence,
        y compris légitime, et deviendrait un « remets tout comme à
        l'installation ». Une vue qui diffère du fichier sans porter de marqueur
        de corruption doit donc rester intacte.
        """
        anglais = self.vue.with_context(lang="en_US")
        anglais.write({"arch_db": anglais.arch_db.replace(
            'string="Barcode"', 'string="Barcode "')})
        divergente = self.vue.with_context(lang="en_US").arch_db

        self.assertEqual(
            self.env["ir.ui.view"]._dally_repair_tk_freight_source_arch(), [],
            "sans marqueur de corruption, aucune vue ne doit être touchée")
        self.assertEqual(self.vue.with_context(lang="en_US").arch_db, divergente,
                         "la divergence légitime survit à la réparation")

    def test_la_liste_des_vues_reparables_est_fermee_aux_trois_constatees(self):
        from odoo.addons.dally_freight_bridge.models.view_translation_overlay import (
            TK_CORRUPTION_MARKERS, TK_REPAIRABLE_VIEWS,
        )
        self.assertEqual(len(TK_REPAIRABLE_VIEWS), 3)
        self.assertIn("tk_freight.freight_shipment_form_view", TK_REPAIRABLE_VIEWS)
        # « Maritime » est de l'anglais légitime chez le fournisseur : le
        # retenir comme marqueur avait fait compter cinq vues au lieu de trois.
        self.assertNotIn("Maritime", TK_CORRUPTION_MARKERS)
