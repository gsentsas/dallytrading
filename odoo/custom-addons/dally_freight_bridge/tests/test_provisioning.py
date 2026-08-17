"""
Tests du provisionnement fret et de sa projection.

Chaque assertion correspond à une mesure faite sur la stack jetable, pas à une
intention : le workflow du fournisseur a été exécuté avant d'être décrit.
"""

import uuid

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_freight_bridge.models.freight_mapping import (
    STAGE_XMLID_TO_STATE,
    mode_from_transport,
    state_from_stage,
)


class ProvisioningCommon(TransactionCase):
    """Un client, un devis prêt à être accepté."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # `freight_sea` explicitement, et non le premier service venu : le
        # provisionnement refuse désormais tout service dont le mode n'est pas
        # déductible, et le premier enregistrement est `import_export`.
        cls.service = cls.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1
        )

    @classmethod
    def _devis(cls, nom):
        partenaire = cls.env["res.partner"].create({"name": f"Prov {nom}"})
        return cls.env["dally.quote.request"].create({
            "partner_id": partenaire.id,
            "contact_name": f"Prov {nom}",
            "company_name": f"Prov {nom}",
            "service_type_id": cls.service.id,
            "email": f"prov-{nom.lower()}@test.invalid",
            "request_uuid": str(uuid.uuid4()),
        })

    def _compte(self, devis):
        """Retourne `(bookings, expéditions, projections)` pour ce devis."""
        bookings = self.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", devis.id)]
        )
        expeditions = self.env["freight.shipment"].sudo().search(
            [("booking_id", "in", bookings.ids)]
        )
        projections = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "in", expeditions.ids)]
        )
        return len(bookings), len(expeditions), len(projections)


@tagged("post_install", "-at_install", "dally_freight")
class TestProvisioning(ProvisioningCommon):
    """Un devis accepté produit exactement une chaîne opérationnelle."""

    def test_acceptation_provisionne_la_chaine_complete(self):
        devis = self._devis("Chaine")
        self.assertEqual(self._compte(devis), (0, 0, 0))

        devis.write({"state": "won"})

        self.assertEqual(
            self._compte(devis),
            (1, 1, 1),
            "L'acceptation doit produire un booking, une expedition et une projection.",
        )

    def test_le_courriel_du_fournisseur_est_supprime(self):
        """`convert_to_operation()` envoie en `force_send=True`.

        Mesuré sur le module nu : deux courriels « Your Booking … » partaient.
        La communication client appartient à DallyTrading.
        """
        avant = self.env["mail.mail"].sudo().search_count([])
        self._devis("Mail").write({"state": "won"})
        self.assertEqual(
            self.env["mail.mail"].sudo().search_count([]),
            avant,
            "Le courriel du fournisseur est parti.",
        )

    def test_la_projection_ne_porte_aucun_montant_interne(self):
        devis = self._devis("Montants")
        devis.write({"state": "won"})
        projection = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "!=", False)], order="id desc", limit=1
        )
        for champ in ("supplier_cost", "margin"):
            self.assertFalse(
                projection[champ],
                f"La projection porte un montant interne ({champ}).",
            )


@tagged("post_install", "-at_install", "dally_freight")
class TestIdempotence(ProvisioningCommon):
    """Le même devis traité n fois produit toujours 1/1/1."""

    def test_reecrire_le_meme_etat_ne_provisionne_pas_deux_fois(self):
        devis = self._devis("Rejeu")
        devis.write({"state": "won"})
        devis.write({"state": "won"})
        self.assertEqual(self._compte(devis), (1, 1, 1))

    def test_dix_appels_directs_restent_idempotents(self):
        """Rejeu de hook, réexécution de méthode, mise à jour de module."""
        devis = self._devis("Dix")
        devis.write({"state": "won"})
        for _ in range(10):
            devis._dally_freight_provision()
        self.assertEqual(self._compte(devis), (1, 1, 1))

    def test_deux_devis_distincts_ont_chacun_leur_chaine(self):
        """Contrôle positif : l'idempotence ne doit pas coller deux dossiers."""
        premier = self._devis("Un")
        second = self._devis("Deux")
        premier.write({"state": "won"})
        second.write({"state": "won"})
        self.assertEqual(self._compte(premier), (1, 1, 1))
        self.assertEqual(self._compte(second), (1, 1, 1))
        self.assertNotEqual(
            self.env["shipment.freight.booking"].sudo().search(
                [("dally_quote_request_id", "=", premier.id)]
            ),
            self.env["shipment.freight.booking"].sudo().search(
                [("dally_quote_request_id", "=", second.id)]
            ),
        )

    def test_l_index_unique_refuse_un_second_booking(self):
        """Dernière barrière, indépendante de tout code applicatif."""
        devis = self._devis("Unique")
        devis.write({"state": "won"})
        with self.assertRaises(Exception):
            self.env["shipment.freight.booking"].sudo().create({
                "dally_quote_request_id": devis.id,
                "operator_id": self.env.user.id,
            }).flush_recordset(["dally_quote_request_id"])


