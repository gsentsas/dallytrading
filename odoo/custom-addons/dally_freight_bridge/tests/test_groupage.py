"""
Groupage maritime et aérien : le service ne dit pas le mode.

Ce que ces tests défendent tient en un chiffre. `dally.shipment` calcule le
poids taxable depuis `VOLUMETRIC_RATIOS`, où l'aérien vaut 167 kg/m³ et le
maritime 1000. Une consolidation aérienne projetée comme maritime — ou comme
« groupage », qui partage le même ratio — serait facturée **six fois trop cher**
sur du fret léger et volumineux, c'est-à-dire sur la majorité des biens de
consommation.

Le reste — libellés, colis, portail — se corrige. Cela, non : la facture part.
"""

import uuid

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


class GroupageCommon(TransactionCase):
    """Un client et le service de groupage."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Service = cls.env["dally.service.type"]
        cls.service_groupage = Service.search([("code", "=", "freight_groupage")], limit=1)
        cls.service_maritime = Service.search([("code", "=", "freight_sea")], limit=1)
        cls.service_aerien = Service.search([("code", "=", "freight_air")], limit=1)
        cls.service_vehicule = Service.search([("code", "=", "freight_vehicle")], limit=1)

    def _devis(self, nom, mode=None, service=None):
        partenaire = self.env["res.partner"].create({"name": f"Grp {nom}"})
        valeurs = {
            "partner_id": partenaire.id,
            "contact_name": f"Grp {nom}",
            "company_name": f"Grp {nom}",
            "service_type_id": (service or self.service_groupage).id,
            "email": f"grp-{nom.lower()}@test.invalid",
            "request_uuid": str(uuid.uuid4()),
            "origin_city": "Dakar",
            "destination_city": "Paris",
        }
        if mode:
            valeurs["groupage_transport_mode"] = mode
        return self.env["dally.quote.request"].create(valeurs)

    def _chaine(self, devis):
        """Retourne `(bookings, expéditions tk, projections)`."""
        bookings = self.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", devis.id)]
        )
        expeditions = self.env["freight.shipment"].sudo().search(
            [("booking_id", "in", bookings.ids)]
        )
        projections = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "in", expeditions.ids)]
        )
        return bookings, expeditions, projections

    def _provisionne(self, devis):
        devis.write({"state": "won"})
        bookings, expeditions, projections = self._chaine(devis)
        self.assertEqual(
            (len(bookings), len(expeditions), len(projections)), (1, 1, 1)
        )
        return expeditions, projections

    def _refuse(self, devis, motif):
        """Exige un refus **et** un rollback complet."""
        etat_initial = devis.state
        try:
            with self.env.cr.savepoint():
                devis.write({"state": "won"})
        except UserError as erreur:
            self.assertIn(motif, str(erreur))
        else:
            self.fail("Le provisionnement aurait du etre refuse.")

        self.env.invalidate_all()
        self.assertEqual(devis.state, etat_initial)
        bookings, expeditions, projections = self._chaine(devis)
        self.assertEqual((len(bookings), len(expeditions), len(projections)), (0, 0, 0))


@tagged("post_install", "-at_install", "dally_freight")
class TestGroupageModes(GroupageCommon):
    """Chaque mode produit sa propre chaîne, sans se confondre."""

    def test_groupage_maritime_produit_un_lcl(self):
        """LCL est une valeur réelle du fournisseur, pas une approximation.

        `ocean_shipment_type` propose `fcl` et `lcl` : on écrit la seconde,
        plutôt que de signaler le groupage dans une note libre que personne
        n'interroge.
        """
        expedition, projection = self._provisionne(self._devis("Sea", "sea"))
        self.assertEqual(expedition.transport, "ocean")
        self.assertEqual(expedition.ocean_shipment_type, "lcl")
        self.assertEqual(projection.transport_mode, "sea")

    def test_groupage_aerien_ne_porte_aucun_type_maritime(self):
        """LCL est une notion maritime : l'écrire sur un vol serait une erreur.

        Le fournisseur n'offre aucun marqueur de consolidation aérienne, et on
        ne détourne pas `operation = house` pour en tenir lieu — la LTA maison
        contre LTA mère décrit un rapport entre transitaires, pas le caractère
        groupé d'un envoi commercial.
        """
        expedition, projection = self._provisionne(self._devis("Air", "air"))
        self.assertEqual(expedition.transport, "air")
        self.assertFalse(expedition.ocean_shipment_type)
        self.assertEqual(projection.transport_mode, "air")

    def test_un_groupage_sans_mode_est_refuse(self):
        self._refuse(self._devis("SansMode"), "mode de groupage")

    def test_le_mode_est_borne_par_la_selection(self):
        with self.assertRaises(ValueError):
            self._devis("ModeInconnu", "teleportation")

    def test_le_pont_ne_produit_jamais_le_mode_groupage(self):
        """Le mode historique reste sur le modèle, mais le pont ne l'écrit pas.

        Il vaut 1000 kg/m³, comme le maritime. Une consolidation aérienne
        projetée ainsi serait facturée au mauvais ratio.
        """
        for nom, mode in (("GardeSea", "sea"), ("GardeAir", "air")):
            _expedition, projection = self._provisionne(self._devis(nom, mode))
            self.assertNotEqual(projection.transport_mode, "groupage")

    def test_la_valeur_historique_reste_disponible(self):
        """On n'a pas supprimé `groupage` de la sélection.

        Des expéditions saisies à la main la portent peut-être déjà, et retirer
        une valeur d'une sélection casse les enregistrements qui l'utilisent.
        """
        modes = dict(
            self.env["dally.shipment"]._fields["transport_mode"]._description_selection(
                self.env
            )
        )
        self.assertIn("groupage", modes)


@tagged("post_install", "-at_install", "dally_freight")
class TestGroupagePoidsTaxable(GroupageCommon):
    """Le mode décide du ratio volumétrique, donc de la facture."""

    #: Cargaison légère et volumineuse : c'est là que les ratios divergent.
    #: 100 kg réels pour 10 m³ — un carton de mousse, un lot de textile.
    POIDS_REEL = 100.0
    VOLUME = 10.0

    def _taxable(self, mode):
        _expedition, projection = self._provisionne(self._devis(f"Poids{mode}", mode))
        projection.sudo().write({
            "weight_kg": self.POIDS_REEL,
            "volume_cbm": self.VOLUME,
        })
        projection.invalidate_recordset(["chargeable_weight_kg"])
        return projection.transport_mode, projection.chargeable_weight_kg

    def test_le_groupage_aerien_emprunte_le_ratio_aerien(self):
        """Le test qui justifie tout le chantier.

        On ne recalcule pas la formule ici : on interroge le mécanisme métier
        existant, et on vérifie qu'un groupage aérien produit bien un résultat
        d'aérien — nettement inférieur à celui du maritime sur cette cargaison.
        """
        mode_air, taxable_air = self._taxable("air")
        mode_sea, taxable_sea = self._taxable("sea")

        self.assertEqual(mode_air, "air")
        self.assertEqual(mode_sea, "sea")

        # Le poids réel est le même : seule la conversion volumétrique diffère.
        self.assertGreater(taxable_sea, taxable_air)
        self.assertGreater(taxable_air, self.POIDS_REEL)
        # Le rapport doit être celui des ratios (1000 / 167 ≈ 6), pas 1.
        self.assertGreater(
            taxable_sea / taxable_air, 5.0,
            "Le groupage aerien n'emprunte pas le chemin aerien : les deux "
            "modes produisent un poids taxable comparable.",
        )


@tagged("post_install", "-at_install", "dally_freight")
class TestGroupageIdempotence(GroupageCommon):
    """Le même devis groupage traité n fois produit toujours 1/1/1."""

    def test_reecrire_le_meme_etat_ne_duplique_rien(self):
        devis = self._devis("Rejeu", "sea")
        devis.write({"state": "won"})
        devis.write({"state": "won"})
        bookings, expeditions, projections = self._chaine(devis)
        self.assertEqual((len(bookings), len(expeditions), len(projections)), (1, 1, 1))

    def test_dix_appels_directs_restent_idempotents(self):
        devis = self._devis("Dix", "air")
        devis.write({"state": "won"})
        for _ in range(10):
            devis._dally_freight_provision()
        bookings, expeditions, projections = self._chaine(devis)
        self.assertEqual((len(bookings), len(expeditions), len(projections)), (1, 1, 1))


@tagged("post_install", "-at_install", "dally_freight")
class TestGroupageColis(GroupageCommon):
    """Les colis passent par le système existant, sans second modèle."""

    def _ajoute_colis(self, expedition, lignes):
        for qty, poids, l, w, h in lignes:
            self.env["shipment.package.line"].sudo().create({
                "shipment_id": expedition.id,
                "qty": qty, "net_weight": poids,
                "length": l, "width": w, "height": h,
            })

    def test_les_colis_maritimes_sont_projetes(self):
        devis = self._devis("ColisSea", "sea")
        expedition, projection = self._provisionne(devis)
        self._ajoute_colis(expedition, [
            (2, 45.0, 120.0, 80.0, 100.0),
            (1, 12.5, 60.0, 40.0, 40.0),
            (3, 8.0, 30.0, 30.0, 30.0),
        ])
        projection._dally_freight_sync_from_tk()

        colis = self.env["dally.shipment.package"].sudo().search(
            [("shipment_id", "=", projection.id)]
        )
        self.assertEqual(len(colis), 3)
        self.assertEqual(sum(colis.mapped("quantity")), 6)

    def test_les_colis_aeriens_sont_projetes(self):
        devis = self._devis("ColisAir", "air")
        expedition, projection = self._provisionne(devis)
        self._ajoute_colis(expedition, [(4, 6.0, 50.0, 40.0, 30.0)])
        projection._dally_freight_sync_from_tk()

        colis = self.env["dally.shipment.package"].sudo().search(
            [("shipment_id", "=", projection.id)]
        )
        self.assertEqual(len(colis), 1)
        self.assertEqual(colis.quantity, 4)


@tagged("post_install", "-at_install", "dally_freight")
class TestGroupageNonRegression(GroupageCommon):
    """Les quatre chemins fret restent distincts."""

    def test_le_maritime_standard_est_inchange(self):
        devis = self._devis("StdSea", service=self.service_maritime)
        expedition, projection = self._provisionne(devis)
        self.assertEqual(expedition.transport, "ocean")
        self.assertEqual(projection.transport_mode, "sea")
        # Le maritime standard n'est pas du LCL : le pont ne doit rien imposer.
        self.assertFalse(expedition.ocean_shipment_type)

    def test_l_aerien_standard_est_inchange(self):
        devis = self._devis("StdAir", service=self.service_aerien)
        expedition, projection = self._provisionne(devis)
        self.assertEqual(expedition.transport, "air")
        self.assertEqual(projection.transport_mode, "air")

    def test_le_vehicule_garde_son_propre_champ(self):
        """Vehicle et Groupage ne partagent pas leur mode.

        Les deux champs coexistent volontairement : ils n'ont ni les mêmes
        valeurs (`sea|air` contre `sea|road`) ni les mêmes conséquences. Les
        fondre imposerait une migration à une fonctionnalité déjà déployée.
        """
        devis = self._devis("Veh", service=self.service_vehicule)
        self.env["dally.freight.vehicle.cargo"].create({
            "quote_request_id": devis.id,
            "make": "Toyota", "model": "Hilux",
            "category": "van", "condition": "running",
            "transport_mode": "road",
        })
        expedition, projection = self._provisionne(devis)
        self.assertEqual(expedition.transport, "land")
        self.assertEqual(projection.transport_mode, "road")
        # Le champ groupage n'a joué aucun rôle.
        self.assertFalse(devis.groupage_transport_mode)

    def test_un_mode_groupage_sur_un_devis_non_groupage_est_ignore(self):
        """Le champ ne doit pas agir hors de son service.

        Sans ce contrôle, un mode résiduel — saisi puis le service changé —
        détournerait silencieusement un dossier maritime standard.
        """
        devis = self._devis("Parasite", service=self.service_aerien)
        devis.groupage_transport_mode = "sea"
        expedition, projection = self._provisionne(devis)
        self.assertEqual(expedition.transport, "air")
        self.assertEqual(projection.transport_mode, "air")


@tagged("post_install", "-at_install", "dally_freight")
class TestGroupageSecurite(GroupageCommon):
    """Le cloisonnement client vaut aussi pour le groupage."""

    def _dossier(self, nom, mode):
        devis = self._devis(nom, mode)
        utilisateur = self.env["res.users"].create({
            "name": f"Grp {nom}",
            "login": f"grp.{nom.lower()}@dally.invalid",
            "partner_id": devis.partner_id.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        _expedition, projection = self._provisionne(devis)
        return utilisateur, projection

    def test_le_client_lit_sa_propre_expedition(self):
        """Contrôle positif : sans lui, le refus suivant ne prouverait rien."""
        client, projection = self._dossier("SecA", "sea")
        self.env.invalidate_all()
        self.assertTrue(
            self.env(user=client)["dally.shipment"].browse(projection.id).read(["reference"])
        )

    def test_le_client_ne_lit_pas_celle_d_un_autre(self):
        client_a, _projection_a = self._dossier("SecB1", "sea")
        _client_b, projection_b = self._dossier("SecB2", "air")
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env(user=client_a)["dally.shipment"].browse(projection_b.id).read(
                ["reference"]
            )
