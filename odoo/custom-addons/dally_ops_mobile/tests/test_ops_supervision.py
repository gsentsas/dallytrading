# -*- coding: utf-8 -*-
"""Ce qui demande une décision, et ce que le tableur a reçu.

## Ce que ces tests protègent

**Le droit d'en connaître.** Les deux lectures traversent tous les dossiers de
la société. Un logisticien ne les obtient pas — et le refus est prononcé par le
serveur, pas par l'écran. Un test le vérifie sur le service lui-même, là où une
requête forgée arriverait.

**Ce qui ne descend pas.** Aucune clé primaire Odoo, aucun `last_error`. La
vérification est structurelle : on parcourt le DTO et on refuse les clés
interdites, plutôt que de chercher un nombre dans du texte — ce qui
retrouverait un identifiant au hasard dans une référence de dossier.

**La distinction entre les deux files.** L'outbox d'Odoo et la file de
l'appareil sont deux systèmes. Le résumé de projection ne doit porter que la
première.
"""
import uuid

from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.dally_ops_mobile.models import ops_anomaly_service

from .test_ops_reconciliation import CLES_INTERDITES, SocleReconciliation


@tagged("post_install", "-at_install", "dally")
class TestOpsSupervision(SocleReconciliation):
    """Réutilise le décor de la réconciliation : même société, mêmes comptes.

    Le socle ne porte aucun test : hériter de la classe de test rejouerait ses
    vingt-six cas sous un second nom, pour rien.
    """

    def _anomalies(self, utilisateur=None):
        """Retourne les anomalies visibles par l'utilisateur de test."""
        return (self.env["dally.ops.anomaly.service"]
                .with_user(utilisateur or self.responsable)
                .with_company(self.societe).list_anomalies())

    def _projection(self, utilisateur=None):
        """Retourne le résumé de projection visible par l'utilisateur de test."""
        return (self.env["dally.ops.sheet.outbox"]
                .with_user(utilisateur or self.responsable)
                .with_company(self.societe).supervision_summary())

    def _types(self, resultat):
        """Extrait les types d'anomalies pour des assertions lisibles."""
        return {anomalie["type"] for anomalie in resultat["anomalies"]}

    # ------------------------------------------------------------------
    # Le droit d'en connaître
    # ------------------------------------------------------------------

    def test_a_logistician_is_refused_the_anomaly_list(self):
        """Le refus vient du serveur, pas de l'écran.

        L'écran cache aussi l'entrée, mais cacher n'est pas protéger : une
        requête forgée arriverait ici.
        """
        with self.assertRaises(AccessError):
            self._anomalies(self.gilles)

    def test_a_logistician_is_refused_the_projection_summary(self):
        """Vérifie le scénario « a logistician is refused the projection summary »."""
        with self.assertRaises(AccessError):
            self._projection(self.gilles)

    def test_a_supervisor_gets_both(self):
        """Le contre-test : sans lui, deux routes cassées passeraient pour sûres."""
        self.assertIn("anomalies", self._anomalies())
        self.assertIn("counts", self._projection())

    # ------------------------------------------------------------------
    # Ce que la liste contient
    # ------------------------------------------------------------------

    def test_an_unbilled_package_is_reported(self):
        """Le scénario tardif synthétique : de la marchandise réelle qu'aucune pièce ne couvre."""
        reference, shipment, _facture = self._dossier_facture()
        self.assertNotIn("UNBILLED_PACKAGE", self._types(self._anomalies()))

        self._service_ligne().add_late_line(reference, self._ligne_tardive())

        resultat = self._anomalies()
        self.assertIn("UNBILLED_PACKAGE", self._types(resultat))
        signalee = next(a for a in resultat["anomalies"]
                        if a["type"] == "UNBILLED_PACKAGE")
        self.assertEqual(signalee["reference"], shipment.external_reference)
        self.assertEqual(signalee["action"], "open_intake")

    def test_a_dossier_from_another_channel_is_never_signalled(self):
        """Une anomalie ne doit désigner qu'un dossier que la fiche sait ouvrir.

        Un dossier venu d'un autre canal peut remplir tous les autres critères
        — société, consolidation, facture comptabilisée, colis non couvert.
        S'il était signalé, l'écran afficherait « OUVRIR LE DOSSIER » vers une
        référence que la route Intake refuse de résoudre : un lien mort, et un
        responsable envoyé chercher là où il n'y a rien.

        Le service partage donc le domaine du service de ligne, plutôt que
        d'en écrire un plus large.
        """
        reference, shipment, _facture = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())
        self.assertIn(
            shipment.external_reference,
            [a["reference"] for a in self._anomalies()["anomalies"]])

        # Le même dossier, sorti du périmètre Ops par sa seule provenance :
        # `google_sheets` est la voie historique du classeur, et ces
        # dossiers-là n'ont pas de fiche Ops.
        shipment.sudo().sync_source = "google_sheets"
        self.assertNotIn(
            shipment.external_reference,
            [a["reference"] for a in self._anomalies()["anomalies"]],
            "un dossier hors Ops ne doit produire aucune anomalie")

    def test_a_dossier_without_an_invoice_is_not_an_anomaly(self):
        """Un dossier en cours de saisie n'a pas de colis « non facturé ».

        Confondre « pas encore facturé » et « non couvert » ferait sonner
        chaque saisie du jour.
        """
        self._creer_dossier()
        self.assertNotIn("UNBILLED_PACKAGE", self._types(self._anomalies()))

    def test_a_failed_projection_is_reported_without_its_transport_error(self):
        """Vérifie le scénario « a failed projection is reported without its transport error »."""
        _reference, shipment = self._creer_dossier()
        self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
        ligne = self.env["dally.ops.sheet.outbox"].sudo().search(
            [("company_id", "=", self.societe.id)], order="id desc", limit=1)
        ligne.write({
            "state": "failed",
            "last_error": "HTTP 500 depuis projection.invalid/transport",
        })

        resultat = self._anomalies()
        self.assertIn("SHEET_PROJECTION_FAILED", self._types(resultat))
        signalee = next(a for a in resultat["anomalies"]
                        if a["type"] == "SHEET_PROJECTION_FAILED")
        self.assertEqual(signalee["severity"], "high")
        # Rien à ouvrir : un incident de transport ne se règle pas dans une fiche.
        self.assertIsNone(signalee["action"])
        self.assertNotIn("projection.invalid", signalee["operator_message"])
        self.assertNotIn("HTTP 500", signalee["operator_message"])

    def _projection_en_vol(self, shipment):
        """Une ligne d'outbox du dossier, encore en attente d'envoi."""
        self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
        return self.env["dally.ops.sheet.outbox"].sudo().search(
            [("company_id", "=", self.societe.id)], order="id desc", limit=1)

    def test_a_retired_identity_is_not_reported_as_a_sheet_failure(self):
        """Une projection neutralisée volontairement ne demande aucune action.

        Le retrait passe par le chemin interne du modèle, pas par un accusé
        fabriqué : c'est ce chemin-là que la supervision doit savoir ignorer.
        """
        reference, shipment = self._creer_dossier()
        ligne = self._projection_en_vol(shipment)
        avant = self._projection()["counts"]["failed"]

        retirees = self.env["dally.ops.sheet.outbox"].sudo().retire_projections(
            self.societe, ligne.ids, reference)
        self.assertEqual(retirees, 1)

        resultat = self._anomalies()
        self.assertNotIn(
            reference, [a["reference"] for a in resultat["anomalies"]])
        self.assertEqual(self._projection()["counts"]["failed"], avant)

    def test_a_retired_projection_stays_in_the_outbox_for_audit(self):
        """Elle disparaît de la supervision, pas de la base.

        L'invariant tient en trois points : la ligne existe encore, elle porte
        `failed`, et son motif nomme la référence retirée. Relue depuis la base
        après invalidation du cache — un `write` suivi d'une lecture en mémoire
        ne prouverait pas que la valeur a été écrite.
        """
        reference, shipment = self._creer_dossier()
        ligne = self._projection_en_vol(shipment)
        identifiant = ligne.id

        self.env["dally.ops.sheet.outbox"].sudo().retire_projections(
            self.societe, ligne.ids, reference)
        self.env.invalidate_all()

        relue = self.env["dally.ops.sheet.outbox"].sudo().browse(identifiant)
        self.assertTrue(relue.exists(), "la ligne doit rester en base")
        self.assertEqual(relue.state, "failed")
        self.assertEqual(relue.last_error, "intake_identity_retired:%s" % reference)
        # Aucune tentative de transport n'a eu lieu : en simuler une fausserait
        # la lecture d'un incident réel.
        self.assertEqual(relue.attempt_count, 0)
        self.assertFalse(relue.last_attempt_at)

    def test_a_delivered_projection_is_never_retired(self):
        """Une ligne déjà écrite dans le classeur ne se retire pas.

        Prétendre l'annuler ici mentirait sur ce que le tableur contient.
        """
        _reference, shipment = self._creer_dossier()
        ligne = self._projection_en_vol(shipment)
        ligne.write({"state": "delivered"})

        retirees = self.env["dally.ops.sheet.outbox"].sudo().retire_projections(
            self.societe, ligne.ids, "AIR-X-A034")
        self.assertEqual(retirees, 0)
        self.assertEqual(ligne.state, "delivered")

    def test_a_retired_projection_of_another_company_is_refused(self):
        """Le retrait est borné à la société qui le demande."""
        autre = self.env["res.company"].create({"name": "Dally Retrait B"})
        _reference, shipment = self._creer_dossier()
        ligne = self._projection_en_vol(shipment)

        retirees = self.env["dally.ops.sheet.outbox"].sudo().retire_projections(
            autre, ligne.ids, "AIR-X-A034")
        self.assertEqual(retirees, 0)
        self.assertEqual(ligne.state, "pending")

    # ------------------------------------------------------------------
    # Le motif réservé, et ce qu'un connecteur ne peut pas en faire
    # ------------------------------------------------------------------

    def test_an_external_ack_cannot_forge_a_retired_marker(self):
        """Un vrai échec ne doit jamais devenir invisible.

        Le scénario : un connecteur autorisé mais défectueux accuse un échec
        permanent en réutilisant le motif interne. S'il pouvait l'écrire, la
        ligne sortirait des compteurs et de l'écran — un vrai incident
        deviendrait silencieux.

        `acknowledge` remplace donc le motif. L'échec reste enregistré, la
        ligne reste `failed`, et elle continue d'être comptée : c'est le point.
        """
        _reference, shipment = self._creer_dossier()
        ligne = self._projection_en_vol(shipment)
        avant = self._projection()["counts"]["failed"]

        self.env["dally.ops.sheet.outbox"].sudo().acknowledge(
            self.societe,
            [{"outbox_id": ligne.id, "ok": False, "permanent": True,
              "error": "intake_identity_retired:FAKE"}])
        self.env.invalidate_all()

        relue = self.env["dally.ops.sheet.outbox"].sudo().browse(ligne.id)
        self.assertEqual(relue.state, "failed")
        self.assertNotIn("intake_identity_retired", relue.last_error or "")
        # Et surtout : l'échec reste visible des deux côtés.
        self.assertEqual(self._projection()["counts"]["failed"], avant + 1)
        self.assertIn(
            "SHEET_PROJECTION_FAILED",
            {a["type"] for a in self._anomalies()["anomalies"]})

    def test_a_real_permanent_failure_is_still_counted(self):
        """Le contrat normal du transport ne change pas.

        Sans ce test, le précédent passerait aussi si `acknowledge` avait cessé
        d'enregistrer les échecs permanents.
        """
        _reference, shipment = self._creer_dossier()
        ligne = self._projection_en_vol(shipment)
        avant = self._projection()["counts"]["failed"]

        self.env["dally.ops.sheet.outbox"].sudo().acknowledge(
            self.societe,
            [{"outbox_id": ligne.id, "ok": False, "permanent": True,
              "error": "HTTP 500 upstream"}])

        self.assertEqual(ligne.state, "failed")
        self.assertEqual(ligne.last_error, "HTTP 500 upstream")
        self.assertEqual(self._projection()["counts"]["failed"], avant + 1)

    def test_a_real_failure_without_a_message_stays_visible(self):
        """Le piège NULL : `last_error` vide ne doit pas valoir « retiré ».

        En SQL, `NULL LIKE 'x%'` vaut NULL, et une négation mal formée fait
        disparaître la ligne du résultat. C'est précisément le vrai échec que
        ce correctif ne doit jamais masquer.
        """
        _reference, shipment = self._creer_dossier()
        ligne = self._projection_en_vol(shipment)
        avant = self._projection()["counts"]["failed"]

        ligne.write({"state": "failed", "last_error": False})

        self.assertEqual(self._projection()["counts"]["failed"], avant + 1)
        self.assertIn(
            "SHEET_PROJECTION_FAILED",
            {a["type"] for a in self._anomalies()["anomalies"]})

    def test_a_retry_is_information_not_an_alarm(self):
        """`retry` et `failed` ne sonnent pas pareil, et c'est délibéré."""
        _reference, shipment = self._creer_dossier()
        self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
        ligne = self.env["dally.ops.sheet.outbox"].sudo().search(
            [("company_id", "=", self.societe.id)], order="id desc", limit=1)
        ligne.write({"state": "retry"})

        signalee = next(a for a in self._anomalies()["anomalies"]
                        if a["type"] == "SHEET_PROJECTION_RETRY")
        self.assertEqual(signalee["severity"], "low")

    # ------------------------------------------------------------------
    # Ce qui ne descend jamais
    # ------------------------------------------------------------------

    def test_no_odoo_identifier_reaches_the_screen(self):
        """Vérifie le scénario « no odoo identifier reaches the screen »."""
        reference, _shipment, _facture = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())
        self._marquer_projection_en_echec()

        for anomalie in self._anomalies()["anomalies"]:
            for cle in anomalie:
                self.assertNotIn(
                    cle, CLES_INTERDITES,
                    "l'anomalie %s publie %s" % (anomalie["type"], cle))

    def test_the_projection_summary_carries_no_transport_error(self):
        """Vérifie le scénario « the projection summary carries no transport error »."""
        self._marquer_projection_en_echec()
        resume = self._projection()
        for cle in resume:
            self.assertNotIn(cle, CLES_INTERDITES)
        self.assertNotIn("last_error", resume)
        self.assertNotIn("projection.invalid", resume["operator_message"])

    def _marquer_projection_en_echec(self):
        """Force une projection synthétique en échec pour le scénario courant."""
        _reference, shipment = self._creer_dossier()
        self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
        ligne = self.env["dally.ops.sheet.outbox"].sudo().search(
            [("company_id", "=", self.societe.id)], order="id desc", limit=1)
        ligne.write({
            "state": "failed",
            "last_error": "HTTP 500 depuis projection.invalid/transport",
        })
        return ligne

    # ------------------------------------------------------------------
    # Les deux files ne se confondent pas
    # ------------------------------------------------------------------

    def test_the_summary_counts_only_the_odoo_queue(self):
        """Quatre compteurs, et aucun venu de l'appareil.

        La file d'IndexedDB n'a pas d'existence côté serveur : le résumé ne
        doit pas laisser croire qu'il la connaît.
        """
        resume = self._projection()
        self.assertEqual(
            set(resume["counts"]), {"pending", "retry", "failed", "synced"})
        self.assertEqual(set(resume), {"counts", "operator_message", "last_synced_at"})

    def test_a_delivered_projection_counts_as_synced(self):
        """Le vocabulaire du transport est traduit, pas relayé."""
        _reference, shipment = self._creer_dossier()
        self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
        ligne = self.env["dally.ops.sheet.outbox"].sudo().search(
            [("company_id", "=", self.societe.id)], order="id desc", limit=1)
        avant = self._projection()["counts"]["synced"]
        ligne.write({"state": "delivered"})
        self.assertEqual(self._projection()["counts"]["synced"], avant + 1)

    def test_another_company_queue_is_never_counted(self):
        """L'isolation vaut ici comme ailleurs."""
        autre = self.env["res.company"].create({"name": "Dally Supervision B"})
        # Le responsable doit pouvoir entrer dans la seconde société, sinon le
        # test mesurerait un refus d'accès et non l'isolation des compteurs.
        self.responsable.company_ids = [(4, autre.id)]
        _reference, shipment = self._creer_dossier()
        self.env["dally.ops.sheet.outbox"].enqueue_dossier(shipment)
        ligne = self.env["dally.ops.sheet.outbox"].sudo().search(
            [("company_id", "=", self.societe.id)], order="id desc", limit=1)
        ligne.write({"state": "failed"})

        vu_par_l_autre = (self.env["dally.ops.sheet.outbox"]
                          .with_user(self.responsable)
                          .with_company(autre).supervision_summary())
        self.assertEqual(vu_par_l_autre["counts"]["failed"], 0)

    # ------------------------------------------------------------------
    # L'ordre et le plafond
    # ------------------------------------------------------------------

    def test_the_gravest_comes_first(self):
        """Un responsable lit le haut de la liste, pas le milieu."""
        reference, _shipment, _facture = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())
        self._marquer_projection_en_echec()

        gravites = [a["severity"] for a in self._anomalies()["anomalies"]]
        self.assertEqual(gravites, sorted(gravites, key=["high", "medium", "low"].index))

    def test_a_recent_anomaly_is_not_lost_behind_older_dossiers(self):
        """La fenêtre d'examen part des dossiers les plus récents.

        Ce que ce test fige : une fenêtre bornée doit examiner les dossiers
        **récents**. Elle le fait aujourd'hui parce que le `_order` de
        `dally.shipment` est `create_date desc, id desc` ; le service le
        répète explicitement, et ce test protège les deux — si l'un ou l'autre
        change, l'écran se viderait sans rien dire de sa cause.

        La fenêtre est rétrécie le temps du test : en fabriquer trois cents
        coûterait des minutes pour prouver la même chose.
        """
        # Deux dossiers plus anciens, **eux aussi facturés** : sans facture
        # comptabilisée ils seraient écartés du balayage et ne disputeraient
        # pas la place, ce qui laisserait passer le défaut.
        self._dossier_facture()
        self._dossier_facture()
        # Puis le dossier qui, lui, porte un colis non couvert.
        reference, shipment, _facture = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())

        with patch.object(ops_anomaly_service, "FENETRE", 1):
            resultat = self._anomalies()

        signalees = [a["reference"] for a in resultat["anomalies"]
                     if a["type"] == "UNBILLED_PACKAGE"]
        self.assertIn(
            shipment.external_reference, signalees,
            "la fenêtre d'examen doit partir des dossiers les plus récents")

    def test_the_list_says_when_it_is_truncated(self):
        """Une liste tronquée doit le dire, sinon elle ment par omission."""
        resultat = self._anomalies()
        self.assertIn("truncated", resultat)
        self.assertEqual(resultat["truncated"], resultat["total"] > len(resultat["anomalies"]))

    def test_every_anomaly_carries_the_five_fields_the_screen_needs(self):
        """Vérifie le scénario « every anomaly carries the five fields the screen needs »."""
        reference, _shipment, _facture = self._dossier_facture()
        self._service_ligne().add_late_line(reference, self._ligne_tardive())
        self._marquer_projection_en_echec()

        attendus = {"type", "reference", "title", "operator_message", "severity",
                    "action", "intake_reference"}
        for anomalie in self._anomalies()["anomalies"]:
            self.assertEqual(set(anomalie), attendus)
            self.assertTrue(anomalie["operator_message"])
            self.assertIn(anomalie["severity"], ("high", "medium", "low"))


# `uuid` est importé pour les fabriques héritées ; le référencer ici évite
# qu'un nettoyage d'import le retire et casse `_ligne_tardive`.
assert uuid is not None
