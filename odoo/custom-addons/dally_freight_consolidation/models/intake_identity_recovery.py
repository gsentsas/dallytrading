# -*- coding: utf-8 -*-
"""Retirer l'identité de collecte d'une entrée annulée, et rien d'autre.

## Le problème

Une collecte saisie depuis Ops réserve trois identités uniques dans sa
consolidation d'entrée : ``collection_sequence``, ``collection_local_ref`` et
``external_reference``. Annuler le dossier ne les rend pas : les contraintes
``dally_shipment_intake_sequence_unique`` et
``dally_shipment_external_reference_unique`` sont des ``UNIQUE`` pleines, sans
clause partielle sur ``active``, et le connecteur cherche de toute façon en
``active_test=False``. Archiver ne libère donc rien.

Quand la référence papier ``A034`` est ensuite attribuée à un autre client,
le classeur ne peut plus la synchroniser : ``freight_sync`` retrouve le dossier
annulé par ``external_reference`` et refuse — « La clé source appartient déjà à
un autre dossier ».

## Ce que fait cette réparation

Elle déplace l'identité de collecte du dossier **annulé** vers une plage
d'archive, et laisse tout le reste intact : le dossier, ses colis, ses photos,
son audit, ses événements, sa clé source. Rien n'est supprimé, rien n'est
recyclé vers le nouveau client, aucune ligne d'historique ne disparaît.

## Ce qu'elle ne fait pas

Elle ne touche jamais à ``sync_source_key`` : c'est l'identité d'origine du
dossier, la seule chose qui dise d'où il vient. La réécrire rendrait le dossier
annulé indiscernable d'un dossier créé par le classeur.

Elle ne touche jamais à ``intake_consolidation_id`` : le dossier reste dans la
consolidation où la marchandise a réellement été reçue. Le modèle refuse de
toute façon ce changement, sans échappatoire.

Elle refuse tout dossier portant de l'argent — devis, facture, encaissement,
paiement. Déplacer l'identité d'un dossier facturé désolidariserait la pièce
comptable de sa référence, et c'est exactement ce qu'aucune maintenance ne doit
pouvoir faire.

## Pourquoi un service, et pas du SQL

Les identifiants de collecte sont immuables par l'ORM : ``dally.shipment.write``
lève ``AccessError`` sans le jeton privé du module. Contourner l'ORM en SQL
sauterait aussi la cohérence ``sequence``/``local_ref``, le chatter et l'audit.
Ce service passe par le jeton — le même chemin que l'allocation initiale — et
laisse une trace lisible dans le chatter du dossier.
"""

import logging

import psycopg2

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

from .shipment import _INTAKE_IDENTITY_TOKEN, _PLANNED_RETIRE_TOKEN

_logger = logging.getLogger(__name__)

#: La précision des poids et volumes chargés, telle que la base les stocke.
#:
#: Comparer des flottants à l'identité binaire ferait échouer la maintenance
#: sur un chiffre de représentation, jamais sur un écart réel. On compare donc
#: à la précision métier — celle qui figure sur le manifeste.
PRECISION_CHARGEMENT = 3

#: Les champs qu'une attente doit porter pour qu'un retrait soit possible.
#:
#: Une attente partielle rendrait le service « adaptatif » : les champs qu'elle
#: ne déclare pas ne sont jamais confrontés, et la maintenance appliquerait
#: alors ce qu'elle trouve. Rendre la méthode privée empêche l'appel fortuit ;
#: ce schéma empêche l'appel volontaire mais négligent — le plus dangereux des
#: deux, parce qu'il a l'air informé.
CHAMPS_ATTENDUS = (
    "company_id", "partner_id",
    "intake_consolidation_id", "planned_consolidation_id",
    "external_reference", "collection_local_ref", "collection_sequence",
    "sync_source", "sync_source_key",
    "loaded_lines", "outbox",
)

#: Une liste vide est une affirmation — « ce dossier ne porte aucun
#: chargement » —, une clé absente n'en est pas une. Les deux ne doivent jamais
#: se confondre, d'où l'exigence de la clé et non d'un contenu.
CHAMPS_LIGNE_ATTENDUE = ("line_id", "package_id", "quantity_loaded", "weight_loaded")
CHAMPS_OUTBOX_ATTENDUE = (
    "outbox_id", "projection_type", "business_key", "state", "resource_reference")

#: Le décalage qui place une identité d'archive hors d'atteinte.
#:
#: Une consolidation alloue ses numéros à partir de 1, un par colis reçu. Un
#: départ dépasse rarement la centaine et n'atteindra jamais 900 000 : la plage
#: d'archive ne peut donc pas entrer en collision avec une allocation future.
#: Le numéro reste malgré tout dérivé de l'``id`` du dossier, ce qui rend
#: l'archive unique par construction et traçable à l'œil nu.
ARCHIVE_SEQUENCE_OFFSET = 900000

