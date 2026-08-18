"""
La galerie : plusieurs photos par produit, et une seule porte pour y accéder.

Le jeu d'essai monte deux produits publiés parce que la propriété la plus
importante de ce fichier ne se prouve qu'à deux : un jeton valide pour un
produit ne doit rien donner sur un autre. Avec un seul produit, « le jeton est
vérifié » serait indémontrable — il n'y aurait rien à confondre.

Chaque photo porte une couleur différente, et les octets diffèrent donc
réellement. Quatre PNG identiques auraient la même empreinte, et les tests
d'ordre comme ceux de jeton auraient passé sans rien vérifier.
"""

import base64

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from ..models.product_template import MIMETYPES_IMAGE

#: Quatre PNG de 1×1 pixel, de couleurs distinctes.
ROUGE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
VERT = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC"
BLEU = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC"
JAUNE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4/58BAAT/Af9dfQKHAAAAAElFTkSuQmCC"

#: Réservé au **second** produit, et à lui seul.
#:
#: Le jeton étant l'empreinte du contenu, deux photos aux octets identiques
#: portent le même jeton — sur deux produits différents s'il le faut. Ce n'est
#: pas une faille : chaque produit sert alors sa propre copie, publique dans les
#: deux cas. Mais une fixture qui partagerait une photo entre les deux produits
#: rendrait le test de jeton croisé **incapable d'échouer**, et c'est
#: exactement ce qui s'est produit à la première exécution.
CYAN = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+P8fAAMBAf+2EqLVAAAAAElFTkSuQmCC"


