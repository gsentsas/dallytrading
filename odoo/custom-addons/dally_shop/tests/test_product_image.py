"""
L'image d'un produit : qui peut la voir, et ce que la projection en dit.

Le jeu d'essai monte cinq produits parce que cinq questions distinctes se posent
sur une seule et même image :

* **publié avec image** — le cas nominal, et le contrôle positif de tous les
  autres : sans lui, « l'image n'est pas servie » serait vrai d'une base vide ;
* **publié sans image** — le cas normal tant que le catalogue se remplit, celui
  qui doit produire un substitut et non une erreur ;
* **non publié, avec image** — la même image que le premier, sur un produit qui
  n'est pas en vente. C'est le cœur du fichier : deux produits portant des octets
  identiques, dont un seul est visible ;
* **archivé mais publié, avec image** — `active` et `dally_published` sont deux
  champs, et n'en vérifier qu'un laisserait l'image d'un produit retiré de la
  circulation continuer à être servie ;
* **publié, avec image, sans règle de tarif** — invisible au catalogue faute de
  prix décidé ; son image doit disparaître au même instant, sinon elle
  prouverait l'existence d'un produit que la vitrine n'affiche pas.
"""

import base64

from odoo.tests import TransactionCase, tagged

from ..models.product_template import (
    MIMETYPES_IMAGE,
    TAILLES_IMAGE,
)

#: Un PNG de 1×1 pixel, valide et minuscule.
#:
#: Vrai PNG et non octets arbitraires : le champ `fields.Image` d'Odoo vérifie
#: qu'il décode une image, et le code sous test déduit le type des octets. Des
#: octets bidons ne franchiraient ni l'un ni l'autre, et le test passerait pour
#: de mauvaises raisons.
PNG_1x1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
)

#: Un second PNG, différent du premier, pour prouver que le jeton de version
#: suit le contenu. 2×1 pixels : la seule chose qui compte est que les octets
#: diffèrent.
PNG_AUTRE = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAAFElEQVR42mNk+M+ADzCO"
    "KhhVAAQAAF0AAcVJZ7QAAAAASUVORK5CYII="
)


