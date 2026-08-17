"""
La publication, et la seule chose qu'elle décide : ce qui est visible.

Le jeu d'essai monte quatre produits, parce que quatre questions distinctes se
posent et qu'un seul produit n'en couvrirait qu'une :

* un **publié**, pour que l'absence des autres soit une information et non un
  catalogue vide qui « réussirait » par accident ;
* un **non publié**, la situation par défaut ;
* un **archivé mais publié**, parce que `active` et `dally_published` sont deux
  champs et qu'oublier le premier laisserait un produit retiré du catalogue
  interne continuer à s'afficher au public ;
* un **publié sans catégorie**, pour que le catalogue ne dépende pas de la
  taxonomie.

Le contrôle positif est la raison d'être du premier : sans lui, chaque assertion
d'invisibilité serait satisfaite par une base vide.
"""

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

#: Marqueur planté dans un champ interne du produit publié.
#:
#: Le coût d'achat est le vrai enjeu de confidentialité d'un catalogue : il donne
#: la marge, donc la limite de négociation. On le cherche par une valeur
#: improbable, qu'aucun arrondi ne peut produire.
CANARI_COUT = 424242.42

#: Marqueur textuel, dans un champ que le public ne doit jamais lire.
CANARI_NOTE = "DALLY_SHOP_CANARY_INTERNAL_NOTE"


