"""
Ce qui doit être vrai avant d'ouvrir la boutique.

Trois questions, mesurées séparément :

* une boutique **fermée** se distingue-t-elle d'une boutique **cassée** ?
* un produit publié dont le prix n'a pas été décidé est-il refusé ?
* l'amorçage complète-t-il une configuration absente sans jamais écraser une
  décision existante ?

La troisième est celle qui protège le propriétaire : un hook qui réécrirait le
tarif à chaque déploiement rendrait toute décision commerciale intenable.
"""

from odoo.tests import TransactionCase, tagged

from ..hooks import CLE_TARIF, post_init_hook
from ..models.product_template import ShopPricelistInvalid, ShopPricelistMissing

PRIX_LISTE = 777777.0
PRIX_REGLE = 42000.0


@tagged("post_install", "-at_install", "dally_shop")
class TestBoutiqueFermee(TransactionCase):
    """Fermée volontairement, cassée, ou ouverte : trois états, trois signaux."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.parametre = cls.env["ir.config_parameter"].sudo()
        cls.Produit = cls.env["product.template"]

    def test_aucun_tarif_configure_leve_pricelist_missing(self):
        """L'état d'une boutique qu'on n'a pas ouverte.

        Ce n'est pas une panne, et le code le dit : c'est ce qui permet à la page
        d'afficher « en préparation » plutôt que « momentanément indisponible ».
        """
        self.parametre.set_param(CLE_TARIF, "")
        with self.assertRaises(ShopPricelistMissing):
            self.Produit._dally_shop_pricelist()

    def test_parametre_absent_leve_aussi_pricelist_missing(self):
        """Paramètre jamais écrit, et non pas vide : même situation.

        Les deux formes existent — `set_param("")` et l'absence de ligne — et
        l'installation produit la seconde.
        """
        self.env["ir.config_parameter"].sudo().search(
            [("key", "=", CLE_TARIF)]
        ).unlink()
        with self.assertRaises(ShopPricelistMissing):
            self.Produit._dally_shop_pricelist()

    def test_espaces_seuls_comptent_comme_absence(self):
        # Une valeur composée d'espaces est une non-configuration, pas une
        # configuration cassée : personne n'a choisi de tarif.
        self.parametre.set_param(CLE_TARIF, "   ")
        with self.assertRaises(ShopPricelistMissing):
            self.Produit._dally_shop_pricelist()

    def test_tarif_supprime_leve_pricelist_invalid(self):
        """Quelqu'un a décidé d'ouvrir, et la configuration est cassée.

        Traité comme une panne, pas comme une boutique fermée : sinon la vitrine
        s'annoncerait « en préparation » indéfiniment et personne ne la réparerait.
        """
        self.parametre.set_param(CLE_TARIF, "999999999")
        with self.assertRaises(ShopPricelistInvalid):
            self.Produit._dally_shop_pricelist()

    def test_valeur_non_numerique_leve_pricelist_invalid(self):
        self.parametre.set_param(CLE_TARIF, "pas-un-identifiant")
        with self.assertRaises(ShopPricelistInvalid):
            self.Produit._dally_shop_pricelist()

    def test_les_deux_exceptions_ne_se_confondent_pas(self):
        """Contrôle explicite : aucune n'est sous-classe de l'autre.

        Sans cela, un `except ShopPricelistInvalid` attraperait aussi la boutique
        fermée — ou l'inverse — et les deux écrans redeviendraient un seul.
        """
        self.assertFalse(issubclass(ShopPricelistMissing, ShopPricelistInvalid))
        self.assertFalse(issubclass(ShopPricelistInvalid, ShopPricelistMissing))

    def test_un_tarif_valide_est_rendu(self):
        # Contrôle positif : sans lui, « ça lève toujours » passerait pour correct.
        tarif = self.env["product.pricelist"].create({"name": "Essai go-live"})
        self.parametre.set_param(CLE_TARIF, str(tarif.id))
        self.assertEqual(self.Produit._dally_shop_pricelist(), tarif)


@tagged("post_install", "-at_install", "dally_shop")
class TestPrixSansRepli(TransactionCase):
    """Aucun produit n'est servi à son prix de liste.

    Le repli d'Odoo est réel et a été mesuré : sur un tarif sans règle applicable,
    `_get_product_price` rend le `list_price` du produit, sans rien signaler. La
    boutique doit donc vérifier qu'une **règle** s'est appliquée, et non se
    contenter d'avoir un tarif.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sans_regle = cls.env["product.pricelist"].create({
            "name": "Essai — tarif sans regle",
        })
        cls.avec_regle = cls.env["product.pricelist"].create({
            "name": "Essai — tarif avec regle",
            "item_ids": [(0, 0, {
                "compute_price": "fixed", "fixed_price": PRIX_REGLE,
                "applied_on": "3_global",
            })],
        })
        cls.produit = cls.env["product.template"].create({
            "name": "Article go-live",
            "type": "consu",
            "list_price": PRIX_LISTE,
            "dally_shop_slug": "essai-golive-article",
            "dally_published": True,
        })

    def _selectionner(self, tarif):
        self.env["ir.config_parameter"].sudo().set_param(CLE_TARIF, str(tarif.id))

    def test_odoo_retombe_bien_sur_le_prix_de_liste(self):
        """Contrôle positif du piège lui-même.

        Sans ce test, la protection pourrait porter sur un comportement d'Odoo qui
        n'existe pas — et les autres tests passeraient pour de bonnes raisons
        imaginaires.
        """
        montant, regle = self.sans_regle._get_product_price_rule(self.produit, 1.0)
        self.assertEqual(montant, PRIX_LISTE)
        self.assertFalse(regle)

    def test_sans_regle_le_produit_na_pas_de_prix(self):
        self._selectionner(self.sans_regle)
        self.assertEqual(self.produit._dally_shop_price(), {})

    def test_avec_regle_le_prix_vient_de_la_regle(self):
        self._selectionner(self.avec_regle)
        self.assertEqual(
            self.produit._dally_shop_price(), {self.produit.id: PRIX_REGLE}
        )

    def test_sans_regle_le_produit_nest_pas_projete(self):
        self._selectionner(self.sans_regle)
        self.assertEqual(self.produit._dally_shop_projection(), [])

    def test_sans_regle_la_fiche_repond_comme_un_produit_inconnu(self):
        """Le même ensemble vide qu'une référence inventée.

        Comparaison de valeurs et non de deux échecs : rien ne distingue les cas.
        """
        self._selectionner(self.sans_regle)
        Produit = self.env["product.template"]
        sans_prix = Produit._dally_shop_find("essai-golive-article")
        inconnu = Produit._dally_shop_find("essai-golive-jamais-cree")
        self.assertFalse(sans_prix)
        self.assertEqual(sans_prix, inconnu)

    def test_avec_regle_la_fiche_repond(self):
        # Contrôle négatif du précédent.
        self._selectionner(self.avec_regle)
        self.assertEqual(
            self.env["product.template"]._dally_shop_find("essai-golive-article"),
            self.produit,
        )

    def test_sans_regle_la_commande_est_refusee(self):
        """Le contrôle vaut aussi à la commande, pas seulement à l'affichage.

        Un panier vit trente jours : sa référence peut avoir perdu sa règle de
        tarif entre la mise au panier et la validation.
        """
        self._selectionner(self.sans_regle)
        with self.assertRaises(ValueError) as refus:
            self.env["product.template"]._dally_shop_resolve_lines(
                [("essai-golive-article", 1)]
            )
        self.assertIn("unavailable_products", str(refus.exception))

    def test_avec_regle_la_commande_passe(self):
        self._selectionner(self.avec_regle)
        lignes = self.env["product.template"]._dally_shop_resolve_lines(
            [("essai-golive-article", 2)]
        )
        self.assertEqual(lignes, [(self.produit, 2)])

    def test_le_prix_de_liste_napparait_jamais(self):
        """Balayage : ni dans la projection, ni dans un montant rendu."""
        import json

        self._selectionner(self.avec_regle)
        corpus = json.dumps(self.produit._dally_shop_projection(detail=True), default=str)
        self.assertNotIn(str(int(PRIX_LISTE)), corpus)
        self.assertIn(str(int(PRIX_REGLE)), corpus)


