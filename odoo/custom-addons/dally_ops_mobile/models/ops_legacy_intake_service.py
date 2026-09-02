# -*- coding: utf-8 -*-
"""Lire un dossier que Dally Ops n'a pas créé, et seulement le lire.

## Pourquoi un second service plutôt qu'un domaine élargi

La fiche native protège des mutations : articles, encaissements, états,
photos, événements. Son résolveur est l'unique porte de tout cela. L'élargir
pour afficher un dossier repris du tableur ouvrirait ces gestes sur des
données dont le modèle Ops ne répond pas — la référence locale y manque, la
consolidation d'entrée aussi, et les colis n'y portent pas la clé de ligne que
les corrections utilisent pour se retrouver.

Ce service-ci n'écrit rien. Aucun ``create``, aucun ``write``, aucun
``unlink``, aucune mise en file. C'est vérifiable par lecture de l'arbre
syntaxique, et un test le vérifie.

## Comment les deux chemins restent disjoints

Un dossier natif est **refusé** ici, et un dossier repris est refusé là-bas.
La reconnaissance ne recopie pas la règle : elle appelle
``_domaine_dossier_ops()`` du service natif. Deux formulations de la même
condition divergeraient au premier changement, et un dossier finirait par
s'ouvrir des deux côtés — ou d'aucun.

## Ce que la référence désigne

``external_reference``, la référence globale, et elle seule.
``collection_local_ref`` est locale à son départ : deux consolidations ont
chacune leur ``A001``. Elle s'affiche, elle ne navigue jamais.
"""

from odoo import _, api, models

from .ops_errors import DallyOpsError, DallyOpsNotFound


