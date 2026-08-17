"""
La commande boutique : identité, prix, idempotence, et ce qu'elle ne crée pas.

## Ce que le jeu d'essai monte

Un produit publié et vendable, un produit publié mais **non vendable**, un produit
**non publié**, un client portail avec compte, et un contact sans compte portant
une adresse connue. Chacun répond à une question distincte, et un jeu plus petit
laisserait des questions ouvertes en donnant l'illusion de les couvrir.

Le tarif boutique est réglé à un montant très éloigné du prix de liste des
produits. Ce n'est pas de la décoration : si un prix venait du prix de liste ou
d'une valeur envoyée par le navigateur, l'écart sauterait aux yeux au lieu de se
noyer dans un arrondi.

## Les canaris

Coût d'achat et note interne sur le produit commandé. Le coût donne la marge, donc
la limite de négociation : c'est le vrai enjeu de confidentialité d'un catalogue.
Chaque assertion d'absence est précédée d'un contrôle positif qui prouve que la
donnée existe — sans quoi « le coût ne fuit pas » serait vrai d'un produit dont le
coût est nul.
"""

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from odoo import api
from odoo.exceptions import ValidationError
from odoo.service.model import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
from odoo.sql_db import db_connect
from odoo.tests import TransactionCase, tagged

from ..models.shop_order import PortalAccountExists

CANARI_COUT = 424242.42
CANARI_NOTE = "DALLY_SHOP_CANARY_CHECKOUT_NOTE"

PRIX_TARIF = 150000.0
PRIX_LISTE = 999999.0