@tagged("post_install", "-at_install", "dally_freight")
class TestMapping(ProvisioningCommon):
    """La traduction tk → Dally est centralisée et ferme sur l'inconnu."""

    def test_mode_maritime_et_aerien(self):
        self.assertEqual(mode_from_transport("ocean"), "sea")
        self.assertEqual(mode_from_transport("air"), "air")
        self.assertEqual(mode_from_transport("land"), "road")

    def test_mode_inconnu_ne_produit_rien(self):
        self.assertIsNone(mode_from_transport("teleportation"))

    def test_toutes_les_etapes_du_fournisseur_sont_mappees(self):
        """Une étape livrée par le fournisseur et non mappée est un trou."""
        for xmlid in STAGE_XMLID_TO_STATE:
            etape = self.env.ref(xmlid, raise_if_not_found=False)
            self.assertTrue(etape, f"Etape absente de l'instance : {xmlid}")
            self.assertEqual(
                state_from_stage(self.env, etape),
                STAGE_XMLID_TO_STATE[xmlid],
            )

    def test_une_etape_inconnue_ne_produit_pas_d_etat_final(self):
        """Le point le plus important du mapping.

        Annoncer « Livré » sur une expédition qui ne l'est pas est la pire
        sortie possible : le client cesse de suivre son dossier.
        """
        inventee = self.env["freight.shipment.stages"].sudo().create(
            {"name": "Etape ajoutee par une mise a jour", "sequence": 99}
        )
        self.assertIsNone(
            state_from_stage(self.env, inventee),
            "Une etape inconnue a ete traduite en un etat Dally.",
        )

    def test_une_etape_inconnue_laisse_l_etat_precedent(self):
        devis = self._devis("Etape")
        devis.write({"state": "won"})
        projection = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "!=", False)], order="id desc", limit=1
        )
        avant = projection.state

        expedition = projection.sudo().tk_shipment_id
        expedition.sudo().stage_id = self.env["freight.shipment.stages"].sudo().create(
            {"name": "Inconnue", "sequence": 98}
        )
        projection._dally_freight_sync_from_tk()

        self.assertEqual(
            projection.state, avant, "L'etat a change sur une etape inconnue."
        )