@tagged("post_install", "-at_install", "dally_shop")
class TestImageProduit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.tarif = cls.env["product.pricelist"].create({
            "name": "Boutique — essai image",
            "item_ids": [(0, 0, {
                "compute_price": "fixed",
                "fixed_price": 150000.0,
                "applied_on": "3_global",
            })],
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(cls.tarif.id)
        )

        cls.avec_image = cls._produit("essai-img-publie", publie=True, image=PNG_1x1)
        cls.sans_image = cls._produit("essai-img-sans", publie=True, image=None)
        cls.non_publie = cls._produit("essai-img-cache", publie=False, image=PNG_1x1)

        cls.archive = cls._produit("essai-img-archive", publie=True, image=PNG_1x1)
        cls.archive.active = False

        cls.non_vendable = cls._produit("essai-img-nonvente", publie=True, image=PNG_1x1)
        cls.non_vendable.sale_ok = False

    @classmethod
    def _produit(cls, slug, publie, image):
        return cls.env["product.template"].create({
            "name": f"Produit {slug}",
            "type": "consu",
            "list_price": 999999.0,
            "dally_shop_slug": slug,
            "dally_published": publie,
            **({"image_1920": image} if image else {}),
        })

    # ------------------------------------------------------------------
    # Contrôle positif
    # ------------------------------------------------------------------

    def test_les_images_sont_bien_en_place(self):
        """Avant toute assertion d'invisibilité, prouver que l'image existe.

        Sans ce test, « l'image du produit non publié n'est pas servie » serait
        vrai d'un produit qui n'a jamais eu d'image.
        """
        self.assertTrue(self.avec_image.image_1920)
        self.assertTrue(self.non_publie.image_1920)
        self.assertFalse(self.sans_image.image_1920)
        # Les deux portent les mêmes octets : seule la publication les sépare.
        self.assertEqual(self.avec_image.image_1920, self.non_publie.image_1920)

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def test_projection_porte_un_jeton_pas_des_octets(self):
        projection = self.avec_image._dally_shop_projection(tarif=self.tarif)[0]

        self.assertIsInstance(projection["imageVersion"], str)
        self.assertTrue(projection["imageVersion"])

    def test_projection_sans_image_annonce_none(self):
        """`None` est le signal qui fait afficher le substitut.

        Une chaîne vide serait une URL construite puis un 404 par tuile ; le
        `None` évite la requête entièrement.
        """
        projection = self.sans_image._dally_shop_projection(tarif=self.tarif)[0]

        self.assertIsNone(projection["imageVersion"])

    def test_aucun_octet_d_image_dans_la_projection(self):
        """Le test qui ferme la porte au base64 massif.

        Dix produits illustrés feraient plusieurs mégaoctets de JSON
        **retransmis à chaque affichage de page**, sans jamais être mis en cache
        par le navigateur puisqu'ils voyageraient dans un document dynamique.
        """
        projection = self.avec_image._dally_shop_projection(
            tarif=self.tarif, detail=True
        )[0]

        entier = str(projection)
        self.assertNotIn(PNG_1x1[:40], entier)
        self.assertNotIn("data:image", entier)
        # Le jeton reste court : c'est une adresse, pas un contenu.
        self.assertLessEqual(len(projection["imageVersion"]), 32)

    def test_projection_n_expose_ni_modele_ni_identifiant(self):
        projection = self.avec_image._dally_shop_projection(
            tarif=self.tarif, detail=True
        )[0]

        entier = str(projection)
        self.assertNotIn("product.template", entier)
        self.assertNotIn("image_1920", entier)
        self.assertNotIn("/web/image", entier)

    def test_le_jeton_derive_du_contenu_et_non_de_l_enregistrement(self):
        """Deux produits distincts portant la même image ont le même jeton.

        C'est la preuve que le jeton est une empreinte du contenu et non un
        dérivé de l'identifiant : deux enregistrements différents, un seul
        jeton. Chercher l'identifiant comme sous-chaîne du jeton ne prouverait
        rien et échouerait au hasard — un identifiant à deux chiffres se trouve
        dans un hexadécimal de seize caractères environ une fois sur deux, ce
        qu'une première version de ce test a effectivement rencontré.
        """
        versions = (self.avec_image | self.non_publie)._dally_shop_image_versions()

        self.assertEqual(
            versions[self.avec_image.id], versions[self.non_publie.id],
            "le jeton doit dépendre des octets, pas de l'enregistrement",
        )
        # Et il diffère dès que les octets diffèrent.
        autre = self._produit("essai-img-autre", publie=True, image=PNG_AUTRE)
        self.assertNotEqual(
            autre._dally_shop_image_versions()[autre.id],
            versions[self.avec_image.id],
        )

    def test_jeton_stable_puis_change_avec_l_image(self):
        """Toute la stratégie de cache tient à cette double propriété."""
        avant = self.avec_image._dally_shop_projection(tarif=self.tarif)[0]
        encore = self.avec_image._dally_shop_projection(tarif=self.tarif)[0]
        self.assertEqual(avant["imageVersion"], encore["imageVersion"])

        self.avec_image.image_1920 = PNG_AUTRE
        apres = self.avec_image._dally_shop_projection(tarif=self.tarif)[0]
        self.assertNotEqual(
            avant["imageVersion"], apres["imageVersion"],
            "le jeton doit suivre le contenu, sinon l'ancienne image reste "
            "affichée jusqu'à ce que chaque visiteur vide son cache",
        )

    def test_une_seule_requete_pour_tout_le_catalogue(self):
        """Le jeton ne doit pas coûter une lecture d'octets par produit.

        Le catalogue lit les empreintes dans la table des pièces jointes, en une
        requête. Lire le champ image aurait chargé les octets de chaque produit,
        à chaque affichage, pour n'en garder qu'un booléen.
        """
        catalogue = self.env["product.template"]._dally_shop_search()
        versions = catalogue._dally_shop_image_versions()

        self.assertIn(self.avec_image.id, versions)
        self.assertNotIn(self.sans_image.id, versions)
        # Non publié : absent du catalogue, donc jamais interrogé.
        self.assertNotIn(self.non_publie.id, versions)

    # ------------------------------------------------------------------
    # Service des octets
    # ------------------------------------------------------------------

    def test_image_servie_pour_un_produit_publie(self):
        resultat = self.env["product.template"]._dally_shop_image("essai-img-publie")

        self.assertIsNotNone(resultat)
        octets, mimetype = resultat
        self.assertEqual(mimetype, "image/png")
        self.assertTrue(octets.startswith(b"\x89PNG"))

    def test_non_publie_et_inconnu_sont_indiscernables(self):
        """Plus fort que « les deux échouent » : les deux valeurs sont comparées.

        Le produit non publié porte pourtant les mêmes octets que le publié. Si
        la publication n'était pas vérifiée ici, son image serait servie à qui
        devine son slug — et un slug se devine bien mieux qu'un identifiant.
        """
        Produit = self.env["product.template"]
        cache = Produit._dally_shop_image("essai-img-cache")
        inconnu = Produit._dally_shop_image("essai-slug-jamais-existe")

        self.assertIsNone(cache)
        self.assertIsNone(inconnu)
        self.assertEqual(cache, inconnu)

    def test_produit_archive_ne_sert_plus_son_image(self):
        self.assertTrue(self.archive.dally_published)
        self.assertFalse(self.archive.active)

        resultat = self.env["product.template"]._dally_shop_image("essai-img-archive")

        self.assertIsNone(resultat)

    def test_produit_non_vendable_ne_sert_plus_son_image(self):
        resultat = self.env["product.template"]._dally_shop_image("essai-img-nonvente")

        self.assertIsNone(resultat)

    def test_produit_publie_sans_image_repond_comme_un_inconnu(self):
        """« Pas d'image » ne se distingue pas de « pas publié ».

        Les distinguer suffirait à savoir qu'un produit existe : il suffirait de
        comparer la réponse d'un slug inventé à celle d'un slug supposé.
        """
        Produit = self.env["product.template"]

        self.assertIsNone(Produit._dally_shop_image("essai-img-sans"))
        self.assertEqual(
            Produit._dally_shop_image("essai-img-sans"),
            Produit._dally_shop_image("essai-slug-jamais-existe"),
        )

    def test_produit_sans_regle_de_tarif_ne_sert_pas_son_image(self):
        """L'image suit exactement la visibilité du catalogue.

        Un produit publié dont le prix n'a pas été décidé est écarté du
        catalogue. Servir son image prouverait son existence à qui devine son
        slug, alors que la vitrine ne le montre pas.
        """
        sans_prix = self._produit("essai-img-sansprix", publie=True, image=PNG_1x1)
        # Un tarif dont aucune règle ne s'applique à ce produit.
        tarif_vide = self.env["product.pricelist"].create({"name": "Sans règle"})
        self.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(tarif_vide.id)
        )
        self.addCleanup(
            self.env["ir.config_parameter"].sudo().set_param,
            "dally_shop.pricelist_id", str(self.tarif.id),
        )

        self.assertTrue(sans_prix.image_1920)
        self.assertIsNone(
            self.env["product.template"]._dally_shop_image("essai-img-sansprix")
        )

    # ------------------------------------------------------------------
    # Tailles
    # ------------------------------------------------------------------

    def test_les_deux_tailles_sont_servies(self):
        Produit = self.env["product.template"]
        for taille in TAILLES_IMAGE:
            resultat = Produit._dally_shop_image("essai-img-publie", taille)
            self.assertIsNotNone(resultat, f"taille {taille} non servie")
            self.assertEqual(resultat[1], "image/png")

    def test_taille_inconnue_retombe_sur_le_defaut(self):
        """Une dimension libre ferait redimensionner à la demande de l'extérieur.

        Le paramètre vient d'une URL : n'importe qui peut itérer de 1 à 4000, et
        chaque valeur inédite serait un calcul d'image et une entrée de cache.
        La liste est donc fermée, et ce qui n'y figure pas est ignoré plutôt que
        refusé — un refus ajouterait une surface d'erreur sans rien protéger.
        """
        Produit = self.env["product.template"]
        defaut = Produit._dally_shop_image("essai-img-publie", "card")
        for absurde in ("2048", "huge", "", None, "image_1920"):
            self.assertEqual(
                Produit._dally_shop_image("essai-img-publie", absurde), defaut
            )

    def test_les_tailles_ne_designent_que_des_champs_derives(self):
        """`image_1920` reste la source, et n'est jamais servie telle quelle.

        Servir l'original enverrait au navigateur une image de plusieurs
        mégaoctets là où 512 pixels suffisent à une tuile de catalogue.
        """
        self.assertNotIn("image_1920", TAILLES_IMAGE.values())
        for champ in TAILLES_IMAGE.values():
            self.assertIn(champ, self.env["product.template"]._fields)

    # ------------------------------------------------------------------
    # Types acceptés
    # ------------------------------------------------------------------

    def test_le_svg_est_hors_liste_blanche(self):
        """Un SVG est un document XML qui peut porter du script.

        Servi depuis notre origine, il s'exécuterait dans notre contexte. Le
        champ image d'Odoo le refuse déjà à l'écriture ; la liste blanche ferme
        le cas où il arriverait par un autre chemin.
        """
        self.assertNotIn("image/svg+xml", MIMETYPES_IMAGE)
        self.assertNotIn("text/html", MIMETYPES_IMAGE)
        self.assertIn("image/png", MIMETYPES_IMAGE)

    def test_le_type_vient_des_octets_pas_du_champ(self):
        """Le type est déduit du contenu, jamais déclaré.

        Un fichier nommé `photo.png` mais contenant du HTML serait servi en
        `text/html` depuis notre origine si l'on faisait confiance au nom.
        """
        resultat = self.env["product.template"]._dally_shop_image("essai-img-publie")
        octets, mimetype = resultat

        # Les octets commencent bien par la signature PNG, et c'est elle — non
        # une métadonnée — qui a décidé du type annoncé.
        self.assertEqual(octets[:8], base64.b64decode(PNG_1x1)[:8])
        self.assertEqual(mimetype, "image/png")
