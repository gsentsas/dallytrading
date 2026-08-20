"""
Le portail commandes : qui voit quoi, et ce qui ne sort jamais.

## Le jeu d'essai

Deux clients portail avec compte, un contact invité sans compte, et quatre
commandes : une par client, une invitée, une non-boutique. Chacune répond à une
question distincte, et un jeu plus petit laisserait des questions ouvertes en
donnant l'illusion de les couvrir.

## Ce que ces tests mesurent réellement

Le cloisonnement n'est pas implémenté par nous : il vient de la record rule native
`Portal Personal Quotations/Sales Orders`
(`partner_id child_of user.commercial_partner_id.id`) et de l'ACL
`sale.order.portal`, qui donne **read seul** au groupe portail.

Ces tests vérifient donc que nous nous appuyons correctement dessus — c'est-à-dire
que nos projections sont appelées sur un recordset obtenu **sans** `sudo()`. Un
`sudo()` glissé dans le contrôleur ferait passer tous les tests de projection et
casser silencieusement ceux-ci ; c'est précisément pour ça qu'ils existent.

## Canaris

Coût, marge et note interne, plantés sur le produit **et** sur la commande. Chaque
assertion d'absence est précédée d'un contrôle positif : sans lui, « le coût ne
fuit pas » serait vrai d'un produit dont le coût est nul.
"""

import base64
import json
import struct
import uuid
import zlib

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, tagged