@tagged("post_install", "-at_install", "dally_freight")
class TestCloisonnementProjection(ProvisioningCommon):
    """Un client ne voit que sa propre projection."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groupe = cls.env.ref("base.group_portal")
        cls.devis_a = cls._devis("ClientA")
        cls.devis_b = cls._devis("ClientB")
        cls.devis_a.write({"state": "won"})
        cls.devis_b.write({"state": "won"})

        cls.user_a = cls.env["res.users"].create({
            "name": "Proj A", "login": "proj.a@dally.invalid",
            "partner_id": cls.devis_a.partner_id.id,
            "group_ids": [(6, 0, [groupe.id])],
        })
        cls.user_b = cls.env["res.users"].create({
            "name": "Proj B", "login": "proj.b@dally.invalid",
            "partner_id": cls.devis_b.partner_id.id,
            "group_ids": [(6, 0, [groupe.id])],
        })

    def _projection(self, devis):
        booking = self.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", devis.id)], limit=1
        )
        expedition = self.env["freight.shipment"].sudo().search(
            [("booking_id", "=", booking.id)], limit=1
        )
        return self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "=", expedition.id)], limit=1
        )

    def _lit(self, utilisateur, projection):
        # Cache vidé : il est porté par la transaction, pas par l'utilisateur.
        self.env.invalidate_all()
        return self.env(user=utilisateur)["dally.shipment"].browse(
            projection.id
        ).read(["reference"])

    def test_le_client_lit_sa_propre_projection(self):
        """Contrôle positif : sans lui, les refus ci-dessous ne prouveraient rien."""
        self.assertTrue(self._lit(self.user_a, self._projection(self.devis_a)))

    def test_le_client_ne_lit_pas_la_projection_d_autrui(self):
        with self.assertRaises(AccessError):
            self._lit(self.user_a, self._projection(self.devis_b))

    def test_le_cloisonnement_vaut_dans_les_deux_sens(self):
        with self.assertRaises(AccessError):
            self._lit(self.user_b, self._projection(self.devis_a))

    def test_le_client_n_atteint_pas_l_expedition_operationnelle(self):
        """`tk_shipment_id` est réservé au personnel interne.

        Le portail parle le langage Dally ; l'identifiant du fournisseur n'a pas
        à exister dans son contrat, même sur un enregistrement qui lui
        appartient.
        """
        projection = self._projection(self.devis_a)
        self.env.invalidate_all()
        champs = self.env(user=self.user_a)["dally.shipment"].fields_get()
        self.assertNotIn(
            "tk_shipment_id",
            champs,
            "Le portail voit le lien vers l'expedition du fournisseur.",
        )


@tagged("post_install", "-at_install", "dally_freight")
class TestGardeFouInvariant(ProvisioningCommon):
    """Le garde-fou doit détecter le NOUVEAU, pas relire une liste."""

    def test_aucune_anomalie_sur_une_instance_saine(self):
        self.assertIsNone(
            self.env["dally.freight.lockdown.guard"]._dally_audit_message()
        )

    def test_une_nouvelle_acl_vendeur_est_detectee(self):
        """Contrôle négatif : simule une ACL ajoutée par une mise à jour.

        Le modèle visé n'appartient à aucune liste écrite à la main — c'est
        exactement le cas qu'un inventaire figé laisserait passer.
        """
        garde = self.env["dally.freight.lockdown.guard"]
        modele = self.env["ir.model"].sudo().search(
            [("model", "=", "freight.port")], limit=1
        )
        self.env["ir.model.access"].sudo().create({
            "name": "acl ajoutee par une mise a jour vendeur",
            "model_id": modele.id,
            "group_id": self.env.ref("base.group_portal").id,
            "perm_read": True,
            "perm_write": True,
        })
        anomalie = garde._dally_audit_message()
        self.assertIsNotNone(anomalie, "Une nouvelle ACL vendeur n'est pas detectee.")
        self.assertIn("freight.port", anomalie)

    def test_les_acl_portail_du_noyau_ne_sont_pas_signalees(self):
        """Contrôle de non-régression du périmètre.

        Un premier critère, trop large, désignait `res.partner`, `sale.order`,
        `account.move` et `stock.picking` — des modèles du noyau que tk_freight
        se contente d'étendre. Les fermer aurait cassé le portail Odoo standard.
        """
        anomalie = self.env["dally.freight.lockdown.guard"]._dally_audit_message()
        self.assertIsNone(anomalie)
        for modele in ("res.partner", "sale.order", "account.move", "stock.picking"):
            self.assertTrue(
                self.env["ir.model.access"].sudo().search_count([
                    ("group_id", "=", self.env.ref("base.group_portal").id),
                    ("model_id.model", "=", modele),
                    ("perm_read", "=", True),
                ]),
                f"L'ACL portail du noyau sur {modele} a ete retiree.",
            )

    def test_toutes_les_routes_du_fournisseur_sont_couvertes(self):
        routes = self.env["dally.freight.lockdown.guard"]._dally_audit_tk_routes()
        self.assertEqual(
            routes, [], f"Routes tk_freight non neutralisees : {routes}"
        )


@tagged("post_install", "-at_install", "dally_freight")
class TestModes(ProvisioningCommon):
    """Le mode vient du service demandé, pas d'une valeur fixée en dur."""

    def _devis_pour(self, code, nom):
        service = self.env["dally.service.type"].search([("code", "=", code)], limit=1)
        self.assertTrue(service, f"Service {code} absent de l'instance.")
        partenaire = self.env["res.partner"].create({"name": f"Mode {nom}"})
        return self.env["dally.quote.request"].create({
            "partner_id": partenaire.id,
            "contact_name": f"Mode {nom}",
            "company_name": f"Mode {nom}",
            "service_type_id": service.id,
            "email": f"mode-{nom.lower()}@test.invalid",
            "request_uuid": str(uuid.uuid4()),
        })

    def _chaine(self, devis):
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

    def test_flux_maritime_de_bout_en_bout(self):
        devis = self._devis_pour("freight_sea", "Sea")
        devis.write({"state": "won"})
        expedition, projection = self._chaine(devis)
        self.assertEqual(expedition.transport, "ocean")
        self.assertEqual(projection.transport_mode, "sea")

    def test_flux_aerien_de_bout_en_bout(self):
        """Sans ce test, un mode fixé en dur créait toute expédition en maritime.

        C'était le cas de la première version : `_dally_freight_transport()`
        retournait `ocean` quel que soit le service demandé par le client.
        """
        devis = self._devis_pour("freight_air", "Air")
        devis.write({"state": "won"})
        expedition, projection = self._chaine(devis)
        self.assertEqual(expedition.transport, "air")
        self.assertEqual(projection.transport_mode, "air")

    def test_un_service_de_vehicule_est_refuse(self):
        """Le transport de véhicule est un métier distinct, non implémenté.

        Il retombait auparavant sur `land`. Créer une expédition routière pour
        un client qui a demandé un transport de véhicule est une réponse fausse,
        pas une approximation acceptable.
        """
        self._refuse_et_verifie_le_rollback("freight_vehicle", "Vehicule")

    def test_un_devis_hors_fret_s_accepte_sans_rien_creer(self):
        """Le refus ne doit pas déborder sur les autres métiers.

        Une première version refusait *tout* devis dont le service n'était ni
        maritime ni aérien. Un devis de sourcing devenait inacceptable, et la
        suite du portail se bloquait sur son test de concurrence. Un devis hors
        fret s'accepte donc normalement — il ne crée simplement aucune
        expédition.
        """
        devis = self._devis_pour("sourcing", "HorsFret")
        devis.write({"state": "won"})
        self.assertEqual(devis.state, "won")
        self.assertEqual(
            self._compte(devis), (0, 0, 0),
            "Un devis hors fret a provisionne une expedition.",
        )

    def test_un_service_import_export_ne_provisionne_pas(self):
        """`import_export` ne désigne aucun mode : rien n'est créé.

        La version précédente en faisait une expédition maritime, visible dans
        l'espace client, sans qu'aucun signal n'indique qu'il y avait quelque
        chose à corriger.
        """
        devis = self._devis_pour("import_export", "SansMode")
        devis.write({"state": "won"})
        self.assertEqual(self._compte(devis), (0, 0, 0))

    def test_un_groupage_est_refuse(self):
        """Le groupage est le plus souvent du LCL maritime — mais pas toujours.

        « Le plus souvent » n'est pas une base pour créer une expédition. Le
        groupage aérien existe ; il faudra une décision métier explicite.
        """
        self._refuse_et_verifie_le_rollback("freight_groupage", "Groupage")

    def _refuse_et_verifie_le_rollback(self, code, nom):
        """Le provisionnement est refusé ET rien ne subsiste.

        Le savepoint reproduit la frontière de transaction d'une requête HTTP :
        sans lui, l'écriture de `state` déjà passée resterait en base et le test
        conclurait à tort que le rollback n'a pas eu lieu.
        """
        devis = self._devis_pour(code, nom)
        etat_initial = devis.state

        try:
            with self.env.cr.savepoint():
                devis.write({"state": "won"})
        except UserError as refus:
            self.assertIn("mode de transport", str(refus))
        else:
            self.fail(f"Le service {code} aurait du etre refuse.")

        self.env.invalidate_all()
        self.assertEqual(
            devis.state, etat_initial, "L'etat du devis n'a pas ete restaure."
        )
        self.assertEqual(
            self._compte(devis), (0, 0, 0),
            "Des enregistrements fret subsistent apres le refus.",
        )