@tagged("post_install", "-at_install", "dally_shop")
class TestAmorcage(TransactionCase):
    """L'amorçage complète, il ne corrige jamais."""

    def setUp(self):
        super().setUp()
        self.parametre = self.env["ir.config_parameter"].sudo()
        self.tarif_module = self.env.ref("dally_shop.pricelist_dally_shop")

    def test_le_tarif_du_module_existe_et_est_en_xof(self):
        self.assertTrue(self.tarif_module)
        self.assertEqual(self.tarif_module.name, "Boutique DallyTrading")
        self.assertEqual(self.tarif_module.currency_id.name, "XOF")

    def test_le_tarif_du_module_na_aucune_regle(self):
        """Volontaire, et c'est le cœur de la sûreté de prix.

        Une règle livrée par le code serait un montant que personne n'a validé.
        Sans règle, aucun produit n'est vendable — la boutique existe et reste
        fermée jusqu'à une décision commerciale.
        """
        self.assertEqual(len(self.tarif_module.item_ids), 0)

    def test_un_choix_existant_nest_jamais_ecrase(self):
        autre = self.env["product.pricelist"].create({"name": "Choix du proprietaire"})
        self.parametre.set_param(CLE_TARIF, str(autre.id))
        post_init_hook(self.env)
        self.assertEqual(self.parametre.get_param(CLE_TARIF), str(autre.id))

    def test_un_parametre_vide_est_complete(self):
        self.parametre.set_param(CLE_TARIF, "")
        post_init_hook(self.env)
        self.assertEqual(
            self.parametre.get_param(CLE_TARIF), str(self.tarif_module.id)
        )

    def test_lamorcage_ne_publie_aucun_produit(self):
        avant = self.env["product.template"].search_count([("dally_published", "=", True)])
        post_init_hook(self.env)
        self.assertEqual(
            self.env["product.template"].search_count([("dally_published", "=", True)]),
            avant,
        )

    def test_lamorcage_ne_cree_aucune_regle_de_prix(self):
        post_init_hook(self.env)
        self.assertEqual(len(self.tarif_module.item_ids), 0)

    def test_lamorcage_est_rejouable(self):
        """Deux passages laissent exactement le même état."""
        self.parametre.set_param(CLE_TARIF, "")
        post_init_hook(self.env)
        premier = self.parametre.get_param(CLE_TARIF)
        post_init_hook(self.env)
        self.assertEqual(self.parametre.get_param(CLE_TARIF), premier)
        self.assertEqual(len(self.tarif_module.item_ids), 0)

    def test_les_identites_dintegration_existent_sans_mot_de_passe(self):
        """Versionnables parce qu'elles ne portent aucun secret.

        Un compte sans mot de passe ne peut pas se connecter : ces identités ne
        servent qu'à porter les groupes qui bornent une clé d'API. Le secret de la
        clé, lui, est engendré dans Odoo et n'existe nulle part dans le dépôt.
        """
        for xmlid, login in (
            ("dally_shop.user_dally_shop_read", "dally_api_shop_read"),
            ("dally_shop.user_dally_shop_checkout", "dally_api_shop_checkout"),
        ):
            utilisateur = self.env.ref(xmlid)
            self.assertEqual(utilisateur.login, login)
            self.assertTrue(utilisateur.active)
            self.assertFalse(utilisateur.share)
            self.assertFalse(utilisateur.password)

    def test_les_deux_identites_sont_distinctes(self):
        # Une identité partagée annulerait la séparation des capacités au niveau
        # qui compte : la vitrine pourrait créer des commandes.
        lecture = self.env.ref("dally_shop.user_dally_shop_read")
        commande = self.env.ref("dally_shop.user_dally_shop_checkout")
        self.assertNotEqual(lecture, commande)

    def test_aucune_cle_dapi_nest_livree_par_le_module(self):
        """Le module ne crée jamais de clé : elle porte un secret.

        Le contrôle porte sur les données du module, pas sur la base : une clé
        créée à la main par le propriétaire est normale.
        """
        cles_du_module = self.env["ir.model.data"].search([
            ("module", "=", "dally_shop"),
            ("model", "=", "dally.api.key"),
        ])
        self.assertFalse(cles_du_module)