@tagged("post_install", "-at_install", "dally_shop")
class TestGalerieProduit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.tarif = cls.env["product.pricelist"].create({
            "name": "Boutique — essai galerie",
            "item_ids": [(0, 0, {
                "compute_price": "fixed",
                "fixed_price": 150000.0,
                "applied_on": "3_global",
            })],
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(cls.tarif.id)
        )

        cls.produit = cls._produit("essai-gal-principal", publie=True, image=ROUGE)
        # Trois photos, créées volontairement dans le désordre : si la
        # projection rendait l'ordre de création, le test d'ordre passerait sans
        # que le tri existe.
        cls.photos = cls.env["dally.shop.product.image"].create([
            {"name": "Vue arrière", "sequence": 30,
             "product_tmpl_id": cls.produit.id, "image_1920": BLEU},
            {"name": "Intérieur", "sequence": 10,
             "product_tmpl_id": cls.produit.id, "image_1920": VERT},
            {"name": "Tableau de bord", "sequence": 20,
             "product_tmpl_id": cls.produit.id, "image_1920": JAUNE},
        ])

        cls.autre = cls._produit("essai-gal-autre", publie=True, image=VERT)
        cls.photo_autre = cls.env["dally.shop.product.image"].create({
            "name": "Photo de l'autre produit", "sequence": 10,
            "product_tmpl_id": cls.autre.id, "image_1920": CYAN,
        })

        cls.cache = cls._produit("essai-gal-cache", publie=False, image=ROUGE)
        cls.photo_cachee = cls.env["dally.shop.product.image"].create({
            "name": "Photo d'un produit non publié", "sequence": 10,
            "product_tmpl_id": cls.cache.id, "image_1920": BLEU,
        })

    @classmethod
    def _produit(cls, slug, publie, image):
        return cls.env["product.template"].create({
            "name": f"Produit {slug}",
            "type": "consu",
            "list_price": 999999.0,
            "dally_shop_slug": slug,
            "dally_published": publie,
            "image_1920": image,
        })

    def _projection(self, produit=None):
        produit = produit or self.produit
        return produit._dally_shop_projection(tarif=self.tarif, detail=True)[0]

    # ------------------------------------------------------------------
    # Contrôle positif
    # ------------------------------------------------------------------

    def test_les_photos_sont_bien_en_place(self):
        """Sans cette assertion, toutes les autres seraient vraies d'une base vide."""
        self.assertTrue(self.produit.image_1920)
        self.assertEqual(len(self.produit.dally_shop_image_ids), 3)
        self.assertTrue(all(p.image_1920 for p in self.produit.dally_shop_image_ids))
        # Les octets diffèrent réellement : c'est ce qui rend les tests de jeton
        # et d'ordre capables d'échouer.
        empreintes = {p.image_1920 for p in self.produit.dally_shop_image_ids}
        self.assertEqual(len(empreintes), 3)

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def test_photo_principale_et_galerie_coexistent(self):
        projection = self._projection()

        self.assertIsInstance(projection["imageVersion"], str)
        self.assertEqual(len(projection["gallery"]), 3)

    def test_la_galerie_respecte_la_sequence(self):
        """L'ordre vient de `sequence`, pas de l'ordre de création.

        Les trois photos ont été créées dans l'ordre 30, 10, 20 précisément pour
        que ce test échoue si le tri disparaissait.
        """
        galerie = self._projection()["gallery"]

        self.assertEqual([p["sequence"] for p in galerie], [10, 20, 30])

    def test_la_photo_principale_n_est_pas_dans_la_galerie(self):
        """Pas de double vérité sur la même image.

        La vitrine place `image_1920` en première position elle-même. La
        recopier ici la ferait apparaître deux fois le jour où quelqu'un
        ajouterait aussi la photo principale à la galerie.
        """
        projection = self._projection()
        jetons_galerie = {p["reference"] for p in projection["gallery"]}

        self.assertNotIn(projection["imageVersion"], jetons_galerie)

    def test_le_catalogue_ne_porte_pas_la_galerie(self):
        """La galerie n'existe que sur la fiche.

        Trente jetons voyageraient dans la charge d'une page qui n'affiche
        qu'une image par tuile. L'absence de la clé en liste rend l'erreur
        impossible plutôt que déconseillée.
        """
        liste = self.produit._dally_shop_projection(tarif=self.tarif)[0]

        self.assertNotIn("gallery", liste)
        self.assertIn("imageVersion", liste)

    def test_aucun_identifiant_technique_dans_la_projection(self):
        projection = self._projection()
        entier = str(projection)

        self.assertNotIn("product.template", entier)
        self.assertNotIn("dally.shop.product.image", entier)
        self.assertNotIn("image_1920", entier)
        self.assertNotIn("/web/image", entier)
        for photo in self.produit.dally_shop_image_ids:
            # L'identifiant de base de chaque photo est absent des jetons. Le
            # test compare des valeurs entières et non des sous-chaînes : un
            # identifiant à deux chiffres se trouve dans un hexadécimal une fois
            # sur deux, ce qui rendrait l'assertion aléatoire.
            self.assertNotIn(
                str(photo.id), [p["reference"] for p in projection["gallery"]]
            )

    def test_aucun_octet_d_image_dans_la_projection(self):
        projection = self._projection()
        entier = str(projection)

        for image in (ROUGE, VERT, BLEU, JAUNE):
            self.assertNotIn(image[:40], entier)
        self.assertNotIn("data:image", entier)
        for photo in projection["gallery"]:
            self.assertLessEqual(len(photo["reference"]), 32)

    def test_la_legende_interne_ne_sort_pas(self):
        """Le nom de la photo est un repère de back-office, pas un texte public.

        Il n'a jamais été rédigé pour être lu par un client — « Photo d'un
        produit non publié » en est l'illustration dans ce fichier même.
        """
        entier = str(self._projection())

        for legende in ("Vue arrière", "Intérieur", "Tableau de bord"):
            self.assertNotIn(legende, entier)

    # ------------------------------------------------------------------
    # Versions
    # ------------------------------------------------------------------

    def test_meme_image_meme_jeton(self):
        avant = self._projection()["gallery"]
        encore = self._projection()["gallery"]

        self.assertEqual(
            [p["reference"] for p in avant], [p["reference"] for p in encore]
        )

    def test_image_changee_jeton_change(self):
        avant = self._projection()["gallery"]
        self.photos[0].image_1920 = ROUGE
        apres = self._projection()["gallery"]

        self.assertNotEqual(
            sorted(p["reference"] for p in avant),
            sorted(p["reference"] for p in apres),
            "le jeton doit suivre le contenu, sinon l'ancienne photo reste "
            "affichée jusqu'à ce que chaque visiteur vide son cache",
        )

    # ------------------------------------------------------------------
    # Service des octets
    # ------------------------------------------------------------------

    def _jetons(self, produit=None):
        return [p["reference"] for p in self._projection(produit)["gallery"]]

    def test_photo_principale_servie(self):
        resultat = self.env["product.template"]._dally_shop_image("essai-gal-principal")

        self.assertIsNotNone(resultat)
        octets, mimetype = resultat
        self.assertEqual(mimetype, "image/png")
        self.assertEqual(octets[:8], base64.b64decode(ROUGE)[:8])

    def test_les_trois_photos_de_galerie_sont_servies(self):
        P = self.env["product.template"]
        servies = []
        for jeton in self._jetons():
            resultat = P._dally_shop_image("essai-gal-principal", "detail", jeton)
            self.assertIsNotNone(resultat, f"jeton {jeton} non servi")
            servies.append(resultat[0])

        self.assertEqual(len(servies), 3)
        # Trois photos distinctes, pas trois fois la même : sans cette
        # assertion, un bug rendant toujours la première passerait inaperçu.
        self.assertEqual(len({bytes(o) for o in servies}), 3)

    def test_la_photo_principale_et_la_galerie_different(self):
        P = self.env["product.template"]
        principale = P._dally_shop_image("essai-gal-principal")[0]
        premiere = P._dally_shop_image(
            "essai-gal-principal", "card", self._jetons()[0]
        )[0]

        self.assertNotEqual(principale, premiere)

    def test_jeton_inconnu_refuse(self):
        P = self.env["product.template"]

        self.assertIsNone(
            P._dally_shop_image("essai-gal-principal", "card", "0000000000000000")
        )

    def test_jeton_d_un_autre_produit_refuse(self):
        """La propriété centrale : un jeton n'est pas une clé globale.

        Le jeton de l'autre produit est valide — il désigne bien une photo
        existante et publiée. Il ne doit rien donner ici, parce que la recherche
        est bornée aux photos du produit demandé.
        """
        P = self.env["product.template"]
        jeton_autre = self._jetons(self.autre)[0]

        self.assertTrue(jeton_autre)
        self.assertIsNotNone(
            P._dally_shop_image("essai-gal-autre", "card", jeton_autre),
            "contrôle positif : ce jeton fonctionne sur son propre produit",
        )
        self.assertIsNone(
            P._dally_shop_image("essai-gal-principal", "card", jeton_autre)
        )

    def test_identifiant_de_base_refuse_comme_jeton(self):
        """L'identifiant de la photo n'ouvre rien.

        C'est l'attaque que le jeton ferme : passer un entier là où une
        empreinte est attendue, et compter sur une recherche par clé primaire.
        """
        P = self.env["product.template"]
        for photo in self.produit.dally_shop_image_ids:
            self.assertIsNone(
                P._dally_shop_image("essai-gal-principal", "card", str(photo.id))
            )

    def test_produit_non_publie_ne_sert_aucune_photo(self):
        """La dépublication coupe la galerie entière, immédiatement."""
        P = self.env["product.template"]
        jeton = self._jetons(self.cache) if self.cache.dally_published else None
        # Le produit étant non publié, sa projection est vide : on prend donc
        # l'empreinte directement, ce qui donne au test un jeton *authentique*.
        from ..models.product_template import empreintes_image
        empreintes = empreintes_image(
            self.env, "dally.shop.product.image", self.photo_cachee.ids
        )
        vrai_jeton = empreintes[self.photo_cachee.id]

        self.assertTrue(vrai_jeton)
        self.assertIsNone(P._dally_shop_image("essai-gal-cache"))
        self.assertIsNone(P._dally_shop_image("essai-gal-cache", "card", vrai_jeton))
        self.assertIsNone(jeton)

    def test_depublication_coupe_la_galerie_a_l_instant(self):
        P = self.env["product.template"]
        jeton = self._jetons()[0]
        self.assertIsNotNone(P._dally_shop_image("essai-gal-principal", "card", jeton))

        self.produit.dally_published = False

        self.assertIsNone(P._dally_shop_image("essai-gal-principal", "card", jeton))
        self.assertIsNone(P._dally_shop_image("essai-gal-principal"))

    def test_sans_regle_de_tarif_aucune_photo(self):
        """L'image suit la visibilité du catalogue, galerie comprise."""
        P = self.env["product.template"]
        jeton = self._jetons()[0]
        tarif_vide = self.env["product.pricelist"].create({"name": "Sans règle"})
        self.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(tarif_vide.id)
        )
        self.addCleanup(
            self.env["ir.config_parameter"].sudo().set_param,
            "dally_shop.pricelist_id", str(self.tarif.id),
        )

        self.assertIsNone(P._dally_shop_image("essai-gal-principal"))
        self.assertIsNone(P._dally_shop_image("essai-gal-principal", "card", jeton))

    def test_produit_inconnu_refuse(self):
        P = self.env["product.template"]
        jeton = self._jetons()[0]

        self.assertIsNone(P._dally_shop_image("essai-slug-jamais-existe"))
        self.assertIsNone(
            P._dally_shop_image("essai-slug-jamais-existe", "card", jeton)
        )

    def test_photo_inactive_disparait(self):
        """`active = False` retire la photo sans la supprimer.

        Le jeton reste calculable — la pièce jointe existe toujours — mais la
        photo n'est plus dans la galerie du produit, donc la comparaison ne
        trouve rien.
        """
        P = self.env["product.template"]
        jeton = self._jetons()[0]
        self.assertIsNotNone(P._dally_shop_image("essai-gal-principal", "card", jeton))

        self.photos.filtered(lambda p: p.sequence == 10).active = False

        self.assertEqual(len(self._projection()["gallery"]), 2)
        self.assertIsNone(P._dally_shop_image("essai-gal-principal", "card", jeton))

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def test_le_svg_est_hors_liste_blanche(self):
        """Un SVG est un document XML capable de porter du script.

        Le champ image d'Odoo le refuse déjà à l'écriture ; la liste blanche
        ferme le cas où il arriverait par un autre chemin.
        """
        self.assertNotIn("image/svg+xml", MIMETYPES_IMAGE)
        self.assertNotIn("text/html", MIMETYPES_IMAGE)

    def test_le_svg_est_refuse_des_l_enregistrement(self):
        """La porte d'entrée est fermée, et il a fallu la fermer.

        Mesuré à la première exécution : `fields.Image` d'Odoo **accepte** un
        SVG et le stocke. Seule la liste blanche appliquée au moment de servir
        le refusait — le visiteur n'aurait jamais vu l'image, mais la personne
        qui l'a déposée aurait vu sa photo enregistrée et introuvable sur le
        site, sans explication.

        La contrainte du modèle refuse donc à l'écriture, là où l'erreur peut
        encore être corrigée.
        """
        svg = base64.b64encode(
            b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>'
        ).decode()
        with self.assertRaises(ValidationError):
            self.env["dally.shop.product.image"].create({
                "name": "Tentative SVG",
                "product_tmpl_id": self.produit.id,
                "image_1920": svg,
            })

    def test_le_html_est_refuse_aussi(self):
        html = base64.b64encode(b"<!doctype html><script>alert(1)</script>").decode()
        with self.assertRaises(ValidationError):
            self.env["dally.shop.product.image"].create({
                "name": "Tentative HTML",
                "product_tmpl_id": self.produit.id,
                "image_1920": html,
            })

    def test_un_png_reste_accepte(self):
        """Contrôle négatif de la contrainte : elle ne refuse pas tout.

        Sans lui, une contrainte qui lèverait systématiquement ferait passer les
        deux tests précédents tout en cassant la galerie.
        """
        photo = self.env["dally.shop.product.image"].create({
            "name": "Photo valide",
            "product_tmpl_id": self.produit.id,
            "image_1920": CYAN,
        })
        self.assertTrue(photo.image_1920)

    def test_le_type_vient_des_octets(self):
        P = self.env["product.template"]
        octets, mimetype = P._dally_shop_image(
            "essai-gal-principal", "card", self._jetons()[0]
        )

        self.assertEqual(mimetype, "image/png")
        self.assertEqual(octets[:8], b"\x89PNG\r\n\x1a\n")