@tagged("post_install", "-at_install", "dally_freight")
class TestColisProjetes(ProvisioningCommon):
    """Les colis opérationnels sont projetés, sans aucun montant."""

    def test_les_colis_du_fournisseur_sont_projetes(self):
        devis = self._devis("Colis")
        devis.write({"state": "won"})
        booking = self.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", devis.id)], limit=1
        )
        expedition = self.env["freight.shipment"].sudo().search(
            [("booking_id", "=", booking.id)], limit=1
        )
        projection = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "=", expedition.id)], limit=1
        )

        # Colis créés côté opérationnel après le provisionnement, comme le ferait
        # l'exploitation en préparant l'envoi.
        self.env["shipment.package.line"].sudo().create({
            "shipment_id": expedition.id, "qty": 3,
            "net_weight": 12.5, "length": 100.0, "width": 80.0, "height": 60.0,
            "charges": 999.0,
        })
        projection._dally_freight_sync_from_tk()

        colis = self.env["dally.shipment.package"].sudo().search(
            [("shipment_id", "=", projection.id)]
        )
        self.assertEqual(len(colis), 1, "Le colis operationnel n'a pas ete projete.")
        self.assertEqual(colis.quantity, 3)
        self.assertEqual(colis.unit_weight_kg, 12.5)
        self.assertEqual(colis.length_cm, 100.0)

        # Contrôle négatif : le montant `charges` du fournisseur ne doit
        # apparaître nulle part dans la projection client.
        self.assertNotIn("999", repr(colis.read()))

    def test_la_projection_des_colis_est_idempotente(self):
        devis = self._devis("ColisRejeu")
        devis.write({"state": "won"})
        booking = self.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", devis.id)], limit=1
        )
        expedition = self.env["freight.shipment"].sudo().search(
            [("booking_id", "=", booking.id)], limit=1
        )
        projection = self.env["dally.shipment"].sudo().search(
            [("tk_shipment_id", "=", expedition.id)], limit=1
        )
        self.env["shipment.package.line"].sudo().create({
            "shipment_id": expedition.id, "qty": 1,
        })
        for _ in range(5):
            projection._dally_freight_sync_from_tk()
        self.assertEqual(
            self.env["dally.shipment.package"].sudo().search_count(
                [("shipment_id", "=", projection.id)]
            ),
            1,
            "La resynchronisation a duplique les colis.",
        )


