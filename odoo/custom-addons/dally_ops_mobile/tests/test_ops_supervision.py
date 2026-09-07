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

from odoo.exceptions import AccessError
from odoo.tests import tagged

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
