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

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError

from .shipment import _INTAKE_IDENTITY_TOKEN, _PLANNED_RETIRE_TOKEN

_logger = logging.getLogger(__name__)

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
    def apply(self, shipment_ids, expected=None, database=None):
        """Applique le retrait, après avoir rejoué toutes les assertions.

        La simulation n'est jamais une autorisation : la base a pu bouger entre
        les deux. Chaque assertion est rejouée ici, et une seule divergence
        annule l'ensemble — pas seulement le dossier fautif. Une réparation
        partielle laisserait un départ à moitié réparé, plus difficile à lire
        qu'un départ non réparé.
        """
        if not self.env.user.has_group("dally_core.group_dally_manager"):
            raise AccessError(_("Seul un Manager peut retirer une identité de collecte."))
        if database and database != self.env.cr.dbname:
            raise UserError(_(
                "Base « %s » attendue, « %s » ouverte.", database, self.env.cr.dbname))

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