@tagged("post_install", "-at_install", "dally_freight")
class TestProvisionnementSousUtilisateurPortail(ProvisioningCommon):
    """Le provisionnement doit aboutir quand c'est le CLIENT qui déclenche.

    Tous les autres tests s'exécutent en administrateur, et passaient donc sur
    un chemin que le client n'emprunte jamais. Une lecture de configuration
    ajoutée au provisionnement — le type de service, pour déterminer le mode —
    échouait en `AccessError` pour un utilisateur portail, et bloquait la suite
    sous concurrence. Ce test existe pour que cela ne puisse plus passer
    inaperçu.
    """

    def test_un_client_portail_declenche_le_provisionnement(self):
        devis = self._devis("Portail")
        client = self.env["res.users"].create({
            "name": "Prov Portail",
            "login": "prov.portail@dally.invalid",
            "partner_id": devis.partner_id.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })

        # Le client n'a aucun droit sur la configuration : c'est exactement la
        # situation qui faisait échouer le provisionnement.
        with self.assertRaises(AccessError):
            self.env(user=client)["dally.service.type"].search([], limit=1).read(["code"])

        devis.with_user(client)._dally_freight_provision()

        self.assertEqual(
            self._compte(devis),
            (1, 1, 1),
            "Le provisionnement declenche par un client portail n'aboutit pas.",
        )

    def test_l_operateur_du_dossier_n_est_jamais_un_client(self):
        """Un utilisateur portail ne peut pas être opérateur d'exploitation."""
        devis = self._devis("Operateur")
        client = self.env["res.users"].create({
            "name": "Prov Operateur",
            "login": "prov.operateur@dally.invalid",
            "partner_id": devis.partner_id.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        devis.with_user(client)._dally_freight_provision()

        booking = self.env["shipment.freight.booking"].sudo().search(
            [("dally_quote_request_id", "=", devis.id)], limit=1
        )
        self.assertFalse(
            booking.operator_id.share,
            "Un utilisateur portail est devenu operateur du dossier.",
        )
