"""
La projection publique : sa liste blanche, et le stock qu'elle ne chiffre pas.

Ce fichier est séparé de `test_publication` parce qu'il répond à une autre
question. Là, il s'agissait de savoir *quels* produits sortent ; ici, de savoir
*ce qui* sort d'un produit — et un test qui mélangerait les deux laisserait
croire qu'une bonne réponse à la première vaut pour la seconde.

La méthode est celle du reste du dépôt : planter des canaris dans les champs
sensibles, prouver d'abord qu'ils existent, puis balayer la projection entière
plutôt que les seules clés auxquelles on pense.
"""

import json

from odoo.tests import TransactionCase, tagged

CANARI_COUT = 424242.42
CANARI_NOTE = "DALLY_SHOP_CANARY_INTERNAL_NOTE"
CANARI_FOURNISSEUR = "DALLY_SHOP_CANARY_SUPPLIER_UNIT"


@tagged("post_install", "-at_install", "dally_shop")
class TestProjectionCatalogue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.tarif = cls.env["product.pricelist"].create({
            "name": "Boutique — essai projection",
            "item_ids": [(0, 0, {
                "compute_price": "fixed",
                "fixed_price": 90000.0,
                "applied_on": "3_global",
            })],
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(cls.tarif.id)
        )

        cls.categorie = cls.env["dally.shop.category"].create({
            "name": "Pièces détachées",
            "slug": "essai-cat-pieces",
            "published": True,
        })
        cls.categorie_fermee = cls.env["dally.shop.category"].create({
            "name": "Réservé interne",
            "slug": "essai-cat-reservee",
            "published": False,
        })

        cls.fournisseur = cls.env["res.partner"].create({
            "name": CANARI_FOURNISSEUR,
            "supplier_rank": 1,
        })

        cls.sur_commande = cls.env["product.template"].create({
            "name": "Filtre à huile",
            "type": "consu",
            "list_price": 777777.0,
            "standard_price": CANARI_COUT,
            "description": CANARI_NOTE,
            "description_sale": "Filtre compatible moteurs 4 cylindres.",
            "dally_shop_slug": "essai-filtre-huile",
            "dally_shop_summary": "Filtre à huile toutes marques.",
            "dally_published": True,
            "dally_stock_policy": "on_order",
            "dally_shop_category_id": cls.categorie.id,
            "seller_ids": [(0, 0, {
                "partner_id": cls.fournisseur.id,
                "price": 12000.0,
            })],
        })

        cls.suivi = cls.env["product.template"].create({
            "name": "Courroie de distribution",
            "type": "consu",
            "is_storable": True,
            "list_price": 555555.0,
            "dally_shop_slug": "essai-courroie",
            "dally_published": True,
            "dally_stock_policy": "managed",
            "dally_shop_category_id": cls.categorie.id,
        })

        cls.categorie_cachee = cls.env["product.template"].create({
            "name": "Pièce en préparation",
            "type": "consu",
            "dally_shop_slug": "essai-piece-preparation",
            "dally_published": True,
            "dally_shop_category_id": cls.categorie_fermee.id,
        })

    # ------------------------------------------------------------------
    # Contrôle positif
    # ------------------------------------------------------------------

    def test_les_donnees_sensibles_existent_bien(self):
        interne = self.sur_commande.sudo().read(
            ["standard_price", "description", "list_price"]
        )[0]
        self.assertEqual(interne["standard_price"], CANARI_COUT)
        self.assertIn(CANARI_NOTE, interne["description"])
        self.assertEqual(interne["list_price"], 777777.0)
        self.assertEqual(
            self.sur_commande.seller_ids.partner_id.name, CANARI_FOURNISSEUR
        )

    # ------------------------------------------------------------------
    # Liste blanche
    # ------------------------------------------------------------------

    def test_la_projection_ne_contient_que_les_cles_declarees(self):
        """Balayage par égalité d'ensembles, pas par présence.

        Vérifier que chaque clé attendue est là laisserait passer une clé
        supplémentaire ajoutée par un module tiers. Comparer les ensembles fait
        échouer le test le jour où quelque chose s'ajoute — ce qui est exactement
        le moment où quelqu'un doit décider si ça peut être public.
        """
        projection = self.sur_commande._dally_shop_projection()[0]
        self.assertEqual(
            set(projection),
            {"reference", "name", "summary", "price", "currency",
             "stockPolicy", "stockPolicyLabel", "availability", "category"},
        )

    def test_le_detail_ajoute_deux_cles_et_pas_plus(self):
        projection = self.sur_commande._dally_shop_projection(detail=True)[0]
        self.assertEqual(
            set(projection),
            {"reference", "name", "summary", "price", "currency",
             "stockPolicy", "stockPolicyLabel", "availability", "category",
             "description", "unit"},
        )

    def test_aucun_canari_dans_la_projection(self):
        """Balayage textuel de la projection sérialisée.

        Sérialiser puis chercher, plutôt qu'inspecter clé par clé : un canari
        caché dans une valeur imbriquée — le nom d'une catégorie, un libellé —
        échapperait à une inspection de surface.
        """
        serialise = json.dumps(
            self.sur_commande._dally_shop_projection(detail=True), default=str
        )
        self.assertNotIn(CANARI_NOTE, serialise)
        self.assertNotIn(CANARI_FOURNISSEUR, serialise)
        self.assertNotIn("424242", serialise)
        self.assertNotIn("777777", serialise)

    def test_aucun_identifiant_de_base_dans_la_projection(self):
        """Ni l'`id` du produit, ni celui de la catégorie.

        Le contrôle porte sur les valeurs et non sur les clés : `{"id": 42}`
        serait attrapé par le test précédent, mais `{"reference": 42}` non.
        """
        projection = self.sur_commande._dally_shop_projection(detail=True)[0]
        valeurs = [projection["reference"], projection["category"]["reference"]]
        for valeur in valeurs:
            self.assertIsInstance(valeur, str)
        self.assertNotIn("id", projection)
        self.assertNotIn(str(self.sur_commande.id), projection["reference"])

    # ------------------------------------------------------------------
    # Stock
    # ------------------------------------------------------------------

    def test_sur_commande_ne_publie_aucune_quantite(self):
        """La disponibilité est qualitative.

        « 12 en stock » est une information sur les volumes d'achat, que la
        concurrence lit aussi bien que le client. Et en `on_order`, elle serait
        fausse : l'article est approvisionné après la commande.
        """
        projection = self.sur_commande._dally_shop_projection()[0]
        self.assertEqual(projection["stockPolicy"], "on_order")
        self.assertEqual(projection["availability"], "on_order")
        self.assertEqual(projection["stockPolicyLabel"], "Sur commande")
        serialise = json.dumps(projection, default=str)
        self.assertNotIn("qty", serialise)

    def test_stock_suivi_dit_epuise_sans_donner_le_nombre(self):
        projection = self.suivi._dally_shop_projection()[0]
        self.assertEqual(projection["stockPolicy"], "managed")
        self.assertEqual(projection["availability"], "out_of_stock")

    def test_stock_suivi_dit_disponible_apres_reception(self):
        """Contrôle négatif du précédent : faire bouger le stock et vérifier.

        Sans lui, « épuisé » serait la seule réponse que le code sait produire, et
        le test précédent réussirait sur une implémentation constante.
        """
        self.env["stock.quant"].sudo().create({
            "product_id": self.suivi.product_variant_id.id,
            "location_id": self.env.ref("stock.stock_location_stock").id,
            "quantity": 7.0,
        })
        self.suivi.invalidate_recordset()
        projection = self.suivi._dally_shop_projection()[0]
        self.assertEqual(projection["availability"], "in_stock")
        self.assertNotIn("7", json.dumps(projection, default=str))

    # ------------------------------------------------------------------
    # Catégorie
    # ------------------------------------------------------------------

    def test_categorie_non_publiee_absente_de_la_projection(self):
        """Une catégorie fermée ne doit pas fuir par le produit publié.

        Le cas se présente pendant la préparation d'une gamme : la catégorie
        n'est pas encore annoncée, les produits le sont déjà. Son nom est une
        information commerciale — il dit ce qui arrive.
        """
        projection = self.categorie_cachee._dally_shop_projection()[0]
        self.assertIsNone(projection["category"])
        self.assertNotIn("Réservé interne", json.dumps(projection, default=str))

    def test_le_compteur_de_categorie_ne_compte_que_le_publie(self):
        self.categorie.invalidate_recordset()
        self.assertEqual(self.categorie.product_count, 2)
        self.sur_commande.dally_published = False
        self.categorie.invalidate_recordset()
        self.assertEqual(self.categorie.product_count, 1)

    def test_filtre_par_categorie(self):
        catalogue = self.env["product.template"]._dally_shop_search(
            categorie_slug="essai-cat-pieces"
        )
        self.assertIn(self.sur_commande, catalogue)
        self.assertNotIn(self.categorie_cachee, catalogue)

    # ------------------------------------------------------------------
    # Ordre
    # ------------------------------------------------------------------

    def test_ordre_stable_a_sequence_egale(self):
        """Deux visites successives donnent le même ordre.

        À séquence égale, `name` puis `id` tranchent. Sans ce dernier départage,
        deux produits homonymes s'échangeraient de place au gré du plan
        d'exécution PostgreSQL — et une pagination deviendrait incohérente.
        """
        self.suivi.dally_shop_sequence = 5
        premier = self.env["product.template"]._dally_shop_search()
        second = self.env["product.template"]._dally_shop_search()
        self.assertEqual(premier.ids, second.ids)
        self.assertEqual(premier[0], self.suivi)
