# -*- coding: utf-8 -*-
"""Ce qui, aujourd'hui, demande une décision humaine.

## Pourquoi un écran, et pas six

Six choses peuvent clocher sur un dossier, et chacune se voyait jusqu'ici
depuis un endroit différent — ou ne se voyait pas du tout. Une projection en
échec ne se lisait que dans Odoo ; un colis arrivé après la facture ne se
signalait nulle part ; un paiement à revérifier attendait qu'on rouvre la
fiche. Le responsable balayait les dossiers un par un.

Ce service rassemble les six en une liste, calculée **côté serveur, depuis
Odoo**. Jamais depuis le tableur : le classeur est une projection, et faire
d'une projection la source d'une alerte reviendrait à s'alarmer d'un reflet.

## Ce qui ne descend jamais

Aucun identifiant Odoo. Une anomalie se désigne par la référence métier du
dossier ou du départ, jamais par une clé primaire — publier un `id` inviterait
l'écran à raisonner dessus, puis à le renvoyer.

Aucun `last_error` non plus. Le message d'erreur d'un transport est écrit pour
un journal : il peut porter une URL, une trace, un identifiant de connexion.
L'opérateur reçoit une phrase rédigée pour lui, choisie parmi un vocabulaire
fermé.

## Qui voit cette liste

Un responsable. C'est une vue de supervision : elle traverse tous les dossiers
de la société, y compris ceux qu'un logisticien n'a pas ouverts. Le refus est
prononcé ici, côté serveur — l'écran le respecte aussi, mais un écran n'est
pas une protection.
"""
from odoo import _, api, models
from odoo.exceptions import AccessError

#: Les six natures d'anomalie, et rien d'autre. Un type inventé côté écran
#: n'aurait ni message ni gravité : le vocabulaire est fermé des deux côtés.
TYPES = (
    "SHEET_PROJECTION_FAILED",
    "SHEET_PROJECTION_RETRY",
    "UNBILLED_PACKAGE",
    "MISSING_TARIFF",
    "PAYMENT_REVIEW_REQUIRED",
    "INCOMPLETE_BEFORE_DEPARTURE",
)

#: La gravité, dite en trois mots plutôt qu'en couleurs : un écran choisit sa
#: couleur, un serveur dit l'urgence.
GRAVITE = {
    "SHEET_PROJECTION_FAILED": "high",
    "SHEET_PROJECTION_RETRY": "low",
    "UNBILLED_PACKAGE": "medium",
    "MISSING_TARIFF": "high",
    "PAYMENT_REVIEW_REQUIRED": "high",
    "INCOMPLETE_BEFORE_DEPARTURE": "medium",
}

#: L'ordre d'affichage : ce qui bloque un départ ou fausse une facture d'abord.
ORDRE = {"high": 0, "medium": 1, "low": 2}

#: Le plafond d'affichage. Une liste sans borne finirait par transporter la base
#: entière le jour d'une panne de projection, et l'écran deviendrait illisible au
#: moment précis où il sert.
PLAFOND = 50

#: La fenêtre d'examen : les N dossiers les plus récents.
#:
#: Elle existe parce qu'une base porte des milliers de dossiers et que les
#: parcourir tous à chaque ouverture d'écran coûterait cher pour ne rien
#: apprendre — un dossier clos depuis six mois ne demande plus de décision.
#:
#: L'ordre est nommé explicitement plutôt que laissé au `_order` du modèle.
#: Celui de `dally.shipment` est bien `create_date desc, id desc`, donc déjà
#: le bon ; mais une fenêtre bornée dont l'ordre dépend d'un défaut hérité
#: cesserait d'être juste le jour où ce défaut change, et le symptôme serait
#: un écran vide — le plus difficile à relier à sa cause.
FENETRE = 300


