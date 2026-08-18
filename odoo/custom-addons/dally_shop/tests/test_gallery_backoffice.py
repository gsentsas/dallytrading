"""
Qui peut gérer la galerie, et ce que la vue promet.

Ces tests sont nés d'un bug d'exploitation : la zone galerie s'affichait vide,
sans bouton d'ajout. La vue n'y était pour rien — l'utilisateur n'avait pas le
droit de créer, et le client web masque alors le contrôle. C'est le bon
comportement, mais rien ne le vérifiait, et rien ne vérifiait non plus que le
droit existe pour qui doit l'avoir.

D'où deux séries d'assertions :

* **les droits**, par groupe et par opération, avec le contrôle négatif que
  « Read Only » ne peut rien écrire — sans lui, « Commercial peut créer » serait
  vrai d'une ACL ouverte à tous ;
* **la vue**, dont on vérifie qu'elle porte un contrôle de création nommé. Une
  vignette fantôme sans libellé est indiscernable d'une zone vide, et c'est
  exactement ce qu'on a observé.
"""

import base64
import struct
import zlib
from lxml import etree

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


def _png(rgb):
    """Un PNG de 1×1 pixel de la couleur demandée.

    Généré plutôt que codé en dur : chaque appel donne des octets différents
    pour une couleur différente, ce qui rend distinguables des photos qui
    autrement partageraient la même empreinte.
    """
    brut = b"\x00" + bytes(rgb)

    def bloc(nom, donnees):
        corps = nom + donnees
        return (struct.pack(">I", len(donnees)) + corps
                + struct.pack(">I", zlib.crc32(corps) & 0xFFFFFFFF))

    return base64.b64encode(
        b"\x89PNG\r\n\x1a\n"
        + bloc(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + bloc(b"IDAT", zlib.compress(brut))
        + bloc(b"IEND", b"")
    ).decode()


@tagged("post_install", "-at_install", "dally_shop")
class TestGalerieBackoffice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Groupe = cls.env["res.groups"]
        interne = cls.env.ref("base.group_user")
        cls.g_commercial = Groupe.search([("name", "=", "Commercial")], limit=1)
        cls.g_manager = Groupe.search([("name", "=", "Manager")], limit=1)
        cls.g_lecture = Groupe.search([("name", "=", "Read Only")], limit=1)

        def utilisateur(login, groupe):
            return cls.env["res.users"].create({
                "name": login, "login": login,
                "group_ids": [(6, 0, [interne.id, groupe.id])],
            })

        cls.g_catalogue = cls.env.ref("dally_shop.group_dally_shop_catalog")
        cls.catalogue = utilisateur("gal.catalogue@essai.invalid", cls.g_catalogue)
        cls.commercial = utilisateur("gal.commercial@essai.invalid", cls.g_commercial)
        cls.responsable = utilisateur("gal.manager@essai.invalid", cls.g_manager)
        cls.lecture = utilisateur("gal.lecture@essai.invalid", cls.g_lecture)

        cls.produit = cls.env["product.template"].create({
            "name": "Camion de galerie",
            "type": "consu",
            "dally_shop_slug": "essai-galerie-backoffice",
            "image_1920": _png((255, 0, 0)),
        })
        cls.photo = cls.env["dally.shop.product.image"].create({
            "name": "Vue avant",
            "sequence": 10,
            "product_tmpl_id": cls.produit.id,
            "image_1920": _png((0, 255, 0)),
        })

    def _en_tant_que(self, utilisateur):
        return self.env["dally.shop.product.image"].with_user(utilisateur)

    # ------------------------------------------------------------------
    # Droits
    # ------------------------------------------------------------------

    def test_commercial_peut_creer(self):
        photo = self._en_tant_que(self.commercial).create({
            "name": "Ajoutée par un commercial",
            "product_tmpl_id": self.produit.id,
            "image_1920": _png((0, 0, 255)),
        })

        self.assertTrue(photo.id)
        self.assertEqual(photo.product_tmpl_id, self.produit)

    def test_commercial_peut_reordonner(self):
        """Réordonner, c'est écrire `sequence` : le geste le plus courant."""
        self._en_tant_que(self.commercial).browse(self.photo.id).write({"sequence": 99})

        self.photo.invalidate_recordset()
        self.assertEqual(self.photo.sequence, 99)

    def test_commercial_peut_supprimer(self):
        photo = self.env["dally.shop.product.image"].create({
            "name": "À supprimer",
            "product_tmpl_id": self.produit.id,
            "image_1920": _png((10, 10, 10)),
        })

        self._en_tant_que(self.commercial).browse(photo.id).unlink()

        self.assertFalse(photo.exists())

    def test_responsable_peut_tout_faire(self):
        M = self._en_tant_que(self.responsable)
        photo = M.create({
            "name": "Par le responsable",
            "product_tmpl_id": self.produit.id,
            "image_1920": _png((20, 20, 20)),
        })
        photo.write({"sequence": 5})
        photo.unlink()

        self.assertFalse(photo.exists())

    def test_lecture_seule_peut_lire(self):
        """Contrôle positif du groupe restreint.

        Sans lui, les trois refus qui suivent seraient vrais d'un groupe qui
        n'a aucun accès au modèle — et la galerie serait invisible plutôt que
        non modifiable.
        """
        lues = self._en_tant_que(self.lecture).search(
            [("product_tmpl_id", "=", self.produit.id)]
        )

        self.assertIn(self.photo, lues)

    def test_lecture_seule_ne_peut_ni_creer_ni_modifier_ni_supprimer(self):
        """C'est cette configuration qui masquait le bouton d'ajout.

        L'utilisateur qui gérait les produits appartenait à ce groupe : le
        client web cache le contrôle de création quand `create` est refusé, ce
        qui est correct — et donnait une zone galerie vide, sans explication.
        """
        L = self._en_tant_que(self.lecture)

        with self.assertRaises(AccessError):
            L.create({
                "name": "Interdite",
                "product_tmpl_id": self.produit.id,
                "image_1920": _png((30, 30, 30)),
            })
        with self.assertRaises(AccessError):
            L.browse(self.photo.id).write({"sequence": 1})
        with self.assertRaises(AccessError):
            L.browse(self.photo.id).unlink()

    # ------------------------------------------------------------------
    # Liaison au parent
    # ------------------------------------------------------------------

    def test_le_one2many_rattache_la_photo_au_produit(self):
        """Aucun `default_product_tmpl_id` n'est nécessaire, et c'est mesuré ici.

        La vue en portait un dans son contexte. Il ne servait à rien — l'ORM
        renseigne le champ inverse — et sa valeur `id` est fausse pour un
        produit pas encore enregistré. Ce test est ce qui autorise à l'avoir
        retiré.
        """
        self.produit.write({
            "dally_shop_image_ids": [
                (0, 0, {"name": "Par le o2m", "sequence": 40,
                        "image_1920": _png((40, 40, 40))}),
            ],
        })

        ajoutee = self.produit.dally_shop_image_ids.filtered(
            lambda p: p.name == "Par le o2m"
        )
        self.assertEqual(ajoutee.product_tmpl_id, self.produit)

    def test_une_photo_sans_produit_est_refusee(self):
        """Le parent n'est pas optionnel.

        Une photo orpheline n'apparaîtrait sur aucune fiche et ne serait
        emportée par aucune suppression de produit.
        """
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env["dally.shop.product.image"].create({
                    "name": "Orpheline", "image_1920": _png((50, 50, 50)),
                })

    def test_l_image_est_obligatoire_meme_si_le_champ_est_absent(self):
        """Le trou que ce test a révélé, et qui est maintenant fermé.

        `required=True` ne protège pas : `image_1920` est stocké en pièce
        jointe, donc sans colonne, donc sans `NOT NULL` possible. Et
        `@api.constrains` ne se déclenche que pour les champs présents dans les
        valeurs — passer `False` était refusé, **omettre le champ passait**, et
        la galerie gagnait une vignette morte.

        Les deux formes sont vérifiées : celle qui échouait déjà, et celle qui
        passait.
        """
        for libelle, valeurs in (
            ("champ absent", {"name": "Sans image",
                              "product_tmpl_id": self.produit.id}),
            ("champ à False", {"name": "Image vide",
                               "product_tmpl_id": self.produit.id,
                               "image_1920": False}),
        ):
            with self.assertRaises(ValidationError, msg=f"accepté : {libelle}"):
                with self.env.cr.savepoint():
                    self.env["dally.shop.product.image"].create(valeurs)

    def test_un_type_refuse_est_rejete(self):
        """SVG et HTML restent refusés, y compris depuis le back-office."""
        for nom, contenu in (
            ("SVG", b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>'),
            ("HTML", b"<!doctype html><script>alert(1)</script>"),
        ):
            with self.assertRaises(ValidationError, msg=f"{nom} accepté"):
                with self.env.cr.savepoint():
                    self.env["dally.shop.product.image"].create({
                        "name": f"Tentative {nom}",
                        "product_tmpl_id": self.produit.id,
                        "image_1920": base64.b64encode(contenu).decode(),
                    })

    # ------------------------------------------------------------------
    # La vue
    # ------------------------------------------------------------------

    def test_la_vue_porte_un_bouton_de_creation_nomme(self):
        """Le correctif d'ergonomie, vérifié sur l'architecture réelle.

        Sans `<control><create/></control>`, le kanban n'offre qu'une vignette
        fantôme sans libellé — indiscernable d'une zone vide, ce qui est
        précisément ce qui a été signalé.
        """
        vue = self.env.ref("dally_shop.product_template_view_form_dally_shop")
        arch = vue.arch

        self.assertIn("<control>", arch)
        self.assertIn("Ajouter des photos", arch)

    def _arch_sans_commentaires(self):
        """L'architecture analysée, commentaires retirés.

        Une première version de ces tests balayait le texte brut et échouait sur
        ses propres commentaires : la vue explique **pourquoi** elle n'a ni
        `default_product_tmpl_id` ni `sudo`, et ces mots y figurent donc. Chercher
        une chaîne dans un document commenté, c'est chercher dans la
        documentation autant que dans le code.
        """
        arbre = etree.fromstring(
            self.env.ref("dally_shop.product_template_view_form_dally_shop").arch
        )
        for commentaire in arbre.xpath("//comment()"):
            commentaire.getparent().remove(commentaire)
        return arbre

    def test_la_vue_n_impose_pas_le_produit_parent(self):
        """L'utilisateur ne choisit jamais `product_tmpl_id` à la main."""
        arbre = self._arch_sans_commentaires()

        self.assertEqual(arbre.xpath('//field[@name="product_tmpl_id"]'), [])
        contextes = " ".join(arbre.xpath("//@context"))
        self.assertNotIn("default_product_tmpl_id", contextes)

    def test_la_vue_n_utilise_aucun_sudo(self):
        arbre = self._arch_sans_commentaires()

        self.assertNotIn("sudo", etree.tostring(arbre, encoding="unicode"))

    def test_la_vue_est_rendue_pour_les_deux_groupes(self):
        """Le champ est présent quel que soit le droit d'écriture.

        C'est la contrepartie du diagnostic : la zone s'affiche pour tout le
        monde, seul le bouton dépend des droits. Un champ absent aurait été un
        tout autre problème.
        """
        for utilisateur in (self.commercial, self.lecture):
            vues = self.env["product.template"].with_user(utilisateur).get_views(
                [(None, "form")]
            )
            self.assertIn(
                "dally_shop_image_ids", vues["views"]["form"]["arch"],
                f"champ galerie absent pour {utilisateur.login}",
            )

    # ------------------------------------------------------------------
    # Le groupe étroit
    # ------------------------------------------------------------------

    def test_le_groupe_catalogue_gere_la_galerie(self):
        """Le groupe créé pour ce correctif fait exactement ce qu'on attend."""
        C = self._en_tant_que(self.catalogue)

        photo = C.create({
            "name": "Par le catalogue",
            "product_tmpl_id": self.produit.id,
            "image_1920": _png((60, 60, 60)),
        })
        photo.write({"sequence": 7})
        photo.unlink()

        self.assertFalse(photo.exists())

    def test_le_groupe_catalogue_gere_les_categories_sans_les_supprimer(self):
        """Créer et renommer, oui ; supprimer, non.

        Une catégorie est partagée entre produits : la retirer les déclasse tous
        à la fois. C'est déjà la règle retenue pour Commercial.
        """
        Cat = self.env["dally.shop.category"].with_user(self.catalogue)
        categorie = Cat.create({"name": "Véhicules", "slug": "essai-vehicules-cat"})
        categorie.write({"name": "Véhicules industriels"})

        with self.assertRaises(AccessError):
            categorie.unlink()

    def test_le_groupe_catalogue_n_ouvre_rien_d_autre(self):
        """La raison d'être du groupe : ce qu'il n'accorde pas.

        Passer par « Commercial » aurait donné l'écriture sur sept modèles
        métier — devis de fret, expéditions, colis, documents de portail — pour
        gérer des photos. Ces refus sont donc le cœur du correctif, pas un
        détail.
        """
        for modele in ("dally.quote.request", "dally.shipment",
                       "dally.shipment.event", "dally.shipment.package",
                       "dally.portal.document"):
            if modele not in self.env:
                continue
            M = self.env[modele].with_user(self.catalogue)
            # La lecture reste ouverte : le groupe implique Read Only.
            M.check_access("read")
            for interdit in ("write", "create"):
                with self.assertRaises(AccessError, msg=f"{modele}.{interdit} accordé"):
                    M.check_access(interdit)

    def test_le_groupe_catalogue_conserve_les_lectures(self):
        """`implied_ids` vers Read Only : le groupe ajoute, il ne retire rien."""
        self.assertIn(
            self.env.ref("dally_core.group_dally_readonly"),
            self.g_catalogue.implied_ids,
        )
