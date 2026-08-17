"""
Transport de véhicule : le service commercial ne dit pas le mode physique.

C'est la seule chose que ces tests défendent vraiment. Tout le reste — VIN,
adresses, nombre de clés — se corrige en production sans conséquence. Un mode
faux, lui, crée une expédition maritime étiquetée routière, ou l'inverse, et
personne ne s'en aperçoit avant que le client ne réclame sa voiture.
"""

import uuid

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


class VehicleCommon(TransactionCase):
    """Un client, un service « transport de véhicule »."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service_vehicule = cls.env["dally.service.type"].search(
            [("code", "=", "freight_vehicle")], limit=1
        )
        cls.service_maritime = cls.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1
        )

    def _devis(self, nom, service=None):
        partenaire = self.env["res.partner"].create({"name": f"Veh {nom}"})
        return self.env["dally.quote.request"].create({
            "partner_id": partenaire.id,
            "contact_name": f"Veh {nom}",
            "company_name": f"Veh {nom}",
            "service_type_id": (service or self.service_vehicule).id,
            "email": f"veh-{nom.lower()}@test.invalid",
            "request_uuid": str(uuid.uuid4()),
            "origin_city": "Paris",
            "destination_city": "Dakar",
        })

    def _vehicule(self, devis, mode="sea", **extra):
        valeurs = {
            "quote_request_id": devis.id,
            "make": "Toyota",
            "model": "Hilux",
            "year": "2019",
            "category": "van",
            "condition": "running",
            "transport_mode": mode,
        }
        valeurs.update(extra)
        return self.env["dally.freight.vehicle.cargo"].create(valeurs)

    def _chaine(self, devis):
        """Retourne `(bookings, expéditions tk, projections, véhicules)`."""
        bookings = self.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", devis.id)]
        )
        expeditions = self.env["freight.shipment"].sudo().search(
            [("booking_id", "in", bookings.ids)]
        )
        projections = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "in", expeditions.ids)]
        )
        vehicules = self.env["dally.freight.vehicle.cargo"].sudo().search(
            [("quote_request_id", "=", devis.id)]
        )
        return len(bookings), len(expeditions), len(projections), len(vehicules)

    def _refuse(self, devis, motif_attendu):
        """Accepte le devis en exigeant un refus **et** un rollback complet.

        Le savepoint reproduit la frontière de transaction d'une requête HTTP :
        sans lui, l'écriture de `state` déjà passée resterait en base et le test
        conclurait à tort que rien n'a été annulé.
        """
        etat_initial = devis.state
        try:
            with self.env.cr.savepoint():
                devis.write({"state": "won"})
        except UserError as refus:
            self.assertIn(motif_attendu, str(refus))
        else:
            self.fail("Le provisionnement aurait du etre refuse.")

        self.env.invalidate_all()
        self.assertEqual(devis.state, etat_initial, "L'etat du devis n'est pas restaure.")
        self.assertEqual(
            self._chaine(devis)[:3], (0, 0, 0),
            "Des enregistrements fret subsistent apres le refus.",
        )


@tagged("post_install", "-at_install", "dally_freight")
class TestVehicleModes(VehicleCommon):
    """Le mode physique vient du véhicule, jamais du service."""

    def _chaine_complete(self, devis):
        booking = self.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", devis.id)], limit=1
        )
        expedition = self.env["freight.shipment"].sudo().search(
            [("booking_id", "=", booking.id)], limit=1
        )
        projection = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "=", expedition.id)], limit=1
        )
        return expedition, projection

    def test_vehicule_maritime_produit_une_expedition_ocean(self):
        """Le cas DallyTrading par excellence : Paris → Dakar par bateau.

        Une version antérieure aurait traduit « transport de véhicule » par
        routier. La voiture serait partie sur un roulier avec une expédition
        étiquetée `land`.
        """
        devis = self._devis("Sea")
        self._vehicule(devis, mode="sea")
        devis.write({"state": "won"})

        expedition, projection = self._chaine_complete(devis)
        self.assertEqual(expedition.transport, "ocean")
        self.assertEqual(projection.transport_mode, "sea")
        self.assertEqual(self._chaine(devis), (1, 1, 1, 1))

    def test_vehicule_routier_produit_une_expedition_land(self):
        devis = self._devis("Road")
        self._vehicule(devis, mode="road")
        devis.write({"state": "won"})

        expedition, projection = self._chaine_complete(devis)
        self.assertEqual(expedition.transport, "land")
        self.assertEqual(projection.transport_mode, "road")
        self.assertEqual(self._chaine(devis), (1, 1, 1, 1))

    def test_le_vehicule_est_rattache_a_l_expedition(self):
        devis = self._devis("Lien")
        vehicule = self._vehicule(devis, mode="sea")
        devis.write({"state": "won"})

        _expedition, projection = self._chaine_complete(devis)
        self.assertEqual(vehicule.shipment_id, projection)

    def test_un_devis_vehicule_sans_vehicule_est_refuse(self):
        """Le service annonce un véhicule ; aucun n'est décrit.

        Provisionner ici reviendrait à inventer un mode de transport.
        """
        self._refuse(self._devis("SansVehicule"), "aucun véhicule")

    def test_un_mode_inconnu_est_refuse_par_le_champ(self):
        """`multimodal` n'est pas provisionnable : la sélection le refuse.

        Le fail-closed est ici porté par le modèle et non par le pont, ce qui
        est plus fort : aucun appelant ne peut le contourner.
        """
        devis = self._devis("ModeInconnu")
        with self.assertRaises(ValueError):
            self._vehicule(devis, mode="multimodal")

    def test_un_devis_non_vehicule_reste_inchange(self):
        """Contrôle de non-régression : le fret maritime classique fonctionne."""
        devis = self._devis("Maritime", service=self.service_maritime)
        devis.write({"state": "won"})
        expedition, projection = self._chaine_complete(devis)
        self.assertEqual(expedition.transport, "ocean")
        self.assertEqual(projection.transport_mode, "sea")


@tagged("post_install", "-at_install", "dally_freight")
class TestVehicleIdempotence(VehicleCommon):
    """Un devis véhicule traité n fois produit toujours 1/1/1/1."""

    def test_reecrire_le_meme_etat_ne_duplique_rien(self):
        devis = self._devis("Rejeu")
        self._vehicule(devis)
        devis.write({"state": "won"})
        devis.write({"state": "won"})
        self.assertEqual(self._chaine(devis), (1, 1, 1, 1))

    def test_dix_appels_directs_restent_idempotents(self):
        devis = self._devis("Dix")
        self._vehicule(devis)
        devis.write({"state": "won"})
        for _ in range(10):
            devis._dally_freight_provision()
        self.assertEqual(self._chaine(devis), (1, 1, 1, 1))

    def test_le_vehicule_n_est_pas_deplace_par_une_resynchronisation(self):
        devis = self._devis("Stable")
        vehicule = self._vehicule(devis)
        devis.write({"state": "won"})
        attendu = vehicule.shipment_id
        for _ in range(5):
            devis._dally_freight_provision()
        self.assertEqual(vehicule.shipment_id, attendu)

    def test_un_seul_vehicule_par_devis(self):
        """Contrainte en base, pas applicative.

        C'est elle qui tient sous deux soumissions concurrentes du formulaire
        public, là où un `search` suivi d'un `create` laisserait passer un
        doublon.
        """
        devis = self._devis("Unique")
        self._vehicule(devis)
        with self.assertRaises(Exception):
            self._vehicule(devis).flush_recordset(["quote_request_id"])


@tagged("post_install", "-at_install", "dally_freight")
class TestVehicleValidation(VehicleCommon):
    """Les données du véhicule sont bornées et nettoyées."""

    def test_le_vin_est_normalise(self):
        devis = self._devis("Vin")
        vehicule = self._vehicule(devis, vin="  jt1234567890abcd  ")
        self.assertEqual(vehicule.vin, "JT1234567890ABCD")

    def test_un_vin_court_mais_plausible_est_accepte(self):
        """Les véhicules anciens n'ont pas de VIN de 17 caractères.

        Refuser un dossier légitime pour cette raison coûte plus cher que
        d'accepter un numéro atypique : le client abandonne, et personne ne sait
        pourquoi.
        """
        devis = self._devis("VinCourt")
        vehicule = self._vehicule(devis, vin="ABC123")
        self.assertEqual(vehicule.vin, "ABC123")

    def test_un_vin_absurde_est_refuse(self):
        devis = self._devis("VinAbsurde")
        with self.assertRaises(ValidationError):
            self._vehicule(devis, vin="AB")

    def test_un_vin_avec_balise_est_refuse(self):
        devis = self._devis("VinBalise")
        with self.assertRaises(ValidationError):
            self._vehicule(devis, vin="<script>alert(1)</script>")

    def test_les_champs_reaffiches_refusent_les_balises(self):
        devis = self._devis("Balise")
        with self.assertRaises(ValidationError):
            self._vehicule(devis, make="<img onerror=x>")

    def test_un_enlevement_sans_adresse_est_refuse(self):
        devis = self._devis("Enlevement")
        with self.assertRaises(ValidationError):
            self._vehicule(devis, pickup_requested=True, pickup_address="")

    def test_un_nombre_de_cles_absurde_est_refuse(self):
        devis = self._devis("Cles")
        with self.assertRaises(ValidationError):
            self._vehicule(devis, key_count=99)


@tagged("post_install", "-at_install", "dally_freight")
class TestVehicleSecurity(VehicleCommon):
    """Le portail n'atteint jamais le modèle interne."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groupe = cls.env.ref("base.group_portal")
        cls.client_a = cls.env["res.users"].create({
            "name": "Veh Portail A", "login": "veh.a@dally.invalid",
            "partner_id": cls.env["res.partner"].create({"name": "Veh Societe A"}).id,
            "group_ids": [(6, 0, [groupe.id])],
        })
        cls.client_b = cls.env["res.users"].create({
            "name": "Veh Portail B", "login": "veh.b@dally.invalid",
            "partner_id": cls.env["res.partner"].create({"name": "Veh Societe B"}).id,
            "group_ids": [(6, 0, [groupe.id])],
        })

    def _vehicule_de(self, utilisateur, nom):
        devis = self.env["dally.quote.request"].create({
            "partner_id": utilisateur.partner_id.id,
            "contact_name": nom, "company_name": nom,
            "service_type_id": self.service_vehicule.id,
            "email": f"{nom}@test.invalid",
            "request_uuid": str(uuid.uuid4()),
        })
        return self._vehicule(devis)

    def test_le_portail_n_a_aucun_acces_au_modele_vehicule(self):
        """Aucune ACL portail n'est déclarée, et c'est délibéré.

        Une ACL en lecture seule serait déjà une surface à borner par record
        rule, pour un besoin qui n'existe pas : le client lit une projection.
        """
        vehicule = self._vehicule_de(self.client_a, "VehA")
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env(user=self.client_a)["dally.freight.vehicle.cargo"].browse(
                vehicule.id
            ).read(["make"])

    def test_le_portail_ne_peut_pas_ecrire(self):
        vehicule = self._vehicule_de(self.client_a, "VehEcriture")
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env(user=self.client_a)["dally.freight.vehicle.cargo"].browse(
                vehicule.id
            ).write({"make": "MODIFIE"})

    def test_le_portail_ne_peut_pas_creer(self):
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env(user=self.client_a)["dally.freight.vehicle.cargo"].create({
                "quote_request_id": 1, "make": "X", "model": "Y",
                "category": "car", "condition": "running", "transport_mode": "sea",
            })

    def test_le_portail_ne_peut_pas_supprimer(self):
        vehicule = self._vehicule_de(self.client_a, "VehSuppr")
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env(user=self.client_a)["dally.freight.vehicle.cargo"].browse(
                vehicule.id
            ).unlink()

    def test_le_vehicule_d_un_client_est_invisible_a_un_autre(self):
        """Le cloisonnement ne repose pas sur l'absence d'ACL seule.

        Même si une ACL était rétablie par erreur, la recherche sous B ne doit
        pas remonter le véhicule de A.
        """
        vehicule_a = self._vehicule_de(self.client_a, "VehCloisonA")
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env(user=self.client_b)["dally.freight.vehicle.cargo"].search(
                [("id", "=", vehicule_a.id)]
            )

    def test_les_champs_internes_ne_sont_pas_charges_pour_le_portail(self):
        """`internal_notes` et `purchase_price` portent `groups=`.

        Ils ne sont pas masqués à l'affichage : l'ORM ne les charge pas.
        """
        champs = self.env(user=self.client_a)["dally.freight.vehicle.cargo"].fields_get()
        for interdit in ("internal_notes", "purchase_price"):
            self.assertNotIn(interdit, champs)