class DallyOpsAnomalyService(models.AbstractModel):
    """Le service de lecture de l'écran « À traiter ».

    Abstrait : il ne stocke rien. Il interroge la facturation, l'outbox et les
    départs, et traduit leurs états en une liste d'anomalies. Aucune méthode
    n'écrit — un écran de supervision constate, il ne corrige pas.
    """

    _name = "dally.ops.anomaly.service"
    _description = "DallyTrading Ops — ce qui demande une décision"

    # ------------------------------------------------------------------

    @api.model
    def list_anomalies(self):
        """Les anomalies ouvertes de la société courante, les plus graves d'abord.

        Lecture seule : rien n'est écrit, rien n'est relancé. L'écran affiche,
        l'opérateur va voir.
        """
        self._exiger_supervision()
        anomalies = (
            self._projections_en_peine()
            + self._colis_non_factures()
            + self._tarifs_manquants()
            + self._paiements_a_verifier()
            + self._departs_incomplets()
        )
        anomalies.sort(key=lambda item: (ORDRE[item["severity"]], item["reference"]))
        return {
            "anomalies": anomalies[:PLAFOND],
            "total": len(anomalies),
            "truncated": len(anomalies) > PLAFOND,
        }

    # ------------------------------------------------------------------
    # Le droit d'en connaître
    # ------------------------------------------------------------------

    @api.model
    def _exiger_supervision(self):
        """Une vue qui traverse tous les dossiers appartient au responsable.

        Le refus est prononcé côté serveur. L'écran cache aussi l'entrée, mais
        cacher n'est pas protéger : une requête forgée arriverait ici quand
        même.
        """
        if not self.env.user._dally_ops_capabilities().get("supervise"):
            raise AccessError(_("Accès réservé au responsable."))

    # ------------------------------------------------------------------
    # Les six familles
    # ------------------------------------------------------------------

    @api.model
    def _projections_en_peine(self):
        """Le tableur n'a pas reçu ce qu'Odoo lui a envoyé.

        `failed` est un abandon : le transport a renoncé, personne ne
        réessaiera sans geste humain. `retry` est une attente : c'est une
        information, pas une alarme — d'où deux types et deux gravités, plutôt
        qu'un seul qui ferait sonner l'un comme l'autre.
        """
        # Une projection retirée volontairement n'est pas une panne : elle est
        # écartée par le domaine du modèle, jamais par une règle réécrite ici.
        # Deux formulations de la même exclusion divergeraient, et l'écran
        # cesserait alors de dire la même chose que les compteurs.
        Boite = self.env["dally.ops.sheet.outbox"]
        lignes = Boite.sudo().search(
            [
                ("company_id", "=", self.env.company.id),
                ("state", "in", ("failed", "retry")),
            ] + Boite._domaine_hors_identite_retiree(),
            order="id desc", limit=FENETRE)
        return [
            self._anomalie(
                "SHEET_PROJECTION_FAILED" if ligne.state == "failed"
                else "SHEET_PROJECTION_RETRY",
                ligne.resource_reference or ligne.business_key,
                _("Synchronisation du tableur"),
                _("Le tableur n'a pas reçu ce dossier. Prévenez le "
                  "responsable de la synchronisation.")
                if ligne.state == "failed" else
                _("Envoi au tableur en attente d'une nouvelle tentative."),
                # Rien à ouvrir : la projection se rejoue par le connecteur,
                # pas depuis un dossier.
                None,
            )
            for ligne in lignes
        ]

    @api.model
    def _colis_non_factures(self):
        """De la marchandise réelle qu'aucune pièce ne couvre encore."""
        dossiers = self._dossiers_factures()
        colis = dossiers.mapped("package_ids")
        if not colis:
            return []

        # La couverture se lit sur `sale.order.line` — seule source de vérité,
        # parce qu'un complément ne se rattache pas à `invoice_id`. Une requête
        # pour toute la fenêtre, plutôt qu'une par dossier.
        lignes = self.env["sale.order.line"].sudo().search([
            ("dally_freight_package_id", "in", colis.ids),
            ("state", "!=", "cancel"),
        ])
        couverts = set(lignes.mapped("dally_freight_package_id").ids)

        anomalies = []
        for dossier in dossiers:
            en_attente = [c for c in dossier.package_ids if c.id not in couverts]
            if not en_attente:
                continue
            anomalies.append(self._anomalie(
                "UNBILLED_PACKAGE",
                dossier.external_reference,
                _("Article non facturé"),
                _("%(nombre)s article(s) de ce dossier ne sont couverts par "
                  "aucune facture.", nombre=len(en_attente)),
                dossier.external_reference,
            ))
        return anomalies

    @api.model
    def _tarifs_manquants(self):
        """Un colis qu'aucune règle ne sait chiffrer.

        Le prix se déduit du service de ligne, qui porte déjà la règle. La
        recopier ici en ferait une seconde version, qui divergerait.
        """
        Ligne = self.env["dally.ops.intake.line.service"]
        par_dossier = {}
        for colis in self._dossiers_ops().mapped("package_ids"):
            if Ligne._statut_pricing(colis) == "manual_required":
                par_dossier.setdefault(colis.shipment_id, []).append(colis)

        return [
            self._anomalie(
                "MISSING_TARIFF",
                dossier.external_reference,
                _("Tarif à valider"),
                _("%(nombre)s article(s) attendent un prix. La facture ne "
                  "peut pas être émise sans lui.", nombre=len(manquants)),
                dossier.external_reference,
            )
            for dossier, manquants in par_dossier.items()
        ]

    @api.model
    def _paiements_a_verifier(self):
        """Un encaissement que la comptabilité n'a pas su enregistrer.

        Le filtre sur le dossier passe par le domaine Ops, comme partout
        ailleurs : un encaissement en erreur sur un dossier venu d'un autre
        canal produirait un lien que la fiche refuserait d'ouvrir.
        """
        collections = self.env["dally.freight.collection"].sudo().search(
            [("company_id", "=", self.env.company.id),
             ("state", "=", "error"),
             ("shipment_id", "in", self._dossiers_ops().ids)],
            order="id desc", limit=FENETRE)
        return [
            self._anomalie(
                "PAYMENT_REVIEW_REQUIRED",
                collection.shipment_id.external_reference,
                _("Paiement à vérifier"),
                _("Un encaissement de ce dossier n'a pas pu être "
                  "comptabilisé."),
                collection.shipment_id.external_reference,
            )
            for collection in collections
        ]

    @api.model
    def _departs_incomplets(self):
        """Un dossier chargé sur un départ qui n'est pas prêt à partir.

        `ready_for_departure` appartient à Freight et sait déjà tout ce qui
        bloque — paiement, complétude, dérogation. Ops le lit, il ne le
        recalcule pas.
        """
        dossiers = self.env["dally.shipment"].sudo().search(
            self._domaine([
                ("consolidation_id", "!=", False),
                ("consolidation_state", "in", ("closed", "in_transit")),
                ("ready_for_departure", "=", False),
            ]), order="id desc", limit=FENETRE)
        return [
            self._anomalie(
                "INCOMPLETE_BEFORE_DEPARTURE",
                dossier.external_reference,
                _("Dossier incomplet avant départ"),
                _("Ce dossier est rattaché à un départ fermé mais n'est pas "
                  "prêt à partir."),
                dossier.external_reference,
            )
            for dossier in dossiers
        ]

    # ------------------------------------------------------------------
    # Le décor
    # ------------------------------------------------------------------

    @api.model
    def _anomalie(self, type_anomalie, reference, titre, message, dossier):
        """Une anomalie, réduite à ce qu'un opérateur doit lire pour agir.

        `action` vaut `open_intake` seulement quand il y a une fiche à ouvrir.
        Une projection en peine n'en a pas : proposer d'ouvrir un dossier pour
        un incident de transport enverrait l'opérateur au mauvais endroit.
        """
        return {
            "type": type_anomalie,
            "reference": reference,
            "title": titre,
            "operator_message": message,
            "severity": GRAVITE[type_anomalie],
            "action": "open_intake" if dossier else None,
            "intake_reference": dossier,
        }

    @api.model
    def _domaine(self, extra=()):
        """Le domaine des dossiers qu'une anomalie a le droit de désigner.

        Il vient du service de ligne, qui porte déjà la définition d'un dossier
        Ops : société, `sync_source = backoffice`, `sync_source_key` en
        `ops:%`, consolidation d'entrée. La recopier ici en ferait une seconde
        version, plus large, qui divergerait.

        Ce n'est pas un détail de forme. Une anomalie annonce `open_intake`
        avec une référence, et la fiche résout cette référence **avec ce
        domaine-là**. Chercher plus large ferait donc afficher un lien que la
        fiche refuserait d'ouvrir — l'écran promettrait un dossier
        introuvable.
        """
        return (self.env["dally.ops.intake.line.service"]._domaine_dossier_ops()
                + [("external_reference", "!=", False)] + list(extra))

    @api.model
    def _dossiers_ops(self):
        """Les dossiers nés de Dally Ops, dans la société courante."""
        return self.env["dally.shipment"].sudo().search(
            self._domaine(), order="id desc", limit=FENETRE)

    @api.model
    def _dossiers_factures(self):
        """Ceux d'entre eux qui portent déjà une pièce comptabilisée.

        Un dossier sans facture n'a pas de colis « non facturé » : il n'a
        simplement pas encore été facturé. Confondre les deux ferait sonner
        chaque saisie en cours.
        """
        return self.env["dally.shipment"].sudo().search(
            self._domaine([("invoice_id.state", "=", "posted")]),
            order="id desc", limit=FENETRE)