def _png_base64():
    """Un PNG 1×1 réellement conforme, encodé en base64.

    Odoo valide l'image de signature avant de confirmer. Une chaîne bidon fait
    échouer l'appel pour une raison sans rapport avec l'autorisation — et
    laisserait croire que la route est fermée alors qu'elle ne l'est pas. C'est
    exactement ce qui s'est produit au premier essai de l'audit.
    """
    def bloc(nom, donnees):
        return (struct.pack(">I", len(donnees)) + nom + donnees
                + struct.pack(">I", zlib.crc32(nom + donnees) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + bloc(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + bloc(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
           + bloc(b"IEND", b""))
    return base64.b64encode(png).decode()

CANARY_SHOP_COST = 424242.42
CANARY_SHOP_MARGIN = 313131.31
CANARY_SHOP_INTERNAL_NOTE = "CANARY_SHOP_INTERNAL_NOTE_PORTAL"

PRIX_TARIF = 150000.0
PRIX_LISTE = 999999.0


@tagged("post_install", "-at_install", "dally_shop")
class TestPortailCommandes(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.tarif = cls.env["product.pricelist"].create({
            "name": "Boutique — essai portail",
            "item_ids": [(0, 0, {
                "compute_price": "fixed",
                "fixed_price": PRIX_TARIF,
                "applied_on": "3_global",
            })],
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(cls.tarif.id)
        )

        cls.produit = cls.env["product.template"].create({
            "name": "Article portail",
            "type": "consu",
            "list_price": PRIX_LISTE,
            "dally_shop_slug": "essai-portail-article",
            "dally_published": True,
        })
        # Canaris côté produit. `standard_price` est le coût réel ; la marge n'a pas
        # de champ dédié en standard, on la plante donc dans un champ interne libre
        # pour qu'un balayage textuel puisse la chercher.
        cls.produit.write({
            "standard_price": CANARY_SHOP_COST,
            "description": (
                f"{CANARY_SHOP_INTERNAL_NOTE} marge={CANARY_SHOP_MARGIN}"
            ),
        })

        cls.client_a, cls.user_a = cls._compte("Client Portail A", "portail.a@essai.invalid")
        cls.client_b, cls.user_b = cls._compte("Client Portail B", "portail.b@essai.invalid")

        cls.commande_a = cls._commande(cls.client_a)
        cls.commande_b = cls._commande(cls.client_b)

        # Commande invité : le contact est créé pour elle et n'a aucun compte.
        cart_invite = str(uuid.uuid4())
        cls.invite = cls.env["res.partner"]._dally_shop_create_guest(cart_invite, {
            "name": "Invité Portail",
            "email": "invite.portail@essai.invalid",
        })
        cls.commande_invite = cls._commande(cls.invite, cart=cart_invite, invite=True)

        # Commande ordinaire du client A : elle ne doit pas apparaître dans la
        # liste boutique, sinon « mes commandes » mélangerait deux choses.
        cls.commande_ordinaire = cls.env["sale.order"].create({
            "partner_id": cls.client_a.id,
        })

        # Canari côté commande, dans un champ que le personnel utilise.
        cls.commande_a.note = CANARY_SHOP_INTERNAL_NOTE

    @classmethod
    def _compte(cls, nom, courriel):
        partenaire = cls.env["res.partner"].create({"name": nom, "email": courriel})
        utilisateur = cls.env["res.users"].create({
            "name": nom,
            "login": courriel,
            "partner_id": partenaire.id,
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })
        return partenaire, utilisateur

    @classmethod
    def _commande(cls, partenaire, cart=None, invite=False):
        lignes = cls.env["product.template"]._dally_shop_resolve_lines(
            [("essai-portail-article", 2)]
        )
        return cls.env["sale.order"].dally_shop_place_order(
            cart or str(uuid.uuid4()), partenaire, lignes, "pickup", invite=invite
        )

    def _vues_par(self, utilisateur):
        """Les commandes boutique visibles par cet utilisateur.

        **Sans `sudo()`** : c'est tout l'objet du test. La record rule native est
        ce qui filtre, et l'écrire ainsi est la seule façon de le vérifier.
        """
        self.env.invalidate_all()
        Commande = self.env["sale.order"].with_user(utilisateur)
        return Commande.search(Commande._dally_shop_portal_domain())

    # ------------------------------------------------------------------
    # Contrôle positif
    # ------------------------------------------------------------------

    def test_canaris_bien_plantes(self):
        interne = self.produit.sudo().read(["standard_price", "description"])[0]
        self.assertEqual(interne["standard_price"], CANARY_SHOP_COST)
        # `description` et `note` sont des champs Html : Odoo enveloppe la valeur
        # dans un `<p>`. On cherche donc la sous-chaîne, pas l'égalité.
        self.assertIn(CANARY_SHOP_INTERNAL_NOTE, str(interne["description"]))
        self.assertIn(str(int(CANARY_SHOP_MARGIN)), str(interne["description"]))
        self.assertIn(CANARY_SHOP_INTERNAL_NOTE, str(self.commande_a.sudo().note))

    # ------------------------------------------------------------------
    # Cloisonnement
    # ------------------------------------------------------------------

    def test_le_client_voit_sa_commande(self):
        self.assertIn(self.commande_a, self._vues_par(self.user_a))

    def test_a_ne_voit_pas_la_commande_de_b(self):
        self.assertNotIn(self.commande_b, self._vues_par(self.user_a))

    def test_b_ne_voit_pas_la_commande_de_a(self):
        """Les deux sens, séparément.

        Un dispositif asymétrique — un domaine mal écrit, un partenaire parent
        commun — passerait un seul des deux tests.
        """
        self.assertNotIn(self.commande_a, self._vues_par(self.user_b))
        self.assertIn(self.commande_b, self._vues_par(self.user_b))

    def test_la_commande_invitee_napparait_dans_aucun_portail(self):
        """Aucun rattachement par adresse, et aucun par accident.

        Le contact invité n'a pas de compte : il n'est le `commercial_partner_id`
        de personne. L'absence tombe donc de la record rule, pas d'un filtre que
        nous aurions ajouté.
        """
        self.assertFalse(self.invite.user_ids)
        for utilisateur in (self.user_a, self.user_b):
            self.assertNotIn(self.commande_invite, self._vues_par(utilisateur))

    def test_une_commande_invitee_meme_email_reste_invisible(self):
        """Le cas explicite : même adresse qu'un compte portail existant.

        Un contact invité portant l'adresse du client A ne doit pas faire
        apparaître sa commande dans le portail de A. C'est le scénario
        d'usurpation, et il doit rester fermé même si l'adresse coïncide.
        """
        cart = str(uuid.uuid4())
        # `_dally_shop_create_guest` refuserait cette adresse ; on crée donc le
        # contact directement, pour éprouver la couche de lecture plutôt que celle
        # de création — c'est bien cette couche qui est testée ici.
        homonyme = self.env["res.partner"].create({
            "name": "Homonyme",
            "email": self.client_a.email,
            "dally_shop_guest_cart_uuid": cart,
        })
        commande = self._commande(homonyme, cart=cart, invite=True)
        self.assertNotIn(commande, self._vues_par(self.user_a))

    def test_une_commande_non_boutique_napparait_pas(self):
        self.assertNotIn(self.commande_ordinaire, self._vues_par(self.user_a))
        # Contrôle positif : elle existe bien et appartient bien à A.
        self.assertEqual(self.commande_ordinaire.partner_id, self.client_a)

    def test_la_reference_seule_nautorise_rien(self):
        """Connaître `S00042` ne donne pas accès à la commande.

        La recherche par référence s'exécute sous l'utilisateur : la commande d'un
        autre est simplement absente du recordset.
        """
        self.env.invalidate_all()
        Commande = self.env["sale.order"].with_user(self.user_a)
        trouvee = Commande.search(
            Commande._dally_shop_portal_domain()
            + [("name", "=", self.commande_b.name)]
        )
        self.assertFalse(trouvee)

    def test_le_portail_ne_peut_pas_ecrire(self):
        """L'ACL native donne read seul. Vérifié plutôt que supposé."""
        Commande = self.env["sale.order"].with_user(self.user_a)
        for droit in ("write", "create", "unlink"):
            with self.assertRaises(AccessError, msg=f"{droit} devrait être refusé"):
                Commande.check_access(droit)

    # ------------------------------------------------------------------
    # Correspondance des états
    # ------------------------------------------------------------------

    def test_draft_devient_commande_recue(self):
        """« Brouillon » n'est pas un mot pour un client.

        Il suggère quelque chose d'inachevé de son côté, alors que ce qui reste à
        faire est du nôtre.
        """
        self.assertEqual(self.commande_a.state, "draft")
        libelle = self.commande_a._dally_shop_state_label()
        self.assertEqual(libelle, "Commande reçue — en attente de validation")
        self.assertNotIn("rouillon", libelle)

    def test_aucun_etat_ne_promet_un_paiement_ni_une_expedition(self):
        """Balayage de tous les libellés possibles.

        Vérifier seulement `draft` laisserait passer un libellé ajouté demain qui
        affirmerait quelque chose de faux.
        """
        from ..models.shop_order_portal import ETATS_CLIENT, ETAT_INCONNU

        for libelle in list(ETATS_CLIENT.values()) + [ETAT_INCONNU]:
            minuscule = libelle.lower()
            for interdit in ("payé", "paye", "réglé", "regle", "expédi", "expedi",
                            "livré", "livre"):
                self.assertNotIn(
                    interdit, minuscule,
                    f"« {libelle} » promet quelque chose que le MVP ne tient pas",
                )

    def test_la_table_couvre_tous_les_etats_du_champ(self):
        """Chaque valeur possible de `state` a son libellé.

        Le repli existe pour un état qu'un module tiers ajouterait, mais aucun
        état **actuel** ne doit y tomber : le client lirait « en cours de
        traitement » là où on sait dire quelque chose de précis.
        """
        from ..models.shop_order_portal import ETATS_CLIENT

        etats = [valeur for valeur, _libelle in self.env["sale.order"]._fields["state"].selection]
        self.assertEqual(sorted(etats), sorted(ETATS_CLIENT))

    def test_un_etat_hors_table_retombe_sur_un_libelle_non_vide(self):
        from ..models.shop_order_portal import ETAT_INCONNU

        # On force l'état en base, hors de la sélection : c'est le seul moyen
        # d'éprouver le repli, qu'aucun chemin normal ne peut atteindre.
        self.env.cr.execute(
            "UPDATE sale_order SET state = %s WHERE id = %s",
            ("etat_invente", self.commande_a.id),
        )
        self.commande_a.invalidate_recordset(["state"])
        self.assertEqual(self.commande_a._dally_shop_state_label(), ETAT_INCONNU)
        self.assertTrue(ETAT_INCONNU)

    # ------------------------------------------------------------------
    # Projections
    # ------------------------------------------------------------------

    def test_projection_de_liste_exactement_ses_cles(self):
        projection = self.commande_a._dally_shop_portal_list()[0]
        self.assertEqual(
            set(projection),
            {"reference", "date", "stateLabel", "currency", "amountUntaxed",
             "amountTax", "amountTotal", "deliveryMode", "deliveryModeLabel",
             "deliveryFeeStatus", "deliveryFee", "grandTotal",
             "fulfillmentState", "fulfillmentLabel", "itemCount"},
        )

    def test_projection_de_detail_exactement_ses_cles(self):
        projection = self.commande_a._dally_shop_portal_detail()
        self.assertEqual(
            set(projection),
            {"reference", "date", "state", "stateLabel", "deliveryMode",
             "deliveryModeLabel", "currency", "amountUntaxed", "amountTax",
             "amountTotal", "deliveryFeeStatus", "deliveryFee", "grandTotal",
             "fulfillmentState", "fulfillmentLabel", "lines", "deliveryAddress"},
        )
        self.assertEqual(
            set(projection["lines"][0]),
            {"productName", "quantity", "unitPrice", "subtotal"},
        )
        self.assertIsNone(projection["deliveryAddress"])

    def test_les_montants_et_les_lignes_sont_exacts(self):
        projection = self.commande_a._dally_shop_portal_detail()
        self.assertEqual(len(projection["lines"]), 1)
        ligne = projection["lines"][0]
        self.assertEqual(ligne["quantity"], 2.0)
        self.assertEqual(ligne["unitPrice"], PRIX_TARIF)
        self.assertEqual(ligne["subtotal"], PRIX_TARIF * 2)
        self.assertEqual(projection["amountUntaxed"], PRIX_TARIF * 2)
        self.assertEqual(
            projection["amountTotal"],
            projection["amountUntaxed"] + projection["amountTax"],
        )
        self.assertEqual(projection["deliveryFeeStatus"], "free")
        self.assertEqual(projection["deliveryFee"], 0.0)
        self.assertEqual(projection["grandTotal"], projection["amountTotal"])
        self.assertEqual(projection["fulfillmentState"], "pending")
        self.assertTrue(projection["fulfillmentLabel"])

    def test_le_compte_darticles_est_celui_du_panier(self):
        """`itemCount` compte les articles, pas les lignes.

        C'est ce que le client a mis au panier, et c'est ce qu'il reconnaîtra.
        """
        projection = self.commande_a._dally_shop_portal_list()[0]
        self.assertEqual(projection["itemCount"], 2)

    def test_aucun_canari_dans_les_projections(self):
        """Balayage textuel des deux projections sérialisées.

        Sérialiser puis chercher, plutôt qu'inspecter clé par clé : un canari
        caché dans une valeur imbriquée — un libellé, un nom d'article —
        échapperait à une inspection de surface.
        """
        corpus = json.dumps(
            [
                self.commande_a._dally_shop_portal_list(),
                self.commande_a._dally_shop_portal_detail(),
            ],
            default=str,
        )
        self.assertIn("Article portail", corpus)  # contrôle positif

        for canari in (
            CANARY_SHOP_INTERNAL_NOTE,
            str(int(CANARY_SHOP_COST)),
            str(int(CANARY_SHOP_MARGIN)),
            str(int(PRIX_LISTE)),
            "standard_price",
            "seller_ids",
            "note",
            "margin",
        ):
            self.assertNotIn(canari, corpus, f"« {canari} » ne doit pas sortir")

    def test_aucun_identifiant_technique_dans_les_projections(self):
        corpus = json.dumps(
            [
                self.commande_a._dally_shop_portal_list(),
                self.commande_a._dally_shop_portal_detail(),
            ],
            default=str,
        )
        for identifiant in (
            self.client_a.id,
            self.produit.id,
            self.produit.product_variant_id.id,
            self.commande_a.order_line.id,
        ):
            self.assertNotIn(
                f'"{identifiant}"', corpus,
                f"l'identifiant {identifiant} ne doit pas sortir",
            )
        # Ni le nom des champs qui les porteraient.
        for clef in ("partner_id", "product_id", "order_id", "commercial_partner_id",
                     "id"):
            self.assertNotIn(f'"{clef}"', corpus)

    def test_la_projection_marche_sous_lutilisateur_du_client(self):
        """Le recordset commande reste sous l'identité réelle du client.

        La méthode de remise n'a volontairement aucune ACL portail générique : la
        projection peut élever uniquement ce petit record de configuration pour
        lire les champs explicitement publics. La commande, ses règles et son
        cloisonnement ne doivent jamais passer en sudo.
        """
        self.env.invalidate_all()
        Method = self.env["dally.shop.delivery.method"].with_user(self.user_a)
        with self.assertRaises(AccessError):
            Method.check_access("read")

        commande = self.commande_a.with_user(self.user_a)
        liste = commande._dally_shop_portal_list()
        detail = commande._dally_shop_portal_detail()
        self.assertEqual(liste[0]["reference"], self.commande_a.name)
        self.assertEqual(liste[0]["deliveryMode"], "pickup")
        self.assertEqual(detail["lines"][0]["unitPrice"], PRIX_TARIF)
        self.assertIsNone(detail["deliveryAddress"])


@tagged("post_install", "-at_install", "dally_shop")
class TestPortailNatifNeutralise(HttpCase):
    """Le portail natif de `sale` n'est pas un second portail boutique.

    L'audit a mesuré, sur la pile de développement, qu'un client portail pouvait
    ouvrir `/my/orders/<id>` pour sa commande boutique **et la confirmer** par
    `/my/orders/<id>/accept` : `draft` → `sale`, signature enregistrée, un
    transfert de stock créé.

    ## Pourquoi `HttpCase` et non un test de méthode

    Un premier essai instanciait `CustomerPortal()` pour inspecter ses domaines.
    Cela ne mesurait rien : Odoo assemble ses contrôleurs au chargement du
    registre, et une instanciation manuelle rend la classe de **base**, sans nos
    surcharges. Le test passait ou échouait pour des raisons sans rapport avec le
    comportement réel.

    Ces tests frappent donc les vraies URL. C'est plus lent, et c'est la seule
    façon d'exercer le contrôleur tel qu'il est servi.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tarif = cls.env["product.pricelist"].create({
            "name": "Boutique — essai natif",
            "item_ids": [(0, 0, {
                "compute_price": "fixed", "fixed_price": PRIX_TARIF,
                "applied_on": "3_global",
            })],
        })
        cls.env["ir.config_parameter"].sudo().set_param(
            "dally_shop.pricelist_id", str(cls.tarif.id)
        )
        cls.produit = cls.env["product.template"].create({
            "name": "Article natif", "type": "consu", "list_price": PRIX_LISTE,
            "dally_shop_slug": "essai-natif-article", "dally_published": True,
        })
        cls.mot_de_passe = "essai-natif-portail-2026"
        cls.partenaire = cls.env["res.partner"].create({
            "name": "Client Natif", "email": "client.natif@essai.invalid",
        })
        cls.utilisateur = cls.env["res.users"].create({
            "name": "Client Natif", "login": "client.natif@essai.invalid",
            "password": cls.mot_de_passe,
            "partner_id": cls.partenaire.id,
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })
        lignes = cls.env["product.template"]._dally_shop_resolve_lines(
            [("essai-natif-article", 1)]
        )
        cls.commande_boutique = cls.env["sale.order"].dally_shop_place_order(
            str(uuid.uuid4()), cls.partenaire, lignes, "pickup"
        )
        # Un devis ordinaire, envoyé : c'est l'état dans lequel le personnel le
        # transmet au client, et celui où le portail natif doit rester utilisable.
        cls.devis_ordinaire = cls.env["sale.order"].create({
            "partner_id": cls.partenaire.id, "state": "sent",
        })

    def setUp(self):
        super().setUp()
        self.authenticate(self.utilisateur.login, self.mot_de_passe)

    def test_la_fiche_native_dune_commande_boutique_est_fermee(self):
        """Indiscernable d'une commande inexistante.

        On compare à la réponse obtenue pour un identifiant qui n'existe pas :
        c'est plus fort que « ce n'est pas la page de la commande », parce que cela
        exclut aussi une page d'erreur propre à notre refus, qui serait un oracle.
        """
        boutique = self.url_open(f"/my/orders/{self.commande_boutique.id}")
        inexistante = self.url_open("/my/orders/99999999")

        self.assertNotIn(self.commande_boutique.name, boutique.text)
        self.assertEqual(len(boutique.text), len(inexistante.text))

    def test_le_devis_ordinaire_reste_accessible(self):
        """Contrôle négatif : la fermeture est étroite.

        Le personnel envoie ses offres par courriel, et le lien de l'offre est une
        route de ce portail. Fermer en bloc casserait un usage commercial réel —
        c'est la raison pour laquelle le refus porte sur `dally_shop_order` et non
        sur la route.
        """
        reponse = self.url_open(f"/my/orders/{self.devis_ordinaire.id}")
        self.assertIn(self.devis_ordinaire.name, reponse.text)

    def test_les_listes_natives_ne_montrent_aucune_commande_boutique(self):
        for chemin in ("/my/orders", "/my/quotes"):
            reponse = self.url_open(chemin)
            self.assertNotIn(
                self.commande_boutique.name, reponse.text,
                f"{chemin} ne doit pas lister une commande boutique",
            )

    def test_un_client_ne_peut_pas_confirmer_sa_commande_boutique(self):
        """Le point qui justifie tout ce fichier.

        Sans la fermeture, cet appel confirmait la commande et créait un transfert.
        Le MVP interdit la confirmation automatique ; il ne servirait à rien de la
        refuser côté Next.js si le client peut la déclencher par une route qu'Odoo
        ouvre par défaut.
        """
        avant = self.commande_boutique.state
        reponse = self.url_open(
            f"/my/orders/{self.commande_boutique.id}/accept",
            json={"params": {
                "order_id": self.commande_boutique.id,
                "access_token": None,
                "name": "Client Natif",
                "signature": _png_base64(),
            }},
        )
        self.commande_boutique.invalidate_recordset()
        self.assertEqual(avant, "draft")
        self.assertEqual(self.commande_boutique.state, "draft")
        self.assertFalse(self.commande_boutique.picking_ids)
        self.assertFalse(self.commande_boutique.signature)
        # Et la réponse est celle d'une commande qu'on n'a pas le droit de toucher.
        self.assertIn("Invalid order", reponse.text)

    def test_le_devis_ordinaire_reste_signable(self):
        """Contrôle négatif du précédent.

        Sans lui, « personne ne peut signer » passerait pour la bonne
        implémentation, et la fermeture aurait cassé le parcours commercial.
        """
        self.url_open(
            f"/my/orders/{self.devis_ordinaire.id}/accept",
            json={"params": {
                "order_id": self.devis_ordinaire.id,
                "access_token": None,
                "name": "Client Natif",
                "signature": _png_base64(),
            }},
        )
        self.devis_ordinaire.invalidate_recordset()
        self.assertEqual(self.devis_ordinaire.state, "sale")

    def test_le_document_edi_dune_commande_boutique_est_ferme(self):
        """Comparé à un identifiant inexistant, pas à un mot-clé.

        Un premier essai cherchait l'absence du mot « Invoice ». C'était faux : la
        route refuse en redirigeant vers `/my`, dont la navigation mentionne
        légitimement les factures. L'assertion échouait donc alors que la
        fermeture fonctionnait.
        """
        boutique = self.url_open(
            f"/my/orders/{self.commande_boutique.id}/download_edi"
        )
        inexistante = self.url_open("/my/orders/99999999/download_edi")

        # Ni le fichier EDI, ni la référence : la même page que pour une commande
        # qui n'existe pas.
        self.assertNotIn(self.commande_boutique.name, boutique.text)
        self.assertEqual(len(boutique.text), len(inexistante.text))
        self.assertNotIn("application/xml", boutique.headers.get("Content-Type", ""))