class DallyOpsLegacyIntakeService(models.AbstractModel):
    _name = "dally.ops.legacy.intake.service"
    _description = "Dally Ops — fiche en lecture seule d'un dossier repris"

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @api.model
    def get_legacy_intake(self, reference):
        """Le dossier repris, réduit à ce qu'un logisticien doit reconnaître.

        Aucune transition, aucun droit d'écriture, aucun motif de blocage : il
        n'y a rien à débloquer. Les publier ferait croire qu'une action
        viendra, et un écran qui promet est pire qu'un écran qui se tait.
        """
        self._exiger_role_ops()
        shipment = self._resoudre_dossier_legacy(reference)
        return {"intake": self._detail_legacy(shipment)}

    # ------------------------------------------------------------------
    # Portée
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        """Le service décide lui-même pour qui il travaille.

        Le contrôleur vérifie déjà le rôle pour choisir le code HTTP ; cette
        seconde vérification garantit que le privilège reste hors d'atteinte
        quel que soit l'appelant.
        """
        if not self.env["res.users"]._dally_ops_role():
            raise DallyOpsError(
                _("Accès refusé."), code="ops_forbidden", status=403)

    @api.model
    def _resoudre_dossier_legacy(self, reference):
        """Le dossier repris désigné par sa référence globale, et lui seul.

        Trois refus, et le même message pour les trois : une référence vide,
        un dossier absent de la société, et un dossier natif. Distinguer le
        troisième renseignerait sur l'existence d'un dossier qu'on n'a pas le
        droit d'ouvrir par ce chemin.
        """
        if not isinstance(reference, str) or not reference.strip():
            raise DallyOpsNotFound(
                _("Dossier introuvable."), code="intake_not_found")

        Dossier = self.env["dally.shipment"].sudo()
        shipment = Dossier.search([
            # C'est le dossier qui porte l'isolation, jamais son client : un
            # partenaire partagé entre deux sociétés ne doit pas la contourner.
            ("company_id", "=", self.env.company.id),
            ("external_reference", "=", reference.strip()),
        ], limit=1)
        if not shipment:
            raise DallyOpsNotFound(
                _("Dossier introuvable."), code="intake_not_found")

        # Le domaine natif est appelé, pas recopié : c'est lui qui définit ce
        # qu'est un dossier Ops, et cette fiche-ci n'a pas à le redire.
        natif = Dossier.search_count(
            self.env["dally.ops.intake.line.service"]._domaine_dossier_ops()
            + [("id", "=", shipment.id)]
        )
        if natif:
            raise DallyOpsNotFound(
                _("Dossier introuvable."), code="intake_not_found")
        return shipment

    # ------------------------------------------------------------------
    # Ce que le comptoir voit
    # ------------------------------------------------------------------

    @api.model
    def _detail_legacy(self, shipment):
        """La projection, entièrement énumérée ici.

        Rien n'est repris du DTO natif : celui-ci porte la tarification, les
        transitions permises et la clé de ligne de chaque colis. Les hériter
        pour en retirer ensuite les champs gênants ferait dépendre la sécurité
        d'une soustraction — et une soustraction s'oublie.
        """
        colis = self._colis(shipment)
        # Une seule lecture des encaissements : la liste et son total disent la
        # même chose et doivent donc la dire du même instant.
        paiements = self.env["dally.ops.payment.service"].payments_for(shipment)
        return {
            # Le serveur déclare la nature de la fiche ; l'écran ne la déduit
            # pas d'une absence de bouton.
            "readonly": True,
            "reference": shipment.external_reference or "",
            "local_reference": shipment.collection_local_ref or "",
            "state": shipment.state or "",
            "state_label": self._libelle_etat(shipment.state),
            "transport_mode": shipment.transport_mode or "",
            "direction": shipment.direction or "",
            "consolidation_reference": (
                shipment.intake_consolidation_id.name
                or shipment.consolidation_id.name
                or ""),
            "received_on": self._date(
                shipment.goods_received_on or shipment.request_date),
            "customer": self._client(shipment),
            "lines": colis,
            "totals": {
                "lines_count": len(colis),
                "weight_kg": sum(ligne["exact_weight_kg"] for ligne in colis),
                "volume_cbm": sum(ligne["volume_cbm"] for ligne in colis),
            },
            "payments": self._projeter_paiements(paiements),
            "payment_summary": self.env[
                "dally.ops.payment.service"].payment_summary(paiements),
        }

    @api.model
    def _colis(self, shipment):
        """Tous les colis du dossier, sans filtre de convention.

        Le DTO natif ne retient que les colis dont `external_line_key` porte
        le préfixe de la clé source du dossier. Cette convention est celle de
        Dally Ops ; les dossiers repris en ont deux autres — `sheets:…` et un
        format historique à barres verticales. Filtrer sur l'une d'elles
        cacherait les colis de l'autre, et la fiche annoncerait un dossier
        vide là où il y a des marchandises.

        Le colis ne porte ni `active` ni `state` : il n'y a rien à écarter.
        """
        return [
            {
                "description": paquet.description or "",
                "goods_category": paquet.goods_category or "",
                "package_type": paquet.package_type or "",
                "quantity": paquet.quantity,
                "announced_weight_kg": paquet.announced_weight_kg or None,
                "exact_weight_kg": paquet.total_weight_kg,
                "length_cm": paquet.length_cm or None,
                "width_cm": paquet.width_cm or None,
                "height_cm": paquet.height_cm or None,
                "volume_cbm": paquet.total_volume_cbm,
            }
            for paquet in shipment.sudo().package_ids
        ]

    @api.model
    def _client(self, shipment):
        """Le nom et le numéro, rien d'autre.

        Le comptoir doit reconnaître la personne devant lui ; il n'a besoin ni
        de son adresse, ni de son courriel, ni de son WhatsApp. Les deux
        champs rendus sont ceux que la recherche affiche déjà : ouvrir la
        fiche ne divulgue donc rien de neuf.

        Le privilège est ciblé sur cette projection et n'ouvre aucune lecture
        de `res.partner` à l'opérateur.
        """
        partenaire = shipment.sudo().partner_id
        return {
            "name": partenaire.name or "",
            "phone": partenaire.phone or "",
        }

    @staticmethod
    def _projeter_paiements(paiements):
        """Les encaissements déjà faits, pour ne pas encaisser deux fois.

        La liste vient du service des paiements, qui inclut volontairement
        ceux venus du tableur. Sa `reference` est retirée : pour un
        encaissement non `ops:`, elle rend la clé externe telle quelle. C'est
        une identité technique, elle ne dit rien au logisticien, et elle n'a
        donc pas à sortir.

        Les champs sont énumérés plutôt que retranchés : ce qui apparaîtra un
        jour dans le DTO des paiements n'arrivera pas ici par surprise.
        """
        return [
            {
                "amount": paiement["amount"],
                "currency_code": paiement["currency_code"],
                "payment_date": paiement["payment_date"],
                "payment_method": paiement["payment_method"],
                "collector": paiement["collector"],
                "accounting_status": paiement["accounting_status"],
            }
            for paiement in paiements
        ]

    @api.model
    def _libelle_etat(self, etat):
        """Le libellé de l'état, lu dans la sélection du modèle.

        Recopier ces libellés dans le navigateur en ferait une seconde source,
        qui divergerait le jour où un état changerait de mot.
        """
        if not etat:
            return ""
        etats = dict(
            self.env["dally.shipment"]._fields["state"]
            ._description_selection(self.env))
        return etats.get(etat, etat)

    @staticmethod
    def _date(valeur):
        return valeur.isoformat() if valeur else ""