@tagged("post_install", "-at_install", "dally_shop")
class TestCheckoutBoutique(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.tarif = cls.env["product.pricelist"].create({
            "name": "Boutique — essai checkout",
            "item_ids": [(0, 0, {
                "compute_price": "fixed",
                "fixed_price": PRIX_TARIF,
                "applied_on": "3_global",
            })],
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(cls.tarif.id)
        )

        cls.vendable = cls._produit("essai-co-vendable", publie=True, vendable=True)
        cls.autre = cls._produit("essai-co-autre", publie=True, vendable=True)
        cls.non_vendable = cls._produit("essai-co-non-vendable", publie=True, vendable=False)
        cls.non_publie = cls._produit("essai-co-non-publie", publie=False, vendable=True)

        cls.vendable.write({
            "standard_price": CANARI_COUT,
            "description": CANARI_NOTE,
        })

        # Client avec compte portail.
        cls.partenaire_client = cls.env["res.partner"].create({
            "name": "Client Checkout Connecte",
            "email": "client.checkout@essai.invalid",
        })
        cls.utilisateur_client = cls.env["res.users"].create({
            "name": "Client Checkout Connecte",
            "login": "client.checkout@essai.invalid",
            "partner_id": cls.partenaire_client.id,
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })

        # Contact SANS compte portail, mais portant une adresse connue. C'est le
        # cas qui fait la différence entre « rapprocher par e-mail » et « demander
        # une connexion » : ici il n'y a pas de compte, donc rien à quoi se
        # connecter, et le rapprochement automatique serait une usurpation.
        cls.contact_sans_compte = cls.env["res.partner"].create({
            "name": "Contact Sans Compte",
            "email": "contact.sans.compte@essai.invalid",
        })

    @classmethod
    def _produit(cls, slug, publie, vendable):
        return cls.env["product.template"].create({
            "name": f"Produit {slug}",
            "type": "consu",
            "list_price": PRIX_LISTE,
            "sale_ok": vendable,
            "dally_shop_slug": slug,
            "dally_published": publie,
            "dally_shop_summary": f"Résumé de {slug}.",
        })

    @staticmethod
    def _identite(email="invite.checkout@essai.invalid"):
        return {
            "name": "Invité Checkout",
            "email": email,
            "phone": "+221 77 000 00 00",
            "street": "1 rue de l'Essai",
            "city": "Dakar",
            "zip": "11000",
            "country_code": "SN",
        }

    def _commander(self, lignes=None, partner=None, invite=False, cart=None, mode="pickup"):
        lignes = lignes or [("essai-co-vendable", 2)]
        resolues = self.env["product.template"]._dally_shop_resolve_lines(lignes)
        return self.env["sale.order"].dally_shop_place_order(
            cart or str(uuid.uuid4()),
            partner or self.partenaire_client,
            resolues,
            mode,
            invite=invite,
        )

    # ------------------------------------------------------------------
    # Contrôle positif
    # ------------------------------------------------------------------

    def test_canaris_bien_plantes(self):
        interne = self.vendable.sudo().read(["standard_price", "description", "list_price"])[0]
        self.assertEqual(interne["standard_price"], CANARI_COUT)
        self.assertIn(CANARI_NOTE, interne["description"])
        self.assertEqual(interne["list_price"], PRIX_LISTE)

    # ------------------------------------------------------------------
    # Client connecté
    # ------------------------------------------------------------------

    def test_checkout_client_connecte(self):
        commande = self._commander()
        self.assertEqual(commande.partner_id, self.partenaire_client)
        self.assertTrue(commande.dally_shop_order)
        self.assertFalse(commande.dally_shop_guest)
        self.assertEqual(commande.dally_shop_delivery_mode, "pickup")
        self.assertEqual(len(commande.order_line), 1)
        self.assertEqual(commande.order_line.product_uom_qty, 2)

    def test_la_commande_reste_en_brouillon(self):
        """Aucune confirmation automatique.

        Confirmer produirait des mouvements de stock et une obligation commerciale
        sur la seule foi d'un formulaire public.
        """
        commande = self._commander()
        self.assertEqual(commande.state, "draft")

    def test_aucune_facture_aucun_picking(self):
        """Ni facture, ni transfert — ce sont des conséquences de la confirmation.

        Le test est explicite plutôt qu'implicite dans « l'état reste draft » :
        un module tiers pourrait très bien créer un picking depuis un brouillon,
        et l'assertion sur l'état seule ne l'attraperait pas.
        """
        commande = self._commander()
        self.assertEqual(commande.invoice_ids, self.env["account.move"])
        self.assertEqual(commande.picking_ids, self.env["stock.picking"])
        self.assertEqual(commande.invoice_count, 0)
        self.assertEqual(commande.delivery_count, 0)

    def test_origine_boutique_structuree(self):
        """L'origine est un booléen, pas une sous-chaîne dans `origin`.

        Chercher « boutique » dans un champ libre marcherait jusqu'au jour où un
        client s'appellerait « Boutique du Port ».
        """
        commande = self._commander()
        boutique = self.env["sale.order"].search([("dally_shop_order", "=", True)])
        self.assertIn(commande, boutique)
        # Le champ libre n'est pas détourné.
        self.assertFalse(commande.origin)

    # ------------------------------------------------------------------
    # Invité
    # ------------------------------------------------------------------

    def test_checkout_invite_cree_un_contact_dedie(self):
        cart = str(uuid.uuid4())
        invite = self.env["res.partner"]._dally_shop_create_guest(cart, self._identite())
        commande = self._commander(partner=invite, invite=True, cart=cart)

        self.assertTrue(commande.dally_shop_guest)
        self.assertEqual(commande.partner_id, invite)
        self.assertEqual(invite.dally_shop_guest_cart_uuid, cart)
        self.assertEqual(invite.city, "Dakar")
        self.assertEqual(invite.country_id.code, "SN")
        # Un invité n'est pas un compte : aucun utilisateur ne lui est attaché.
        self.assertFalse(invite.user_ids)

    def test_invite_jamais_rapproche_par_egalite_demail(self):
        """Le point le plus important du fichier.

        Une adresse connue d'un contact existant **sans** compte portail ne donne
        pas accès à ce contact : un nouveau contact invité est créé. Sinon, la
        seule connaissance d'une adresse suffirait à faire atterrir une commande
        dans le dossier de quelqu'un d'autre.
        """
        cart = str(uuid.uuid4())
        invite = self.env["res.partner"]._dally_shop_create_guest(
            cart, self._identite(email=self.contact_sans_compte.email)
        )
        self.assertNotEqual(invite, self.contact_sans_compte)
        self.assertEqual(invite.email, self.contact_sans_compte.email)
        # Le contact d'origine n'a pas été touché.
        self.assertFalse(self.contact_sans_compte.dally_shop_guest_cart_uuid)

    def test_invite_sur_email_de_compte_portail_refuse(self):
        """Une adresse qui appartient à un compte : on demande la connexion.

        C'est le seul moyen de vérifier que c'est bien la même personne. Créer une
        seconde identité en silence dédoublerait le client dans l'ERP et
        laisserait ses commandes hors de son espace client.
        """
        cart = str(uuid.uuid4())
        with self.assertRaises(PortalAccountExists):
            self.env["res.partner"]._dally_shop_create_guest(
                cart, self._identite(email=self.utilisateur_client.login)
            )
        # Et rien n'a été créé au passage.
        self.assertFalse(self.env["res.partner"]._dally_shop_guest_for_cart(cart))

    def test_email_de_compte_portail_insensible_a_la_casse(self):
        """`=ilike` et non `=` : une adresse n'est pas sensible à la casse.

        Sans cela, `Client.Checkout@…` contournerait le contrôle et produirait un
        second client — exactement ce que le contrôle existe pour empêcher.
        """
        with self.assertRaises(PortalAccountExists):
            self.env["res.partner"]._dally_shop_create_guest(
                str(uuid.uuid4()),
                self._identite(email=self.utilisateur_client.login.upper()),
            )

    # ------------------------------------------------------------------
    # Revalidation du panier
    # ------------------------------------------------------------------

    def test_produit_non_publie_refuse(self):
        with self.assertRaises(ValueError) as refus:
            self.env["product.template"]._dally_shop_resolve_lines(
                [("essai-co-non-publie", 1)]
            )
        self.assertIn("unavailable_products", str(refus.exception))

    def test_produit_non_vendable_refuse(self):
        """`sale_ok` est une décision distincte de la publication.

        Un produit peut rester en vitrine pendant qu'on suspend sa vente. L'oubli
        produirait une commande qu'Odoo refuserait plus loin, à un endroit où le
        message n'a plus de rapport avec la cause.
        """
        with self.assertRaises(ValueError) as refus:
            self.env["product.template"]._dally_shop_resolve_lines(
                [("essai-co-non-vendable", 1)]
            )
        self.assertIn("unavailable_products", str(refus.exception))

    def test_le_refus_est_global_et_non_partiel(self):
        """Une seule référence en défaut fait échouer la commande entière.

        Retirer silencieusement la ligne fautive serait plus doux et pire : le
        client validerait un total qu'il n'a pas vu, pour un contenu qu'il n'a pas
        choisi.
        """
        with self.assertRaises(ValueError):
            self.env["product.template"]._dally_shop_resolve_lines(
                [("essai-co-vendable", 1), ("essai-co-non-publie", 1)]
            )
        self.assertFalse(
            self.env["sale.order"].search([("dally_shop_order", "=", True)])
        )

    def test_reference_inconnue_refusee(self):
        with self.assertRaises(ValueError):
            self.env["product.template"]._dally_shop_resolve_lines(
                [("essai-slug-jamais-cree", 1)]
            )

    def test_panier_vide_refuse(self):
        with self.assertRaises(ValueError) as refus:
            self.env["product.template"]._dally_shop_resolve_lines([])
        self.assertIn("empty_cart", str(refus.exception))

    # ------------------------------------------------------------------
    # Prix
    # ------------------------------------------------------------------

    def test_le_prix_vient_du_tarif_boutique(self):
        commande = self._commander(lignes=[("essai-co-vendable", 3)])
        self.assertEqual(commande.order_line.price_unit, PRIX_TARIF)
        self.assertNotEqual(commande.order_line.price_unit, PRIX_LISTE)
        self.assertEqual(commande.amount_untaxed, PRIX_TARIF * 3)
        self.assertEqual(commande.pricelist_id, self.tarif)

    def test_aucune_remise_posee(self):
        commande = self._commander()
        self.assertEqual(commande.order_line.discount, 0.0)

    def test_le_prix_est_recalcule_si_le_tarif_change(self):
        """Le montant vient d'Odoo et de maintenant, pas d'un instantané.

        Contrôle négatif du test précédent : sans lui, « le prix vaut 150 000 »
        serait vrai d'une implémentation qui recopierait une constante.
        """
        self.tarif.item_ids.fixed_price = 200000.0
        commande = self._commander()
        self.assertEqual(commande.order_line.price_unit, 200000.0)

    def test_un_prix_injecte_serait_ignore_par_le_calcul(self):
        """Même écrit, un prix est écrasé par le recalcul.

        Le contrôleur refuse déjà `price_unit` dans la charge. Ce test couvre
        l'étage suivant : si un appelant interne le passait quand même, le
        recalcul forcé le remplace. Deux barrières valent mieux qu'une, et celle-ci
        s'appuie sur `force_price_recomputation`, qui contourne l'échappatoire
        « prix saisi à la main » d'Odoo.
        """
        commande = self._commander()
        commande.order_line.write({"price_unit": 1.0})
        commande._recompute_prices()
        self.assertEqual(commande.order_line.price_unit, PRIX_TARIF)

    def test_aucun_canari_dans_la_projection_de_commande(self):
        commande = self._commander()
        serialise = json.dumps(commande._dally_shop_projection(), default=str)
        self.assertNotIn(CANARI_NOTE, serialise)
        self.assertNotIn("424242", serialise)
        self.assertNotIn("999999", serialise)

        # Aucun identifiant de partenaire ni de produit.
        self.assertNotIn(str(self.partenaire_client.id), serialise)
        self.assertNotIn(str(self.vendable.id), serialise)
        self.assertNotIn(str(self.vendable.product_variant_id.id), serialise)

        # `reference` est `sale.order.name` — la référence commerciale d'Odoo,
        # du type `S00779`. Sa séquence est corrélée à l'identifiant de ligne, et
        # ce test l'a d'abord signalé comme une fuite. Ce n'en est pas une : c'est
        # la référence que le client lit sur ses documents commerciaux, celle dont
        # il a besoin pour parler de sa commande, et la connaître ne donne accès à
        # rien — la lecture d'une commande passe par l'authentification et les
        # record rules. C'est la même situation que les références `DT-2026-…`
        # utilisées partout ailleurs dans ce dépôt.
        #
        # Ce qui est vérifié, donc : la référence est bien celle d'Odoo, et non un
        # identifiant technique nu.
        self.assertEqual(commande._dally_shop_projection()["reference"], commande.name)
        self.assertNotEqual(
            commande._dally_shop_projection()["reference"], str(commande.id)
        )

    def test_la_projection_ne_contient_que_les_cles_declarees(self):
        projection = self._commander()._dally_shop_projection()
        self.assertEqual(
            set(projection),
            {"reference", "status", "deliveryMode", "deliveryModeLabel", "currency",
             "amountUntaxed", "amountTax", "amountTotal", "lines"},
        )
        self.assertEqual(
            set(projection["lines"][0]),
            {"reference", "name", "quantity", "unitPrice", "subtotal"},
        )

    # ------------------------------------------------------------------
    # Cohérence de la commande boutique
    # ------------------------------------------------------------------

    def test_commande_boutique_sans_cle_refusee(self):
        with self.assertRaises(ValidationError):
            self.env["sale.order"].create({
                "partner_id": self.partenaire_client.id,
                "dally_shop_order": True,
                "dally_shop_delivery_mode": "pickup",
            })

    def test_commande_boutique_sans_mode_refusee(self):
        with self.assertRaises(ValidationError):
            self.env["sale.order"].create({
                "partner_id": self.partenaire_client.id,
                "dally_shop_order": True,
                "dally_shop_cart_uuid": str(uuid.uuid4()),
            })

    def test_une_commande_non_boutique_nest_pas_contrainte(self):
        """Contrôle négatif : la contrainte ne gêne pas le reste de l'ERP.

        Sans lui, la contrainte pourrait exiger une clé de panier sur toutes les
        commandes de l'entreprise, ce qui bloquerait la saisie manuelle.
        """
        ordinaire = self.env["sale.order"].create({
            "partner_id": self.partenaire_client.id,
        })
        self.assertFalse(ordinaire.dally_shop_order)

    # ------------------------------------------------------------------
    # Idempotence séquentielle
    # ------------------------------------------------------------------

    def test_deux_envois_du_meme_panier(self):
        cart = str(uuid.uuid4())
        premiere = self._commander(cart=cart)
        seconde = self._commander(cart=cart)
        self.assertEqual(premiere, seconde)
        self.assertEqual(len(premiere.order_line), 1)

    def test_dix_envois_du_meme_panier(self):
        """Dix fois, et pas seulement deux.

        Un dispositif qui tiendrait au second appel mais accumulerait des lignes
        au dixième passerait un test à deux appels. Les quantités sont vérifiées
        autant que le nombre de commandes : une duplication de lignes est une
        duplication de facturation.
        """
        cart = str(uuid.uuid4())
        commandes = {self._commander(cart=cart).id for _ in range(10)}
        self.assertEqual(len(commandes), 1)

        commande = self.env["sale.order"].browse(commandes.pop())
        self.assertEqual(len(commande.order_line), 1)
        self.assertEqual(commande.order_line.product_uom_qty, 2)
        self.assertEqual(
            self.env["sale.order"].search_count(
                [("dally_shop_cart_uuid", "=", cart)]
            ),
            1,
        )

    def test_dix_envois_ne_creent_quun_seul_contact_invite(self):
        cart = str(uuid.uuid4())
        contacts = set()
        for _ in range(10):
            invite = self.env["res.partner"]._dally_shop_create_guest(
                cart, self._identite()
            )
            contacts.add(invite.id)
            self._commander(partner=invite, invite=True, cart=cart)
        self.assertEqual(len(contacts), 1)
        self.assertEqual(
            self.env["res.partner"].search_count(
                [("dally_shop_guest_cart_uuid", "=", cart)]
            ),
            1,
        )

    def test_deux_paniers_differents_donnent_deux_commandes(self):
        """Contrôle négatif de l'idempotence.

        Sans lui, « une seule commande » serait vrai d'une implémentation qui
        refuserait toute seconde commande, quelle qu'elle soit.
        """
        premiere = self._commander()
        seconde = self._commander()
        self.assertNotEqual(premiere, seconde)


@tagged("post_install", "-at_install", "dally_shop")
class TestCheckoutConcurrence(TransactionCase):
    """La concurrence réelle, avec deux transactions PostgreSQL distinctes.

    Le motif est celui déjà employé pour la décision de devis portail, et ses
    deux contraintes ont été payées une fois :

    * les curseurs **et** les environnements sont construits dans le thread
      principal. `api.Environment(...)` prend un verrou de registre qu'Odoo
      détient pendant l'exécution d'une suite de tests ; appelé depuis un thread
      de travail, il ne rend jamais la main ;
    * une barrière garantit que les deux transactions sont ouvertes et
      positionnées avant que l'une n'écrive. Sans elle, on n'observerait qu'une
      exécution séquentielle déguisée.

    Ce que la concurrence produit réellement : le perdant travaille sur son
    instantané `REPEATABLE READ`, ne voit pas la commande du gagnant, crée, et se
    fait rejeter par l'index unique. `dally_shop_place_order` convertit ce rejet
    en `SerializationFailure`, qu'Odoo rejoue — l'invariant à prouver est donc
    « une seule commande écrite », pas « les deux appels rendent gentiment un
    objet ».
    """

    def setUp(self):
        super().setUp()
        self.cart = str(uuid.uuid4())
        self.reference_produit = f"essai-conc-{uuid.uuid4().hex[:8]}"
        self._monter_fixture_commitee()
        self.addCleanup(self._nettoyer_fixture)

    def _monter_fixture_commitee(self):
        """Les données doivent être visibles depuis d'autres transactions.

        D'où un commit explicite : une fixture posée dans la transaction du test
        serait invisible aux deux curseurs concurrents, et le test échouerait sur
        un produit introuvable plutôt que sur ce qu'il mesure.
        """
        with db_connect(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            tarif = env["product.pricelist"].create({
                "name": f"Boutique — concurrence {self.cart[:8]}",
                "item_ids": [(0, 0, {
                    "compute_price": "fixed",
                    "fixed_price": PRIX_TARIF,
                    "applied_on": "3_global",
                })],
            })
            env["ir.config_parameter"].sudo().set_param(
                "dally_shop.pricelist_id", str(tarif.id)
            )
            produit = env["product.template"].create({
                "name": f"Produit {self.reference_produit}",
                "type": "consu",
                "list_price": PRIX_LISTE,
                "dally_shop_slug": self.reference_produit,
                "dally_published": True,
            })
            partenaire = env["res.partner"].create({
                "name": f"Client concurrence {self.cart[:8]}",
                "email": f"conc.{self.cart[:8]}@essai.invalid",
            })
            cr.commit()
            self.tarif_id = tarif.id
            self.produit_id = produit.id
            self.partenaire_id = partenaire.id

    def _nettoyer_fixture(self):
        """Supprime ce que le test a commité, sinon la base garde des fantômes.

        Les commandes d'abord : `sale.order` référence le partenaire, et une
        suppression dans l'autre sens échouerait. L'annulation avant suppression
        reprend le motif déjà utilisé dans les fixtures de concurrence du portail.
        """
        with db_connect(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            commandes = env["sale.order"].search(
                [("dally_shop_cart_uuid", "=", self.cart)]
            )
            if commandes:
                commandes.state = "cancel"
                commandes.unlink()
            env["res.partner"].browse(self.partenaire_id).exists().unlink()
            env["product.template"].browse(self.produit_id).exists().unlink()
            env["product.pricelist"].browse(self.tarif_id).exists().unlink()
            cr.commit()

    def _lancer(self, nombre):
        barriere = threading.Barrier(nombre)
        resultats = []
        erreurs = []

        curseurs = [db_connect(self.env.cr.dbname).cursor() for _ in range(nombre)]
        for cr in curseurs:
            self.addCleanup(cr.close)
        environnements = [api.Environment(cr, self.env.uid, {}) for cr in curseurs]

        def commander(index):
            env = environnements[index]
            try:
                lignes = env["product.template"]._dally_shop_resolve_lines(
                    [(self.reference_produit, 2)]
                )
                partenaire = env["res.partner"].browse(self.partenaire_id)
                barriere.wait(timeout=30)
                commande = env["sale.order"].dally_shop_place_order(
                    self.cart, partenaire, lignes, "pickup"
                )
                curseurs[index].commit()
                resultats.append(commande.id)
            except Exception as erreur:  # noqa: BLE001
                erreurs.append(erreur)

        with ThreadPoolExecutor(max_workers=nombre) as pool:
            list(pool.map(commander, range(nombre)))
        return resultats, erreurs

    def test_deux_commandes_concurrentes_donnent_une_seule_commande(self):
        resultats, erreurs = self._lancer(2)

        # Une seule commande existe, quoi qu'aient vécu les deux transactions.
        with db_connect(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            commandes = env["sale.order"].search(
                [("dally_shop_cart_uuid", "=", self.cart)]
            )
            self.assertEqual(
                len(commandes), 1,
                f"une seule commande attendue ; resultats={resultats} erreurs={erreurs}",
            )
            self.assertEqual(len(commandes.order_line), 1)
            self.assertEqual(commandes.order_line.product_uom_qty, 2)
            self.assertEqual(commandes.state, "draft")

        # Le perdant, s'il a échoué, doit avoir échoué par un conflit de
        # sérialisation — la seule erreur qu'Odoo rejoue. Toute autre erreur
        # signifierait qu'un client reçoit une 500 sur une opération légitime.
        for erreur in erreurs:
            self.assertIsInstance(
                erreur, PG_CONCURRENCY_EXCEPTIONS_TO_RETRY,
                f"le perdant doit echouer par conflit de serialisation, obtenu {erreur!r}",
            )
        self.assertLessEqual(len(erreurs), 1, f"au plus un perdant ; obtenu {erreurs}")

    def test_dix_commandes_concurrentes_donnent_une_seule_commande(self):
        resultats, erreurs = self._lancer(10)

        with db_connect(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            commandes = env["sale.order"].search(
                [("dally_shop_cart_uuid", "=", self.cart)]
            )
            self.assertEqual(
                len(commandes), 1,
                f"une seule commande attendue ; resultats={resultats} erreurs={erreurs}",
            )
            self.assertEqual(len(commandes.order_line), 1)

        for erreur in erreurs:
            self.assertIsInstance(
                erreur, PG_CONCURRENCY_EXCEPTIONS_TO_RETRY,
                f"echec inattendu sous concurrence : {erreur!r}",
            )
