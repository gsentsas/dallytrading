# -*- coding: utf-8 -*-
"""La politique, l'alignement, et la file — éprouvés là où ils peuvent mentir.

Trois familles d'assertions, dans l'ordre du risque.

**Le sens de l'échec.** Une politique manquante, archivée, ou qui ne publie
pas, doit rendre un état muet. C'est le comportement qui protège d'une fuite le
jour où quelqu'un ajoutera un état sans y penser, et c'est donc celui qui est
vérifié dans les deux sens : ce qui est publié l'est, et ce qui ne l'est pas ne
l'est pas.

**L'unicité.** Une vraie transition produit au plus un message ; réécrire le
même état n'en produit aucun. La propriété tient par la contrainte
`unique(event_id)` et par le fait qu'aucun événement n'est créé sans
transition — les deux sont mesurés, pas supposés.

**Le contenu.** Ce que la file retient doit suffire à écrire un courriel et ne
contenir rien qu'un client ne doive lire. La liste des champs est donc
inspectée en entier, et pas seulement échantillonnée : c'est la seule
formulation qui résiste à l'ajout d'une colonne.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dally_freight_notifications.models.dally_shipment_notification import (
    MOTIF_NON_PUBLIE,
    MOTIF_POLITIQUE,
    MOTIF_REFUS_CLIENT,
    MOTIF_SANS_ADRESSE,
    MOTIF_SANS_GABARIT,
)


@tagged("post_install", "-at_install", "dally")
class TestStatePolicy(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Politique = self.env["dally.freight.state.policy"]
        self.Notif = self.env["dally.shipment.notification"]
        self.service = self.env["dally.service.type"].search(
            [("code", "=", "freight_sea")], limit=1)
        self.client = self.env["res.partner"].create({
            "name": "Client suivi", "email": "suivi@example.invalid"})

    def _expedition(self, **valeurs):
        valeurs.setdefault("partner_id", self.client.id)
        valeurs.setdefault("service_type_id", self.service.id)
        valeurs.setdefault("transport_mode", "sea")
        return self.env["dally.shipment"].create(valeurs)

    def _notifications(self, expedition):
        return self.Notif.search([("shipment_id", "=", expedition.id)])

    def _gabarit(self):
        return self.env["mail.template"].create({
            "name": "Suivi — essai",
            "model_id": self.env["ir.model"]._get_id("dally.shipment.notification"),
            "subject": "{{ object.shipment_reference }}",
            "body_html": "<p>{{ object.customer_message }}</p>",
        })

    # ─── La politique ────────────────────────────────────────────────

    def test_les_quatorze_etats_ont_une_politique(self):
        etats_modele = {
            code for code, _libelle
            in self.env["dally.shipment"]._fields["state"].selection
        }
        etats_politique = set(self.Politique.search([]).mapped("state"))
        self.assertEqual(etats_politique, etats_modele)
        self.assertEqual(len(etats_politique), 14)

    def test_draft_reste_interne(self):
        politique = self.Politique._dally_policy_for("draft")
        self.assertFalse(politique.visible_in_portal)
        self.assertFalse(politique.visible_in_tracking)
        self.assertFalse(politique.notify_customer)

    def test_treize_etats_sont_visibles(self):
        self.assertEqual(
            self.Politique.search_count([("visible_in_portal", "=", True)]), 13)
        self.assertEqual(
            self.Politique.search_count([("visible_in_tracking", "=", True)]), 13)

    def test_preparing_se_voit_sans_notifier(self):
        politique = self.Politique._dally_policy_for("preparing")
        self.assertTrue(politique.visible_in_portal)
        self.assertTrue(politique.visible_in_tracking)
        self.assertFalse(politique.notify_customer)

    def test_douze_etats_notifient(self):
        notifiants = self.Politique.search([("notify_customer", "=", True)])
        self.assertEqual(len(notifiants), 12)
        self.assertNotIn("draft", notifiants.mapped("state"))
        self.assertNotIn("preparing", notifiants.mapped("state"))

    def test_un_etat_ne_peut_avoir_deux_politiques(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                self.Politique.create({"state": "draft", "customer_label": "Bis"})

    # ─── Le sens de l'échec ──────────────────────────────────────────

    def test_une_politique_absente_ferme_la_porte(self):
        """Ni publication, ni notification, pour un état sans politique."""
        self.Politique._dally_policy_for("customs").unlink()
        expedition = self._expedition()
        expedition.write({"state": "customs"})

        evenement = expedition.event_ids
        self.assertEqual(len(evenement), 1, "l'événement doit rester tracé")
        self.assertFalse(evenement.visible_to_customer)
        self.assertEqual(self._notifications(expedition).status, "skipped")
        self.assertFalse(expedition.dally_portal_visible)

    def test_une_politique_archivee_ferme_la_porte(self):
        self.Politique._dally_policy_for("arrived").active = False
        expedition = self._expedition()
        expedition.write({"state": "arrived"})

        self.assertFalse(expedition.event_ids.visible_to_customer)
        self.assertNotIn("arrived", self.env["dally.shipment"]._dally_public_state_wording())

    def test_les_libelles_publiables_viennent_de_la_politique(self):
        mots = self.env["dally.shipment"]._dally_public_state_wording()
        self.assertEqual(len(mots), 13)
        self.assertNotIn("draft", mots)
        self.assertEqual(mots["in_transit"],
                         self.Politique._dally_policy_for("in_transit").customer_label)

        # Modifier la donnée change la sortie : c'est bien elle la source.
        self.Politique._dally_policy_for("in_transit").customer_label = "Sur la route"
        self.assertEqual(
            self.env["dally.shipment"]._dally_public_state_wording()["in_transit"],
            "Sur la route")

    # ─── L'unicité ───────────────────────────────────────────────────

    def test_une_vraie_transition_produit_un_evenement_et_une_notification(self):
        expedition = self._expedition()
        self.assertFalse(expedition.event_ids)
        self.assertFalse(self._notifications(expedition))

        expedition.write({"state": "in_transit"})
        self.assertEqual(len(expedition.event_ids), 1)
        self.assertEqual(len(self._notifications(expedition)), 1)

    def test_reecrire_le_meme_etat_ne_produit_rien(self):
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        expedition.write({"state": "in_transit"})
        expedition.write({"state": "in_transit"})

        self.assertEqual(len(expedition.event_ids), 1)
        self.assertEqual(len(self._notifications(expedition)), 1)

    def test_un_evenement_ne_peut_porter_deux_notifications(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        evenement = expedition.event_ids

        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                self.Notif.create({
                    "shipment_id": expedition.id, "event_id": evenement.id,
                })

    def test_un_evenement_saisi_a_la_main_ne_notifie_pas(self):
        """Il décrit souvent un fait intermédiaire ; écrire au client reste une
        décision explicite."""
        expedition = self._expedition()
        self.env["dally.shipment.event"].create({
            "shipment_id": expedition.id, "status": "in_transit",
            "description": "Passage au port de Dakar",
        })
        self.assertFalse(self._notifications(expedition))

    # ─── Les motifs d'abstention ─────────────────────────────────────

    def test_un_evenement_non_publie_ne_devient_jamais_un_courriel(self):
        """La condition première, et elle porte sur le chemin.

        On n'écrit au client que sur ce qu'on lui montre. Un événement créé
        fermé — c'est ainsi que la synchronisation du fournisseur les crée, en
        écrivant `visible_to_customer=False` en dur sans jamais consulter la
        politique — reste inenvoyable **quel que soit son état**, y compris un
        état par ailleurs publiable et notifiable.

        C'est ce qui interdit qu'un mapping du fournisseur vers un état public
        transforme un fait d'exploitation en courriel client.
        """
        self.Politique._dally_policy_for("in_transit").email_template_id = self._gabarit()
        expedition = self._expedition()

        ferme = self.env["dally.shipment.event"].create({
            "shipment_id": expedition.id,
            "status": "in_transit",
            "description": "Projeté depuis le fournisseur",
            "visible_to_customer": False,
            "is_automatic": True,
        })
        ligne = self.Notif.search([("event_id", "=", ferme.id)])
        self.assertTrue(ligne, "la file doit garder la trace de l'abstention")
        self.assertEqual(ligne.status, "skipped")
        self.assertEqual(ligne.last_error, MOTIF_NON_PUBLIE)

    def test_sans_gabarit_la_notification_est_ignoree(self):
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        notification = self._notifications(expedition)
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_SANS_GABARIT)

    def test_un_etat_non_notifiant_est_ignore_avec_son_motif(self):
        self.Politique._dally_policy_for("preparing").email_template_id = self._gabarit()
        expedition = self._expedition()
        expedition.write({"state": "preparing"})
        notification = self._notifications(expedition)
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_POLITIQUE)

    def test_sans_adresse_la_notification_est_ignoree(self):
        self.Politique._dally_policy_for("in_transit").email_template_id = self._gabarit()
        muet = self.env["res.partner"].create({"name": "Sans adresse"})
        expedition = self._expedition(partner_id=muet.id)
        expedition.write({"state": "in_transit"})
        notification = self._notifications(expedition)
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_SANS_ADRESSE)

    def test_un_client_qui_refuse_est_ignore(self):
        self.Politique._dally_policy_for("in_transit").email_template_id = self._gabarit()
        self.client.dally_freight_notify = False
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        notification = self._notifications(expedition)
        self.assertEqual(notification.status, "skipped")
        self.assertEqual(notification.last_error, MOTIF_REFUS_CLIENT)

    def test_tout_reuni_la_notification_attend_son_envoi(self):
        """Le contrôle positif : sans lui, les quatre tests ci-dessus
        passeraient même si rien ne pouvait jamais être mis en attente."""
        self.Politique._dally_policy_for("in_transit").email_template_id = self._gabarit()
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        notification = self._notifications(expedition)
        self.assertEqual(notification.status, "pending")
        self.assertFalse(notification.last_error)
        self.assertEqual(notification.email, "suivi@example.invalid")
        self.assertEqual(notification.attempts, 0)

    def test_le_consentement_est_accorde_par_defaut(self):
        self.assertTrue(
            self.env["res.partner"].create({"name": "Nouveau"}).dally_freight_notify)

    # ─── Le contenu figé ─────────────────────────────────────────────

    def test_la_photographie_suffit_a_ecrire_un_message(self):
        expedition = self._expedition(origin_city="Le Havre", destination_city="Dakar")
        expedition.write({"state": "in_transit"})
        notification = self._notifications(expedition)

        self.assertEqual(notification.shipment_reference, expedition.reference)
        self.assertEqual(notification.customer_label, "En transit")
        self.assertTrue(notification.customer_message)
        self.assertIn("Le Havre", notification.origin_label)
        self.assertIn("Dakar", notification.destination_label)
        self.assertTrue(notification.event_date)
        self.assertIn("/tracking?ref=", notification.tracking_url)

    def test_la_file_ne_porte_aucun_champ_sensible(self):
        """Le gabarit lira ces colonnes et rien d'autre ; ce qui n'y est pas ne
        peut pas fuir dans un courriel rendu en superutilisateur."""
        interdits = ("cost", "margin", "supplier", "internal", "carrier",
                     "purchase", "price", "note")
        for champ in self.Notif._fields:
            for interdit in interdits:
                self.assertNotIn(interdit, champ, champ)

    def test_le_lien_de_suivi_ne_porte_aucun_identifiant(self):
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        url = self._notifications(expedition).tracking_url
        self.assertNotIn("/id/", url)
        self.assertNotIn("=%s" % expedition.id, url)

    # ─── L'alignement ────────────────────────────────────────────────

    def test_le_badge_porte_le_mot_du_client_et_le_code_reste(self):
        """`status` est le code que consomment les DTO du site : il ne bouge
        pas. Seul `statusLabel` devient le libellé de la politique."""
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        charge = expedition._dally_public_payload()
        self.assertEqual(charge["status"], "in_transit")
        self.assertEqual(charge["statusLabel"], "En transit")

    def test_portail_et_suivi_lisent_la_meme_politique(self):
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        self.assertTrue(expedition.dally_portal_visible)
        self.assertTrue(expedition.event_ids.visible_to_customer)
        self.assertEqual(len(expedition._dally_portal_timeline()), 1)

        # On retire l'état du portail : la frise portail se vide, le suivi
        # public garde son événement. Deux décisions, une seule table.
        self.Politique._dally_policy_for("in_transit").visible_in_portal = False
        expedition.invalidate_recordset()
        self.assertFalse(expedition.dally_portal_visible)
        self.assertEqual(len(expedition._dally_portal_timeline()), 0)
        self.assertTrue(expedition.event_ids.visible_to_customer)

    def test_un_client_ne_voit_jamais_le_dossier_d_un_autre(self):
        """Le canari de cette étape.

        Une première version ajoutait une **seconde** règle sur le groupe
        portail. Les règles d'un même groupe se combinent en OU : « mes
        dossiers » OU « états publiables » — et le client A voyait alors
        l'expédition du client B. Mesuré, puis corrigé en fusionnant la
        condition dans la règle existante. Ce test existe pour que l'erreur ne
        puisse pas revenir sans être vue.
        """
        autre = self.env["res.partner"].create({
            "name": "Autre client", "email": "autre@example.invalid"})
        sienne = self._expedition()
        celle_de_l_autre = self._expedition(partner_id=autre.id)
        sienne.write({"state": "in_transit"})
        celle_de_l_autre.write({"state": "in_transit"})

        portail = self.env["res.users"].create({
            "name": "Client portail", "login": "notif.canari@dallytrading.invalid",
            "partner_id": self.client.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        vues = self.env["dally.shipment"].with_user(portail).search([])
        self.assertIn(sienne, vues)
        self.assertNotIn(celle_de_l_autre, vues)

    def test_decocher_un_etat_retire_les_dossiers_deja_dedans(self):
        """Une décision qui ne s'applique pas est pire qu'une case grisée."""
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        self.assertTrue(expedition.dally_portal_visible)

        self.Politique._dally_policy_for("in_transit").visible_in_portal = False
        expedition.invalidate_recordset()
        self.assertFalse(expedition.dally_portal_visible)

    def test_un_salarie_continue_de_voir_les_brouillons(self):
        """La règle d'état ne vise que les externes.

        Elle est **globale** — donc liée par ET à tout le reste — et son domaine
        est conditionnel : vide pour un salarié, restrictif pour un utilisateur
        partagé. Sans ce test, une globale inconditionnelle priverait
        l'exploitation de ses propres brouillons sans que rien ne l'annonce.
        """
        interne = self.env["res.users"].create({
            "name": "Salarié", "login": "notif.interne@dallytrading.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("dally_core.group_dally_readonly").id])],
        })
        brouillon = self._expedition()
        self.assertFalse(brouillon.dally_portal_visible)
        self.assertIn(
            brouillon,
            self.env["dally.shipment"].with_user(interne).search([]))

    def test_la_regle_de_dally_portal_n_est_pas_ecrasee(self):
        """Un `-u dally_portal` seul ne doit plus pouvoir défaire la politique.

        La condition d'état vit dans une règle **globale** qui nous appartient,
        et non dans le domaine de la règle du module voisin. Ce test vérifie que
        ce domaine est resté celui de `dally_portal` : s'il portait notre
        condition, une mise à jour de ce module la ferait disparaître en
        silence.
        """
        regle_portail = self.env.ref("dally_portal.rule_portal_shipment")
        self.assertNotIn("dally_portal_visible", regle_portail.domain_force)

        notre_regle = self.env.ref(
            "dally_freight_notifications.dally_shipment_state_visibility_rule")
        self.assertFalse(notre_regle.groups, "la règle doit être globale")
        self.assertTrue(notre_regle["global"])
        self.assertIn("user.share", notre_regle.domain_force)

    def test_le_suivi_public_revoque_aussi_l_historique(self):
        """Décocher « visible au suivi » retire les anciens événements.

        La publication de l'événement est un fait historique, et elle reste
        écrite. Ce qui doit être révocable, c'est sa **sortie** par l'API : sans
        cela, une politique modifiée ne changerait rien à ce qu'un client peut
        déjà consulter.
        """
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        charge = expedition._dally_public_payload()
        self.assertEqual(len(charge["timeline"]), 1)
        self.assertTrue(charge["lastUpdate"])

        self.Politique._dally_policy_for("in_transit").visible_in_tracking = False
        charge = expedition._dally_public_payload()
        self.assertEqual(len(charge["timeline"]), 0)
        self.assertIsNone(charge["lastUpdate"])
        # L'événement lui-même n'a pas été réécrit : l'histoire est intacte.
        self.assertTrue(expedition.event_ids.visible_to_customer)

    def test_le_provisionnement_sort_du_brouillon(self):
        """Un devis fret accepté rend le dossier visible immédiatement.

        La projection naissait en brouillon et y restait : le client dont le
        devis venait d'être accepté ne voyait rien. Elle doit désormais finir en
        `request_received`, par le chemin normal — donc avec sa date de
        changement, son événement de suivi et sa notification.
        """
        import uuid as _uuid
        devis = self.env["dally.quote.request"].create({
            "service_type_id": self.service.id,
            "partner_id": self.client.id,
            "contact_name": "Client provisionné",
            "email": "provision@example.invalid",
            "request_uuid": str(_uuid.uuid4()),
        })
        devis.write({"state": "won"})

        projection = self.env["dally.shipment"].sudo().search(
            [("partner_id", "=", self.client.commercial_partner_id.id)],
            order="id desc", limit=1)
        self.assertTrue(projection, "aucune projection créée")
        self.assertEqual(projection.state, "request_received")
        self.assertTrue(projection.state_changed_on)
        self.assertTrue(projection.dally_portal_visible)

        evenements = projection.event_ids.filtered(
            lambda e: e.status == "request_received")
        self.assertEqual(len(evenements), 1)
        self.assertEqual(
            len(self.Notif.search([("event_id", "in", evenements.ids)])), 1)

    def test_le_client_voit_immediatement_son_dossier_provisionne(self):
        import uuid as _uuid
        portail = self.env["res.users"].create({
            "name": "Client provisionné", "login": "notif.prov@dallytrading.invalid",
            "partner_id": self.client.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        devis = self.env["dally.quote.request"].create({
            "service_type_id": self.service.id,
            "partner_id": self.client.id,
            "contact_name": "Client", "email": "prov2@example.invalid",
            "request_uuid": str(_uuid.uuid4()),
        })
        devis.write({"state": "won"})

        projection = self.env["dally.shipment"].sudo().search(
            [("partner_id", "=", self.client.commercial_partner_id.id)],
            order="id desc", limit=1)
        self.assertIn(
            projection,
            self.env["dally.shipment"].with_user(portail).search([]))

    # ─── Les canaris du `sudo` ───────────────────────────────────────

    def test_le_sudo_de_la_politique_n_ouvre_aucune_ecriture(self):
        """Lire la configuration n'est pas la modifier.

        `_dally_policy_for` et `_dally_labels_by_state` passent en `sudo` parce
        que le portail et l'utilisateur d'API n'ont aucune ACL sur la table de
        politique — et ils n'en ont pas besoin : ils en subissent l'effet, ils ne
        la consultent pas. Ce que ce test refuse, c'est que ce contournement de
        lecture se transforme en droit d'écriture.
        """
        lecteur = self.env["res.users"].create({
            "name": "Lecteur", "login": "notif.lecteur@dallytrading.invalid",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("dally_core.group_dally_readonly").id])],
        })
        politique = self.Politique.with_user(lecteur)._dally_policy_for("in_transit")
        self.assertTrue(politique.customer_label, "la lecture doit aboutir")
        with self.assertRaises(AccessError):
            politique.with_user(lecteur).write({"notify_customer": False})

    def test_le_sudo_de_la_file_n_ouvre_aucune_lecture(self):
        """Écrire la file en `sudo` ne la rend pas lisible.

        La ligne d'outbox est créée en `sudo` parce que l'opérateur qui fait
        avancer un dossier — ou l'utilisateur d'API — n'a pas le droit de créer
        cet enregistrement technique. Ce test vérifie que ce droit d'écriture
        technique n'a pas emporté un droit de lecture : un client portail ne
        doit pas pouvoir consulter ce qu'on écrit à son sujet, ni a fortiori ce
        qu'on écrit aux autres.
        """
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        self.assertTrue(self._notifications(expedition))

        portail = self.env["res.users"].create({
            "name": "Client portail", "login": "notif.sudo@dallytrading.invalid",
            "partner_id": self.client.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        self.assertFalse(self.Notif.with_user(portail).has_access("read"))
        with self.assertRaises(AccessError):
            self.Notif.with_user(portail).search([])

    def test_aucun_sudo_n_elargit_une_lecture_metier(self):
        """Le canari central : les champs protégés le restent.

        Le calcul de la charge publique et la mise en file passent tous deux par
        `sudo` en interne. Si l'un d'eux laissait fuiter son environnement
        élevé, un lecteur restreint pourrait ensuite lire un coût ou une note
        interne sur l'expédition. On le vérifie **après** avoir provoqué ces
        deux chemins.
        """
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        expedition._dally_public_payload()

        api = self.env["res.users"].create({
            "name": "Utilisateur API", "login": "notif.api@dallytrading.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        vue_api = expedition.with_user(api)
        for champ in ("supplier_cost", "margin", "internal_notes"):
            with self.assertRaises(AccessError, msg=champ):
                vue_api.read([champ])

    def test_la_charge_publique_ne_porte_rien_de_sensible(self):
        expedition = self._expedition()
        expedition.write({"state": "in_transit"})
        charge = repr(expedition._dally_public_payload())
        for interdit in ("supplier", "margin", "internal", "cost", "purchase"):
            self.assertNotIn(interdit, charge, interdit)

    def test_le_portail_ne_voit_pas_une_expedition_en_brouillon(self):
        portail = self.env["res.users"].create({
            "name": "Client portail", "login": "notif.portail@dallytrading.invalid",
            "partner_id": self.client.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        brouillon = self._expedition()
        self.assertFalse(brouillon.dally_portal_visible)
        self.assertNotIn(
            brouillon,
            self.env["dally.shipment"].with_user(portail).search([]))

        brouillon.write({"state": "in_transit"})
        self.assertTrue(brouillon.dally_portal_visible)