@tagged("post_install", "-at_install", "dally_shop")
class TestPublicationBoutique(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.categorie = cls.env["dally.shop.category"].create({
            "name": "Groupes électrogènes",
            "slug": "essai-cat-publiee",
            "published": True,
        })
        cls.categorie_fermee = cls.env["dally.shop.category"].create({
            "name": "Brouillon interne",
            "slug": "essai-cat-brouillon",
            "published": False,
        })

        cls.tarif = cls.env["product.pricelist"].create({
            "name": "Boutique — essai unitaire",
            "item_ids": [(0, 0, {
                "compute_price": "fixed",
                "fixed_price": 150000.0,
                "applied_on": "3_global",
            })],
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(cls.tarif.id)
        )

        cls.publie = cls._produit(
            "Groupe électrogène 5 kVA", slug="essai-groupe-5kva",
            publie=True, categorie=cls.categorie,
        )
        cls.non_publie = cls._produit(
            "Groupe électrogène 12 kVA", slug="essai-groupe-12kva",
            publie=False, categorie=cls.categorie,
        )
        cls.archive = cls._produit(
            "Groupe électrogène retiré", slug="essai-groupe-retire",
            publie=True, categorie=cls.categorie,
        )
        cls.archive.active = False
        cls.sans_categorie = cls._produit(
            "Onduleur 3 kVA", slug="essai-onduleur-3kva", publie=True, categorie=None,
        )

        # Canaris sur le produit publié : c'est celui dont la projection sort.
        cls.publie.write({
            "standard_price": CANARI_COUT,
            "description": CANARI_NOTE,
        })

    @classmethod
    def _produit(cls, nom, slug, publie, categorie):
        return cls.env["product.template"].create({
            "name": nom,
            "type": "consu",
            "list_price": 999999.0,
            "dally_shop_slug": slug,
            "dally_published": publie,
            "dally_shop_category_id": categorie.id if categorie else False,
            "dally_shop_summary": f"Résumé public de {nom}.",
        })

    # ------------------------------------------------------------------
    # Contrôle positif
    # ------------------------------------------------------------------

    def test_canaris_bien_plantes(self):
        """Avant toute assertion de fuite, prouver que la donnée existe.

        Sans ce test, « le coût n'apparaît pas » serait vrai d'un produit dont le
        coût est nul — c'est-à-dire de rien du tout.
        """
        interne = self.publie.sudo().read(["standard_price", "description"])[0]
        self.assertEqual(interne["standard_price"], CANARI_COUT)
        self.assertIn(CANARI_NOTE, interne["description"])

    # ------------------------------------------------------------------
    # Visibilité
    # ------------------------------------------------------------------

    def test_produit_publie_visible(self):
        catalogue = self.env["product.template"]._dally_shop_search()
        self.assertIn(self.publie, catalogue)

    def test_produit_non_publie_invisible(self):
        catalogue = self.env["product.template"]._dally_shop_search()
        self.assertNotIn(self.non_publie, catalogue)

    def test_produit_archive_invisible_meme_publie(self):
        """`active` et `dally_published` sont deux décisions séparées.

        Archiver un produit est la façon normale de le retirer de la circulation.
        Si le catalogue ne regardait que la publication, un produit archivé
        resterait en vitrine — et personne ne penserait à le dépublier d'abord.
        """
        self.assertTrue(self.archive.dally_published)
        self.assertFalse(self.archive.active)
        catalogue = self.env["product.template"]._dally_shop_search()
        self.assertNotIn(self.archive, catalogue)

    def test_produit_sans_categorie_reste_visible(self):
        """Le catalogue ne dépend pas de la taxonomie.

        Un produit publié sans catégorie doit se vendre : sinon la première mise
        en ligne échoue en silence, et l'explication — « il manque une
        catégorie » — n'apparaît nulle part.
        """
        catalogue = self.env["product.template"]._dally_shop_search()
        self.assertIn(self.sans_categorie, catalogue)

    # ------------------------------------------------------------------
    # Indiscernabilité
    # ------------------------------------------------------------------

    def test_non_publie_et_inconnu_sont_indiscernables(self):
        """Les deux recherches donnent exactement le même résultat.

        C'est plus fort que « les deux échouent » : on compare les deux valeurs
        de retour, donc rien ne distingue les cas — ni un ensemble vide d'un côté
        et une exception de l'autre, ni deux exceptions de types différents.
        """
        Produit = self.env["product.template"]
        non_publie = Produit._dally_shop_find("essai-groupe-12kva")
        inexistant = Produit._dally_shop_find("essai-slug-jamais-existe")
        self.assertFalse(non_publie)
        self.assertFalse(inexistant)
        self.assertEqual(non_publie, inexistant)

    def test_reference_non_textuelle_ne_leve_pas(self):
        """Le slug vient du réseau : ce n'est pas forcément une chaîne.

        Un entier passé à `search` produirait une comparaison SQL sur un champ
        texte, et une exception 500 plutôt qu'un 404.
        """
        Produit = self.env["product.template"]
        for valeur in (None, 0, self.publie.id, [], {}, True):
            self.assertFalse(Produit._dally_shop_find(valeur))

    def test_identifiant_de_base_ne_donne_pas_acces(self):
        """L'identifiant numérique n'est pas une clé publique.

        Le test est nommé d'après l'attaque qu'il ferme : passer l'`id` d'un
        produit non publié là où une référence est attendue.
        """
        Produit = self.env["product.template"]
        self.assertFalse(Produit._dally_shop_find(str(self.non_publie.id)))
        self.assertFalse(Produit._dally_shop_find(str(self.publie.id)))

    # ------------------------------------------------------------------
    # Cohérence de la publication
    # ------------------------------------------------------------------

    def test_publication_fermee_par_defaut(self):
        """Le défaut est mesuré, pas relu dans le code.

        Un produit créé sans mentionner la boutique — le cas de tous les produits
        existants, dont les quatre lignes de frais de `tk_freight`.
        """
        nu = self.env["product.template"].create({"name": "Ligne de frais interne"})
        self.assertFalse(nu.dally_published)
        self.assertEqual(nu.dally_stock_policy, "on_order")

    def test_publier_sans_slug_refuse(self):
        with self.assertRaises(ValidationError):
            self.env["product.template"].create({
                "name": "Produit sans adresse",
                "dally_published": True,
            })

    def test_slug_invalide_refuse(self):
        for mauvais in ("Majuscule", "avec espace", "accentué", "double--tiret",
                        "-debut", "fin-", "slash/dedans", "point.dedans"):
            with self.assertRaises(ValidationError, msg=f"slug accepté : {mauvais}"):
                self.env["product.template"].create({
                    "name": f"Essai {mauvais}",
                    "dally_shop_slug": mauvais,
                })

    def test_slug_reserve_refuse(self):
        """Un slug que le site utilise déjà pour une page fixe.

        `/boutique/panier` est un segment statique, et un segment statique gagne
        toujours contre un segment dynamique dans Next.js. Un produit nommé
        `panier` apparaîtrait donc au catalogue avec un lien menant au panier —
        symptôme déroutant, cause invisible. Le refus est au moment de la saisie.
        """
        from ..models.product_template import SLUGS_RESERVES

        self.assertIn("panier", SLUGS_RESERVES)
        for reserve in SLUGS_RESERVES:
            with self.assertRaises(ValidationError, msg=f"slug accepté : {reserve}"):
                self.env["product.template"].create({
                    "name": f"Produit {reserve}",
                    "dally_shop_slug": reserve,
                })

    def test_slug_proche_dun_reserve_reste_accepte(self):
        """Contrôle négatif : la réservation est exacte, pas un préfixe.

        Sans lui, « panier » pourrait être implémenté comme un `startswith` et
        interdirait `panier-solaire`, qui est un nom de produit légitime.
        """
        produit = self.env["product.template"].create({
            "name": "Panier solaire",
            "dally_shop_slug": "essai-panier-solaire",
        })
        self.assertEqual(produit.dally_shop_slug, "essai-panier-solaire")

    def test_slug_unique(self):
        from psycopg2 import IntegrityError
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["product.template"].create({
                    "name": "Doublon",
                    "dally_shop_slug": "essai-groupe-5kva",
                })

    # ------------------------------------------------------------------
    # Tarif
    # ------------------------------------------------------------------

    def test_prix_vient_du_tarif_pas_du_prix_de_liste(self):
        """Le prix affiché est celui décidé pour la vente publique.

        `list_price` vaut 999 999 sur toutes les fixtures, le tarif boutique
        150 000. Les deux valeurs sont volontairement éloignées : si la
        projection retombait sur le prix de liste, l'écart serait visible plutôt
        que noyé dans un arrondi.
        """
        projection = self.publie._dally_shop_projection()[0]
        self.assertEqual(projection["price"], 150000.0)
        self.assertNotEqual(projection["price"], self.publie.list_price)

    def test_sans_tarif_configure_la_boutique_refuse(self):
        """Fermé plutôt que devinant.

        La même règle que le mode de transport du fret : sans la donnée, on
        refuse. Afficher un prix que personne n'a validé serait pire qu'un refus
        — dont le 1 912 000 de l'artefact de test présent en production.
        """
        self.env["ir.config_parameter"].sudo().set_param("dally_shop.pricelist_id", "")
        with self.assertRaises(UserError):
            self.env["product.template"]._dally_shop_pricelist()

    def test_tarif_supprime_ne_fait_pas_tomber_la_boutique(self):
        """Un paramètre pointant vers un enregistrement disparu.

        `browse` sur un identifiant mort ne lève pas : sans `exists()`, le code
        obtiendrait un recordset fantôme et échouerait plus loin, dans le calcul
        du prix, avec un message sans rapport.
        """
        self.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", "999999999"
        )
        with self.assertRaises(UserError):
            self.env["product.template"]._dally_shop_pricelist()