#: La marge exigée entre la plage d'archive et le prochain numéro que la
#: consolidation distribuerait. Vérifiée, jamais supposée.
ARCHIVE_SEQUENCE_MIN_MARGIN = 1000


def _local_ref(sequence):
    """La forme canonique du modèle : ``A001`` en dessous de 1000, ``A%d`` au-delà.

    Dupliquer la règle serait une invitation à la voir diverger ; elle est
    reprise telle quelle de ``_allocate_intake_identity``, qui est l'autorité.
    """
    return ("A%03d" % sequence) if sequence < 1000 else ("A%d" % sequence)


class DallyFreightIntakeIdentityRecovery(models.AbstractModel):
    """Simulation puis application du retrait d'une identité de collecte annulée."""

    _name = "dally.freight.intake.identity.recovery"
    _description = "Retrait d'identité de collecte annulée"

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    @api.model
    def simulate(self, shipment_ids, expected=None):
        """Rend le rapport complet sans écrire une seule ligne.

        ``expected`` porte, par dossier, ce que l'opérateur croit vrai. Chaque
        clé y est comparée à la base : une seule divergence suffit à refuser.
        Sans cette confrontation, la maintenance appliquerait ce qu'elle
        trouve — et une réparation qui s'adapte à ce qu'elle trouve n'est plus
        une réparation, c'est une écriture aveugle.
        """
        expected = expected or {}
        rapport = {
            "database": self.env.cr.dbname,
            "company_id": self.env.company.id,
            "shipments": [],
            "blocking": [],
        }
        for shipment_id in shipment_ids:
            detail = self._inspect(int(shipment_id), expected.get(int(shipment_id)) or {})
            rapport["shipments"].append(detail)
            rapport["blocking"].extend(
                "%s: %s" % (shipment_id, echec) for echec in detail["failed_assertions"]
            )
        rapport["dry_run_pass"] = not rapport["blocking"]
        return rapport

    @api.model
    def _inspect(self, shipment_id, expected):
        """Toutes les assertions d'un dossier, collectées et non interrompues.

        On ne s'arrête pas à la première : un opérateur qui corrige une
        divergence à la fois relancerait la simulation dix fois. Le rapport
        doit dire tout ce qui cloche, d'un coup.
        """
        Shipment = self.env["dally.shipment"].with_context(active_test=False)
        shipment = Shipment.browse(shipment_id).exists()
        echecs = []

        def exiger(condition, message):
            if not condition:
                echecs.append(message)

        exiger(bool(shipment), _("Dossier %s introuvable.", shipment_id))
        if not shipment:
            return {
                "shipment_id": shipment_id, "failed_assertions": echecs,
                "archive": {}, "outbox": [], "consolidation_lines": [],
            }

        consolidation = shipment.intake_consolidation_id

        if "company_id" in expected:
            exiger(shipment.company_id.id == expected["company_id"],
                   _("Société %s attendue, %s en base.", expected["company_id"], shipment.company_id.id))
        if "intake_consolidation_id" in expected:
            exiger(consolidation.id == expected["intake_consolidation_id"],
                   _("Consolidation d'entrée %s attendue, %s en base.",
                     expected["intake_consolidation_id"], consolidation.id))
        for champ in ("external_reference", "collection_local_ref", "sync_source_key"):
            if champ in expected:
                exiger(shipment[champ] == expected[champ],
                       _("%s attendu « %s », « %s » en base.", champ, expected[champ], shipment[champ]))
        if "collection_sequence" in expected:
            exiger(shipment.collection_sequence == expected["collection_sequence"],
                   _("collection_sequence %s attendu, %s en base.",
                     expected["collection_sequence"], shipment.collection_sequence))
        if "planned_consolidation_id" in expected:
            exiger(shipment.planned_consolidation_id.id == expected["planned_consolidation_id"],
                   _("Départ prévu %s attendu, %s en base.",
                     expected["planned_consolidation_id"], shipment.planned_consolidation_id.id))
        if "loaded_line_ids" in expected:
            reelles = sorted(ligne.id for ligne in shipment.consolidation_line_ids)
            exiger(reelles == sorted(expected["loaded_line_ids"]),
                   _("Lignes de chargement %s attendues, %s en base.",
                     sorted(expected["loaded_line_ids"]), reelles))
        if "partner_id" in expected:
            exiger(shipment.partner_id.id == expected["partner_id"],
                   _("Client %s attendu, %s en base.",
                     expected["partner_id"], shipment.partner_id.id))
        if "sync_source" in expected:
            exiger(shipment.sync_source == expected["sync_source"],
                   _("sync_source « %s » attendu, « %s » en base.",
                     expected["sync_source"], shipment.sync_source))

        # Les invariants qui ne se négocient pas, quelle que soit l'attente
        # déclarée par l'opérateur.
        exiger(shipment.state == "cancelled",
               _("Le dossier doit être annulé (état actuel : %s).", shipment.state))
        exiger(bool(consolidation),
               _("Le dossier ne porte aucune consolidation d'entrée : il n'a pas d'identité à retirer."))
        exiger(bool(shipment.collection_sequence) and bool(shipment.collection_local_ref),
               _("Le dossier ne porte pas d'identité de collecte complète."))
        exiger(not shipment.sale_order_id, _("Un devis est rattaché (%s).", shipment.sale_order_id.id))
        exiger(not shipment.invoice_id, _("Une facture est rattachée (%s).", shipment.invoice_id.id))
        exiger(not shipment.billing_locked, _("La facturation est verrouillée."))

        collections = self.env["dally.freight.collection"].sudo().search(
            [("shipment_id", "=", shipment.id)])
        exiger(not collections,
               _("%s encaissement(s) rattaché(s).", len(collections)))
        exiger(not collections.mapped("payment_id"),
               _("Des paiements comptables sont rattachés aux encaissements."))

        # Un lien financier peut exister sans passer par `invoice_id` : une
        # facture peut pointer le dossier sans que le dossier pointe la
        # facture. Chercher dans les deux sens, sinon la garantie « aucune
        # finance » ne vaut que dans un sens.
        Move = self.env["account.move"].sudo().with_context(active_test=False)
        factures_liees = Move.browse()
        if "dally_freight_shipment_id" in Move._fields:
            factures_liees = Move.search([("dally_freight_shipment_id", "=", shipment.id)])
        exiger(not factures_liees,
               _("%s pièce(s) comptable(s) pointent ce dossier.", len(factures_liees)))
        Order = self.env["sale.order"].sudo()
        commandes_liees = Order.browse()
        if "dally_freight_shipment_id" in Order._fields:
            commandes_liees = Order.search([("dally_freight_shipment_id", "=", shipment.id)])
        exiger(not commandes_liees,
               _("%s devis pointent ce dossier.", len(commandes_liees)))

        lignes = [
            {
                "line_id": ligne.id,
                "consolidation_id": ligne.consolidation_id.id,
                "consolidation_name": ligne.consolidation_id.name,
                "consolidation_state": ligne.consolidation_id.state,
                "package_id": ligne.package_id.id,
                "package_shipment_id": ligne.package_id.shipment_id.id,
                "description": ligne.package_id.description,
                "quantity_loaded": ligne.quantity_loaded,
                "weight_loaded": ligne.weight_loaded,
                "volume_loaded": ligne.volume_loaded,
            }
            for ligne in shipment.consolidation_line_ids
        ]
        # Un colis reçu depuis Ops est chargé dans sa consolidation au moment
        # même de la saisie, et annuler le dossier ne le décharge pas. Une
        # quantité chargée est donc l'état NORMAL d'une entrée annulée, pas le
        # signe d'un enchevêtrement : le retrait ne touche ni `package_id` ni
        # `quantity_loaded`, seulement les trois champs d'identité. Refuser
        # là-dessus bloquerait tous les cas réels sans rien protéger — mesuré
        # sur 842 et 843, tous deux chargés dans une consolidation ouverte.
        #
        # Ce qui doit bloquer, c'est une consolidation qui n'est plus en
        # collecte : son manifeste est imprimé, et il porterait alors une
        # référence que la base ne revendique plus.
        exiger(all(ligne["consolidation_state"] == "collecting" for ligne in lignes),
               _("Le dossier est rattaché à une consolidation qui n'est plus en collecte."))

        # Chaque ligne doit appartenir au dossier ciblé. `line.shipment_id` est
        # la relation autoritaire, mais on revérifie par le colis : une ligne
        # dont le colis appartient à un autre dossier serait une incohérence
        # préexistante, et la maintenance ne doit pas la retirer au passage.
        etrangeres = [
            ligne["line_id"] for ligne in lignes
            if ligne["package_shipment_id"] != shipment.id
        ]
        exiger(not etrangeres,
               _("Les lignes %s portent des colis d'un autre dossier.", etrangeres))

        planifie = shipment.planned_consolidation_id
        exiger(planifie.state != "departed" if planifie else True,
               _("Le départ prévu est déjà parti."))
        exiger(planifie.state == "collecting" if planifie else True,
               _("Le départ prévu n'est plus en collecte (état : %s).",
                 planifie.state if planifie else ""))

        boite = self.env["dally.ops.sheet.outbox"].sudo().search([
            ("resource_model", "=", "dally.shipment"), ("resource_id", "=", shipment.id),
        ]) if "dally.ops.sheet.outbox" in self.env else self.env["dally.shipment"].browse()
        outbox = [
            {
                "outbox_id": ligne.id, "state": ligne.state,
                "projection_type": ligne.projection_type,
                "business_key": ligne.business_key,
                "resource_reference": ligne.resource_reference,
            }
            for ligne in boite
        ]

        self._exiger_empreinte_lignes(expected, lignes, exiger)
        self._exiger_empreinte_outbox(expected, outbox, exiger)

        archive = self._archive_identity(shipment, consolidation, echecs)

        return {
            "shipment_id": shipment.id,
            "reference": shipment.reference,
            "client": shipment.partner_id.display_name,
            "state": shipment.state,
            "current_identity": {
                "external_reference": shipment.external_reference,
                "collection_local_ref": shipment.collection_local_ref,
                "collection_sequence": shipment.collection_sequence,
                "sync_source_key": shipment.sync_source_key,
                "sync_source": shipment.sync_source,
                "intake_consolidation": consolidation.name,
            },
            # Ce qui doit survivre intact, capturé pour être revérifié après
            # écriture. Une postcondition qui se compare à elle-même ne prouve
            # rien : elle doit se comparer à l'avant.
            "current_identity_intake_id": consolidation.id,
            "package_count_before": len(shipment.package_ids),
            "archive": archive,
            "consolidation_lines": lignes,
            # Ce que l'APPLY retirera du départ vivant, énuméré avant toute
            # mutation : sans cette liste, personne ne pourrait vérifier après
            # coup que seuls les faux colis ont quitté le manifeste.
            "loaded_lines_to_remove": [ligne["line_id"] for ligne in lignes],
            "loaded_quantity_total": sum(ligne["quantity_loaded"] for ligne in lignes),
            "loaded_weight_total": sum(ligne["weight_loaded"] for ligne in lignes),
            "loaded_volume_total": sum(ligne["volume_loaded"] for ligne in lignes),
            "planned_consolidation_to_clear": {
                "id": planifie.id,
                "name": planifie.name,
                "state": planifie.state,
            } if planifie else {},
            "outbox": outbox,
            "failed_assertions": echecs,
        }

    @api.model
    def _exiger_empreinte_lignes(self, expected, lignes, exiger):
        """Compare le chargement ligne à ligne, pas seulement par identifiant.

        Des identifiants identiques ne disent pas que le chargement est le
        même : un colis peut avoir été réaffecté, une quantité corrigée, un
        poids repesé. Ce sont précisément les valeurs qui décideront de ce qui
        quitte le manifeste, donc celles qu'il faut confronter.
        """
        if "loaded_lines" not in expected:
            return
        attendues = {int(ligne["line_id"]): ligne for ligne in expected["loaded_lines"]}
        reelles = {ligne["line_id"]: ligne for ligne in lignes}
        if set(attendues) != set(reelles):
            exiger(False, _(
                "Lignes de chargement %(attendu)s attendues, %(reel)s en base.",
                attendu=sorted(attendues), reel=sorted(reelles)))
            return
        for line_id, attendue in sorted(attendues.items()):
            reelle = reelles[line_id]
            if attendue.get("package_id") is not None:
                exiger(reelle["package_id"] == int(attendue["package_id"]), _(
                    "Ligne %(id)s : colis %(attendu)s attendu, %(reel)s en base.",
                    id=line_id, attendu=attendue["package_id"], reel=reelle["package_id"]))
            if attendue.get("quantity_loaded") is not None:
                exiger(reelle["quantity_loaded"] == attendue["quantity_loaded"], _(
                    "Ligne %(id)s : quantité %(attendu)s attendue, %(reel)s en base.",
                    id=line_id, attendu=attendue["quantity_loaded"],
                    reel=reelle["quantity_loaded"]))
            if attendue.get("weight_loaded") is not None:
                exiger(float_compare(
                    reelle["weight_loaded"], float(attendue["weight_loaded"]),
                    precision_digits=PRECISION_CHARGEMENT) == 0, _(
                    "Ligne %(id)s : poids %(attendu)s attendu, %(reel)s en base.",
                    id=line_id, attendu=attendue["weight_loaded"],
                    reel=reelle["weight_loaded"]))

    @api.model
    def _exiger_empreinte_outbox(self, expected, outbox, exiger):
        """Confronte la file de projection à ce que l'audit y avait vu.

        L'état d'une ligne d'outbox bouge tout seul : un transport peut la
        passer en `processing` entre l'audit et la réparation. Terminaliser une
        ligne qu'un autre a déjà prise en charge, c'est écraser un verdict qui
        ne nous appartient pas.
        """
        if "outbox" not in expected:
            return
        attendues = {int(ligne["outbox_id"]): ligne for ligne in expected["outbox"]}
        reelles = {ligne["outbox_id"]: ligne for ligne in outbox}
        if set(attendues) != set(reelles):
            exiger(False, _(
                "Projections %(attendu)s attendues, %(reel)s en base.",
                attendu=sorted(attendues), reel=sorted(reelles)))
            return
        for outbox_id, attendue in sorted(attendues.items()):
            reelle = reelles[outbox_id]
            for champ in ("projection_type", "business_key", "state", "resource_reference"):
                if attendue.get(champ) is None:
                    continue
                exiger(reelle[champ] == attendue[champ], _(
                    "Projection %(id)s : %(champ)s « %(attendu)s » attendu, "
                    "« %(reel)s » en base.",
                    id=outbox_id, champ=champ,
                    attendu=attendue[champ], reel=reelle[champ]))

    @api.model
    def _archive_identity(self, shipment, consolidation, echecs):
        """Calcule l'identité d'archive et prouve qu'elle est libre.

        Le calcul est déterministe — dérivé de l'``id`` — pour qu'une
        simulation et son application des heures plus tard visent exactement la
        même cible. Rien n'est choisi au moment d'écrire.
        """
        if not consolidation:
            return {}
        sequence = ARCHIVE_SEQUENCE_OFFSET + shipment.id
        local = _local_ref(sequence)
        externe = "%s-%s" % (consolidation.name, local)
        Shipment = self.env["dally.shipment"].with_context(active_test=False)
        base = [("company_id", "=", shipment.company_id.id)]

        sequence_prise = Shipment.search_count(base + [
            ("intake_consolidation_id", "=", consolidation.id),
            ("collection_sequence", "=", sequence),
        ])
        local_pris = Shipment.search_count(base + [
            ("intake_consolidation_id", "=", consolidation.id),
            ("collection_local_ref", "=", local),
        ])
        externe_pris = Shipment.search_count(base + [("external_reference", "=", externe)])

        if sequence_prise:
            echecs.append(_("Le numéro d'archive %s est déjà pris.", sequence))
        if local_pris:
            echecs.append(_("La référence locale d'archive %s est déjà prise.", local))
        if externe_pris:
            echecs.append(_("La référence globale d'archive %s est déjà prise.", externe))

        # La plage d'archive doit rester hors d'atteinte de la séquence de la
        # consolidation. On lit le compteur plutôt que de faire confiance à
        # l'ordre de grandeur : une consolidation dont la séquence aurait été
        # réinitialisée haut invaliderait tout le raisonnement.
        prochain = 0
        sequence_record = consolidation.intake_sequence_id
        if sequence_record:
            prochain = sequence_record.sudo().number_next_actual or 0
        if prochain and sequence - prochain < ARCHIVE_SEQUENCE_MIN_MARGIN:
            echecs.append(_(
                "La plage d'archive (%s) est trop proche du prochain numéro de collecte (%s).",
                sequence, prochain))

        return {
            "collection_sequence": sequence,
            "collection_local_ref": local,
            "external_reference": externe,
            "sequence_free": not sequence_prise,
            "local_ref_free": not local_pris,
            "external_reference_free": not externe_pris,
            "next_intake_sequence": prochain,
        }

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    @api.model
    def _valider_schema_attentes(self, shipment_ids, expected):
        """Refuse une attente incomplète, avant tout verrou et toute mutation.

        Vérifier la seule présence d'une entrée par dossier ne suffit pas : une
        attente réduite à un champ laisserait tous les autres hors contrôle, et
        le service redeviendrait capable de s'adapter à ce qu'il trouve. Le
        schéma est donc exigé en entier, jusqu'au détail de chaque ligne de
        chargement et de chaque projection.

        La clé est exigée, jamais une valeur : un dossier peut légitimement
        n'avoir aucun départ prévu, aucun chargement ou aucune projection.
        Déclarer une liste vide est une affirmation ; omettre la clé n'en est
        pas une, et c'est cette différence que le schéma protège.
        """
        expected = expected or {}
        griefs = []
        for identifiant in shipment_ids:
            attente = expected.get(int(identifiant))
            if not isinstance(attente, dict) or not attente:
                griefs.append(_("dossier %s : aucune attente déclarée", identifiant))
                continue
            absents = [champ for champ in CHAMPS_ATTENDUS if champ not in attente]
            if absents:
                griefs.append(_(
                    "dossier %(id)s : champ(s) obligatoire(s) absent(s) — %(champs)s",
                    id=identifiant, champs=", ".join(absents)))
            for rang, ligne in enumerate(attente.get("loaded_lines") or [], start=1):
                if not isinstance(ligne, dict):
                    griefs.append(_(
                        "dossier %(id)s : ligne de chargement %(rang)s invalide",
                        id=identifiant, rang=rang))
                    continue
                creux = [champ for champ in CHAMPS_LIGNE_ATTENDUE if champ not in ligne]
                if creux:
                    griefs.append(_(
                        "dossier %(id)s : ligne %(rang)s incomplète — %(champs)s",
                        id=identifiant, rang=rang, champs=", ".join(creux)))
            for rang, projection in enumerate(attente.get("outbox") or [], start=1):
                if not isinstance(projection, dict):
                    griefs.append(_(
                        "dossier %(id)s : projection %(rang)s invalide",
                        id=identifiant, rang=rang))
                    continue
                creux = [
                    champ for champ in CHAMPS_OUTBOX_ATTENDUE if champ not in projection]
                if creux:
                    griefs.append(_(
                        "dossier %(id)s : projection %(rang)s incomplète — %(champs)s",
                        id=identifiant, rang=rang, champs=", ".join(creux)))
        if griefs:
            raise UserError(_(
                "Retrait refusé : l'empreinte attendue est incomplète.\n\n%s",
                "\n".join(griefs)))
        return True

    @api.model
    def _verrouiller_cibles(self, shipment_ids):
        """Fige les objets à muter, ou renonce — jamais d'attente.

        Les verrous existants du module sont des `pg_advisory_xact_lock`
        bloquants : ils sérialisent deux écritures concurrentes. Ce n'est pas ce
        qu'il faut ici. Une maintenance qui attend son tour reprend la main sur
        un état qu'elle n'a pas audité, et ses assertions portent alors sur un
        instantané périmé. `FOR UPDATE NOWAIT` renonce immédiatement : mieux
        vaut refaire le dry-run que réparer à l'aveugle.

        L'ordre des verrous est fixe — dossiers, départs, lignes, projections,
        chacun trié par identifiant — pour qu'aucun interblocage ne puisse
        naître de deux maintenances lancées en parallèle.

        Le verrou est pris AVANT la revalidation finale : entre l'assertion et
        la mutation, plus rien ne peut bouger.
        """
        cr = self.env.cr
        ids = sorted({int(identifiant) for identifiant in shipment_ids})
        requetes = [
            ("dossiers", "SELECT id FROM dally_shipment WHERE id = ANY(%s) "
                         "ORDER BY id FOR UPDATE NOWAIT"),
            ("départs prévus",
             "SELECT id FROM dally_freight_consolidation WHERE id IN ("
             "  SELECT DISTINCT planned_consolidation_id FROM dally_shipment"
             "   WHERE id = ANY(%s) AND planned_consolidation_id IS NOT NULL)"
             " ORDER BY id FOR UPDATE NOWAIT"),
            ("lignes de chargement",
             "SELECT id FROM dally_freight_consolidation_line "
             "WHERE shipment_id = ANY(%s) ORDER BY id FOR UPDATE NOWAIT"),
        ]
        if "dally.ops.sheet.outbox" in self.env:
            requetes.append((
                "projections",
                "SELECT id FROM dally_ops_sheet_outbox "
                "WHERE resource_model = 'dally.shipment' AND resource_id = ANY(%s) "
                "ORDER BY id FOR UPDATE NOWAIT"))
        for libelle, requete in requetes:
            try:
                cr.execute(requete, (ids,))
            except psycopg2.errors.LockNotAvailable as erreur:
                raise UserError(_(
                    "Une autre transaction travaille sur les %(quoi)s de ce "
                    "périmètre. Le retrait est abandonné : relancez la "
                    "simulation, l'état audité n'est plus garanti.", quoi=libelle)
                ) from erreur
        return ids

    @api.model
    def _apply_authorized_recovery(self, shipment_ids, expected, database):
        """Applique le retrait, après avoir rejoué toutes les assertions.

        ## Pourquoi cette méthode est privée

        Ce n'est pas une API métier, c'est un outil de maintenance. Le script
        restreint ses cibles à une liste fermée, mais une méthode publique
        offrirait un second chemin, sans cette restriction, à qui sait appeler
        un modèle. Le nom privé et les trois arguments obligatoires font que
        l'appel ne peut être qu'intentionnel.

        `expected` doit décrire **chaque** dossier visé : un retrait qui
        s'adapterait à ce qu'il trouve n'est plus une réparation, c'est une
        écriture aveugle.

        ## Pourquoi le savepoint est ici, et pas chez l'appelant

        Un appelant qui capture `UserError` — un contrôleur, un cron, un script
        maladroit — conserverait sinon une réparation à moitié faite. La
        garantie doit appartenir au service : le savepoint est ouvert ici,
        l'exception le traverse, et PostgreSQL a déjà tout défait quand elle
        parvient à l'appelant.
        """
        if not self.env.user.has_group("dally_core.group_dally_manager"):
            raise AccessError(_("Seul un Manager peut retirer une identité de collecte."))
        if not database:
            raise UserError(_("Le nom de la base cible est obligatoire."))
        if database != self.env.cr.dbname:
            raise UserError(_(
                "Base « %s » attendue, « %s » ouverte.", database, self.env.cr.dbname))
        if not shipment_ids:
            raise UserError(_("Aucun dossier ciblé."))
        if not expected:
            raise UserError(_("Les valeurs attendues sont obligatoires."))
        self._valider_schema_attentes(shipment_ids, expected)

        with self.env.cr.savepoint():
            return self._appliquer_sous_verrou(shipment_ids, expected)

    @api.model
    def _appliquer_sous_verrou(self, shipment_ids, expected):
        """Verrouille, oublie, revalide, mute — dans cet ordre et sans relâche.

        L'oubli n'est pas une précaution de style. L'appelant a presque
        toujours lancé une simulation avant d'autoriser le retrait, et cette
        lecture a peuplé le cache ORM. Revalider sans vider ce cache relirait
        les valeurs d'avant le verrou : le verrou ne protégerait plus rien, et
        la maintenance travaillerait sur un instantané qu'elle croit frais.

        L'invalidation est globale plutôt que ciblée. L'empreinte couvre le
        dossier, le départ prévu, les lignes de chargement, les projections,
        les encaissements, les pièces comptables et les devis : énumérer ces
        modèles ici créerait une liste à tenir synchronisée avec `_inspect`, et
        en oublier un est exactement la panne contre laquelle on se protège.
        """
        self._verrouiller_cibles(shipment_ids)
        self.env.invalidate_all()

        rapport = self.simulate(shipment_ids, expected=expected)
        if not rapport["dry_run_pass"]:
            raise UserError(_(
                "Retrait refusé : les préconditions ne sont pas réunies.\n\n%s",
                "\n".join(rapport["blocking"])))

        Shipment = self.env["dally.shipment"].with_context(active_test=False)
        Line = self.env["dally.freight.consolidation.line"].sudo()
        for detail in rapport["shipments"]:
            shipment = Shipment.browse(detail["shipment_id"])
            archive = detail["archive"]
            ancienne = detail["current_identity"]
            planifie = shipment.planned_consolidation_id

            # 3. Terminaliser la boîte d'envoi d'abord : une projection servie
            #    au milieu du retrait décrirait un état intermédiaire.
            self._retire_outbox(shipment, detail["outbox"], ancienne)

            # 4. Retirer le chargement — et rien que le sien. On rebrowse par
            #    identifiants capturés : si une ligne a bougé depuis la
            #    simulation, `exists()` la fait disparaître et la postcondition
            #    « 0 ligne » attrapera l'écart.
            lignes = Line.browse(detail["loaded_lines_to_remove"]).exists()
            etrangeres = lignes.filtered(lambda l: l.shipment_id.id != shipment.id)
            if etrangeres:
                raise UserError(_(
                    "Ligne(s) %s hors du dossier ciblé : retrait annulé.", etrangeres.ids))
            lignes.unlink()

            # 5. Puis seulement vider le plan : l'ordre inverse laisserait un
            #    dossier chargé sans plan, l'incohérence exacte que
            #    `_loaded_but_not_planned_shipments` dénonce.
            if planifie:
                shipment.with_context(
                    _dally_planned_retire_token=_PLANNED_RETIRE_TOKEN
                ).write({"planned_consolidation_id": False})

            # 6. L'identité d'archive.
            shipment.with_context(
                _dally_intake_identity_token=_INTAKE_IDENTITY_TOKEN
            ).write({
                "collection_sequence": archive["collection_sequence"],
                "collection_local_ref": archive["collection_local_ref"],
                "external_reference": archive["external_reference"],
            })

            # 7. La trace, sur le dossier et sur le départ délesté.
            self._trace(shipment, ancienne, archive, detail)
            if planifie:
                self._trace_consolidation(planifie, shipment, ancienne, detail)

            # 8. Les postconditions. Une seule qui manque et tout est annulé :
            #    lever ici propage jusqu'au ROLLBACK de la transaction.
            self._verifier_postconditions(shipment, archive, detail)

            _logger.info(
                "Intake identity retired: shipment=%s %s -> %s, %s line(s) unloaded, plan cleared=%s",
                shipment.id, ancienne["external_reference"],
                archive["external_reference"], len(lignes), bool(planifie))

        rapport["applied"] = True
        return rapport

    @api.model
    def _verifier_postconditions(self, shipment, archive, detail):
        """Relit la base après écriture, et refuse tout écart.

        Une réparation qui se contente d'avoir écrit n'a rien prouvé. On relit
        donc l'état obtenu, y compris ce qui devait rester intact : l'oubli le
        plus coûteux ne serait pas un champ mal écrit, mais un colis ou un
        historique disparu sans que personne le remarque.
        """
        shipment.invalidate_recordset()
        manques = []
        if shipment.state != "cancelled":
            manques.append(_("état %s au lieu de « annulé »", shipment.state))
        if shipment.intake_consolidation_id.id != detail["current_identity_intake_id"]:
            manques.append(_("la consolidation d'entrée a changé"))
        if shipment.planned_consolidation_id:
            manques.append(_("le départ prévu n'est pas vidé"))
        if shipment.collection_sequence != archive["collection_sequence"]:
            manques.append(_("numéro de collecte %s", shipment.collection_sequence))
        if shipment.collection_local_ref != archive["collection_local_ref"]:
            manques.append(_("référence locale %s", shipment.collection_local_ref))
        if shipment.external_reference != archive["external_reference"]:
            manques.append(_("référence globale %s", shipment.external_reference))
        if shipment.sync_source_key != detail["current_identity"]["sync_source_key"]:
            manques.append(_("la clé source a été modifiée"))
        if len(shipment.package_ids) != detail["package_count_before"]:
            manques.append(_(
                "%s colis au lieu de %s",
                len(shipment.package_ids), detail["package_count_before"]))
        if shipment.consolidation_line_ids:
            manques.append(_(
                "%s ligne(s) de chargement subsistent", len(shipment.consolidation_line_ids)))
        if shipment.sale_order_id or shipment.invoice_id:
            manques.append(_("un document commercial est apparu"))
        if manques:
            raise UserError(_(
                "Postconditions non tenues sur le dossier %(id)s : %(motifs)s.\n"
                "La transaction est annulée dans son intégralité.",
                id=shipment.id, motifs=" ; ".join(manques)))
        return True

    @api.model
    def _trace(self, shipment, ancienne, archive, detail):
        """Écrit dans le chatter ce qu'aucune colonne ne dira plus.

        Après le retrait, la base ne porte plus que la nouvelle identité. Sans
        cette note, personne ne pourrait relier le dossier annulé à la
        référence papier qu'il occupait — et c'est précisément la question que
        posera le premier audit.
        """
        plan = detail.get("planned_consolidation_to_clear") or {}
        shipment.message_post(
            body=_(
                "Retrait d'une identité de collecte annulée.<br/>"
                "Ancienne identité : %(ancien_externe)s (%(ancien_local)s, n° %(ancien_num)s)<br/>"
                "Nouvelle identité : %(nouvel_externe)s (%(nouveau_local)s, n° %(nouveau_num)s)<br/>"
                "Départ prévu retiré : %(plan)s<br/>"
                "Chargement retiré : %(lignes)s ligne(s), %(poids).3f kg, %(volume).4f m³<br/>"
                "Raison : Ancien dossier Ops de test annulé — identité et rattachement "
                "au départ retirés afin de libérer la référence réelle issue du Google "
                "Sheet. Historique et colis conservés.",
                ancien_externe=ancienne["external_reference"],
                ancien_local=ancienne["collection_local_ref"],
                ancien_num=ancienne["collection_sequence"],
                nouvel_externe=archive["external_reference"],
                nouveau_local=archive["collection_local_ref"],
                nouveau_num=archive["collection_sequence"],
                plan=plan.get("name") or "-",
                lignes=len(detail.get("loaded_lines_to_remove") or []),
                poids=detail.get("loaded_weight_total") or 0.0,
                volume=detail.get("loaded_volume_total") or 0.0,
            ),
            subtype_xmlid="mail.mt_note",
        )

    @api.model
    def _trace_consolidation(self, consolidation, shipment, ancienne, detail):
        """Dit au départ ce qui vient de quitter son manifeste.

        Les totaux d'un départ se recalculent depuis ses lignes : après le
        retrait, le poids baisse sans qu'aucune trace n'explique pourquoi. Un
        contrôle de manifeste qui compare deux impressions verrait un écart
        inexpliqué — et un écart inexpliqué sur un manifeste, c'est une
        suspicion de marchandise perdue.
        """
        consolidation.message_post(
            body=_(
                "Retrait de %(lignes)s colis de test du manifeste.<br/>"
                "Dossier : %(ref)s (%(client)s), annulé.<br/>"
                "Poids retiré : %(poids).3f kg — Volume retiré : %(volume).4f m³<br/>"
                "Détail : %(detail)s<br/>"
                "Raison : Ancien dossier Ops de test annulé — identité et rattachement "
                "au départ retirés afin de libérer la référence réelle issue du Google "
                "Sheet. Historique et colis conservés.",
                lignes=len(detail.get("loaded_lines_to_remove") or []),
                ref=ancienne["external_reference"],
                client=shipment.partner_id.display_name,
                poids=detail.get("loaded_weight_total") or 0.0,
                volume=detail.get("loaded_volume_total") or 0.0,
                detail=", ".join(
                    "%s (colis %s, %s)" % (
                        ligne.get("description") or "-",
                        ligne["package_id"], ligne["quantity_loaded"])
                    for ligne in detail.get("consolidation_lines") or []
                ) or "-",
            ),
            subtype_xmlid="mail.mt_note",
        )

    @api.model
    def _retire_outbox(self, shipment, lignes, ancienne):
        """Termine les projections en attente du dossier archivé.

        Le payload de la boîte d'envoi est recalculé à l'émission : une ligne
        restée en attente projetterait désormais l'identité d'archive, jamais
        l'ancienne. La référence papier est donc déjà hors de danger sans rien
        faire ici.

        Reste qu'une projection d'archive écrirait dans le classeur une ligne
        « A900842 » que personne n'a demandée. On la termine donc par
        ``acknowledge`` en refus permanent — le chemin que le modèle prévoit
        pour une projection devenue invalide : la ligne reste visible, porte
        son motif, et cesse d'occuper le transport. Aucun état n'est forcé en
        SQL, aucune méthode n'est ajoutée au modèle.
        """
        if not lignes or "dally.ops.sheet.outbox" not in self.env:
            return
        motif = "intake_identity_retired:%s" % (ancienne["external_reference"] or "")
        self.env["dally.ops.sheet.outbox"].sudo().acknowledge(
            shipment.company_id,
            [
                {"outbox_id": ligne["outbox_id"], "ok": False,
                 "permanent": True, "error": motif}
                for ligne in lignes
                if ligne["state"] in ("pending", "retry", "processing")
            ],
        )
