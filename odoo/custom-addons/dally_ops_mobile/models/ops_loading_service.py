# -*- coding: utf-8 -*-
"""Préparer un départ depuis le quai, sans jamais devenir un second moteur.

## Ce que ce service décide, et ce qu'il délègue

Il décide **qui** agit — rôle Ops, société courante —, **sur quoi** — un
départ résolu par sa référence, un colis résolu par son identité opaque —, et
**quand** — la collecte doit être ouverte. Tout le reste appartient à Freight :
la compatibilité de route, le plafond de quantité, le verrou par colis et
l'unicité `(consolidation, colis)` restent gardés par le cœur, qui les
applique que l'appel vienne d'ici, du back-office ou d'un import.

Écrire une seconde fois ces règles ici les ferait diverger au premier
changement. Le service les appelle donc, et ne les recopie pas.

## Ce qu'un geste de chargement touche

Une seule table métier : `dally.freight.consolidation.line`. Ni le dossier, ni
le colis, ni le client, ni les paiements, ni l'état. C'est ce qui rend le
chargement compatible avec un dossier repris sans contredire l'étape 6 : la
fiche du dossier reste en lecture seule, c'est la **composition du départ**
qui change.

## Pourquoi le colis entier

Le cœur sait stocker une quantité partielle, et des chargements historiques
en portent. L'écran, lui, ne propose que le colis entier : demander une
quantité au clavier sur un téléphone, dans un entrepôt, produit des erreurs
de saisie que personne ne relit. Les lignes partielles existantes sont
affichées comme telles et peuvent être complétées, jamais créées.
"""

import hashlib
import json
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import ConcurrencyError

from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsNotFound

#: Les états où la composition se regarde. Le cœur n'autorise à la modifier
#: que dans le premier ; les deux autres servent à constater.
ETATS_VISIBLES = ("collecting", "collection_closed", "ready")

#: Le seul état où le cœur accepte une mutation de ligne.
ETAT_MUTABLE = "collecting"

ACTIONS = ("load", "unload")

ACTION_AUDIT_CHARGE = "package_loaded"
ACTION_AUDIT_RETIRE = "package_unloaded"

#: Ce qu'un colis vaut sur ce départ, décidé par le serveur.
STATUT_NON_CHARGE = "not_loaded"
STATUT_PARTIEL = "partial"
STATUT_CHARGE = "loaded"
STATUT_BLOQUE = "blocked"


class DallyOpsLoadingService(models.AbstractModel):
    _name = "dally.ops.loading.service"
    _description = "Dally Ops — chargement et complétude d'un départ"

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @api.model
    def list_consolidations(self):
        """Les départs que le quai peut préparer ou constater."""
        self._exiger_role_ops()
        departs = self.env["dally.freight.consolidation"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("state", "in", list(ETATS_VISIBLES)),
            ("active", "=", True),
        ], order="scheduled_departure asc, name asc")
        return {"consolidations": [
            {**self._entete(depart), "summary": self._resume(depart)}
            for depart in departs
        ]}

    @api.model
    def get_loading(self, reference):
        """Le détail d'un départ : ce qui est attendu, ce qui est chargé."""
        self._exiger_role_ops()
        depart = self._resoudre_depart(reference)
        return {"loading": self._detail(depart)}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    @api.model
    def apply_loading(self, reference, payload):
        """Charge ou retire un colis, une fois et une seule.

        L'ordre compte. Le verrou du geste précède la résolution du dossier :
        deux envois du même `request_uuid` arrivés ensemble se sérialisent
        avant d'avoir pu créer deux lignes. Le rejeu est reconnu ensuite, sur
        un état déjà stable.
        """
        request_uuid = self._request_uuid_pour_verrou(payload)

        with self.env.cr.savepoint():
            self._verrouiller_avant_instantane(request_uuid, reference)
            self._exiger_role_ops()
            donnees = self._valider(payload)

            depart = self._resoudre_depart(reference)
            colis = self._resoudre_colis(depart, donnees["package_reference"])
            intention = self._intention(depart, colis, donnees["action"])

            rejeu = self._rejeu(donnees["request_uuid"], intention)
            if rejeu is not None:
                return {"replayed": True, "loading": self._detail(depart)}

            # Relu dans la transaction, après le verrou du geste : une clôture
            # back-office concurrente est visible ici, jamais entre la
            # vérification et l'écriture.
            self._verrouiller_depart(depart)
            depart.invalidate_recordset(["state"])
            if depart.state != ETAT_MUTABLE:
                raise DallyOpsConflict(
                    _("La collecte de ce départ n'est plus ouverte."),
                    code="consolidation_not_collecting",
                )

            avant = self._quantite_ici(depart, colis)
            if donnees["action"] == "load":
                self._charger(depart, colis)
                action_audit = ACTION_AUDIT_CHARGE
            else:
                self._retirer(depart, colis)
                action_audit = ACTION_AUDIT_RETIRE
            apres = self._quantite_ici(depart, colis)

            self.env["dally.ops.loading.request"].sudo().create({
                "request_uuid": donnees["request_uuid"],
                "company_id": self.env.company.id,
                "consolidation_id": depart.id,
                "package_id": colis.id,
                "action": donnees["action"],
                "intent_hash": intention,
                "operator_user_id": self.env.uid,
            })
            self._journaliser(
                action_audit, depart, colis, donnees, avant, apres)
            return {"replayed": False, "loading": self._detail(depart)}

    # ------------------------------------------------------------------
    # Les deux gestes
    # ------------------------------------------------------------------

    @api.model
    def _charger(self, depart, colis):
        """Porte le colis à sa quantité entière sur ce départ.

        Le cœur reçoit une création ou une correction ; il verrouille le
        colis, revérifie la compatibilité et le plafond de quantité. Rien de
        cela n'est réécrit ici.
        """
        Ligne = self.env["dally.freight.consolidation.line"].sudo()
        ailleurs = self._quantite_ailleurs(depart, colis)
        if ailleurs:
            raise DallyOpsConflict(
                _("Ce colis est déjà chargé sur un autre départ."),
                code="package_loaded_elsewhere",
            )
        ligne = self._ligne(depart, colis)
        if not ligne:
            Ligne.create({
                "consolidation_id": depart.id,
                "package_id": colis.id,
                "quantity_loaded": colis.quantity,
            })
            return
        if ligne.quantity_loaded < colis.quantity:
            # La formule appartient au cœur : `create` l'applique déjà, et la
            # redire ici la ferait diverger au premier changement.
            ligne.write({
                "quantity_loaded": colis.quantity,
                **Ligne._mesures_chargees(colis, colis.quantity),
            })

    @api.model
    def _retirer(self, depart, colis):
        """Retire le chargement de ce colis sur ce départ, en entier.

        Un colis déjà absent n'est pas une erreur : le quai a peut-être
        retiré, perdu le réseau, puis rouvert l'écran. Le geste est sans
        effet, et le dire ainsi vaut mieux qu'un faux succès ou un faux
        conflit.
        """
        ligne = self._ligne(depart, colis)
        if ligne:
            ligne.unlink()

    # ------------------------------------------------------------------
    # Portée et résolution
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise DallyOpsError(
                _("Accès refusé."), code="ops_forbidden", status=403)

    @api.model
    def _resoudre_depart(self, reference):
        """Le départ désigné, dans la société de l'opérateur et dans un état
        où sa composition se regarde. Tout le reste répond « introuvable » :
        distinguer un départ parti d'un départ inexistant renseignerait sur
        des départs qu'on n'a pas à connaître."""
        if not isinstance(reference, str) or not reference.strip():
            raise DallyOpsNotFound(_("Départ introuvable."), code="consolidation_not_found")
        depart = self.env["dally.freight.consolidation"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("name", "=", reference.strip()),
            ("state", "in", list(ETATS_VISIBLES)),
            ("active", "=", True),
        ], limit=1)
        if not depart:
            raise DallyOpsNotFound(_("Départ introuvable."), code="consolidation_not_found")
        return depart

    @api.model
    def _resoudre_colis(self, depart, identite):
        """Le colis désigné, à condition qu'il soit attendu sur ce départ.

        L'identité opaque ne suffit pas : elle dit lequel, pas s'il a sa place
        ici. La société et l'appartenance aux dossiers attendus sont
        revérifiées, faute de quoi connaître un identifiant deviendrait un
        droit.
        """
        if not isinstance(identite, str) or not identite.strip():
            raise DallyOpsNotFound(_("Colis introuvable."), code="package_not_found")
        colis = self.env["dally.shipment.package"].sudo().search([
            ("ops_loading_uuid", "=", identite.strip()),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not colis or colis.shipment_id not in depart._expected_shipments():
            raise DallyOpsNotFound(_("Colis introuvable."), code="package_not_found")
        return colis

    #: Ce que vaut la part « société » de la clé quand le contexte n'en porte
    #: aucune. Une sentinelle, pas une société : deux appels sans contexte se
    #: gênent alors mutuellement, ce qui est sans conséquence — ils sont
    #: exceptionnels — là où une fenêtre d'instantané périmé, elle, ne l'est
    #: pas.
    SOCIETE_INCONNUE = 0

    @api.model
    def _societe_pour_verrou(self):
        """La part « société » de la clé de verrou. **Jamais** une garantie.

        ## Pourquoi aucune lecture ici

        `self.env.company` valide la société contre `env.companies` et émet un
        `SELECT` — mesuré : `res_company` quand le contexte porte
        `allowed_company_ids`, `res_users` quand il n'en porte pas. Cet
        ordre-là figerait l'instantané juste avant notre verrou et rouvrirait
        la fenêtre qu'on vient de fermer. Le repli ORM est donc exclu, y
        compris pour le cas rare.

        ## Ce que cette valeur est, et ce qu'elle n'est pas

        C'est une **clé de contention**, rien d'autre. L'isolation réelle
        reste vérifiée après le verrou, par les recherches métier :
        `_resoudre_depart` borne sur `company_id`, et un départ d'une autre
        société reste introuvable. Confondre les deux reviendrait à faire d'un
        verrou une frontière de sécurité, ce qu'il n'est pas.
        """
        autorisees = self.env.context.get("allowed_company_ids")
        return autorisees[0] if autorisees else self.SOCIETE_INCONNUE

    @api.model
    def _verrouiller_avant_instantane(self, request_uuid, reference):
        """Les deux verrous Ops, en **un seul ordre SQL**, avant toute lecture.

        ## Pourquoi deux clés, et pourquoi ensemble

        Le geste est protégé par son `request_uuid` : deux envois du même geste
        se sérialisent. Mais deux gestes **différents** visant le même départ
        ne partagent aucune clé — et c'est par là qu'une incohérence passait.
        Un `unload` supprime une ligne enfant sans jamais toucher la ligne
        `dally_freight_consolidation` ; un `load` concurrent obtenait donc son
        verrou de ligne sans erreur de sérialisation, gardait son instantané,
        y voyait encore la ligne supprimée, ne recréait rien, et répondait
        « chargé » sur une base où le colis ne l'était plus. Reproduit.

        Les deux clés sont donc prises dans le **même ordre SQL**. Deux
        `SELECT` successifs ne suffiraient pas : sous `REPEATABLE READ`, le
        premier fige déjà l'instantané, et le second arriverait trop tard.

        ## Pourquoi sans attendre

        Attendre rendrait la main sur un instantané périmé — le défaut qu'on
        vient de fermer. On tente ; si l'une des deux clés est tenue, on lève
        `ConcurrencyError`, que `service.model.retrying` rejoue sur une
        transaction neuve, dont l'instantané voit enfin l'état à jour.

        ## Ce que ce verrou ne protège pas

        Il ne protège **que** Ops contre Ops. Le back-office ne le prend pas ;
        c'est le verrou de ligne de `_verrouiller_depart` qui s'en charge.

        La clé du départ se construit sans ORM — société et référence
        normalisée — pour que rien ne soit lu avant elle.
        """
        societe = self._societe_pour_verrou()
        propre = reference.strip() if isinstance(reference, str) else "invalid"
        cles = ("ops-loading-request:%s:%s" % (societe, request_uuid),
                "ops-loading-departure:%s:%s" % (societe, propre))
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)),"
            "       pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
            list(cles))
        geste, depart = self.env.cr.fetchone()
        if not (geste and depart):
            raise ConcurrencyError(
                "Un autre geste de chargement occupe ce départ.")

    @api.model
    def _verrouiller_depart(self, depart):
        """Verrouille la ligne du départ, et non un verrou consultatif.

        ## Ce qu'un verrou consultatif ne pouvait pas voir

        Une clôture back-office ne prend pas nos clés — elle prend
        `consolidation:<préfixe>`, celle de la numérotation. Il n'y avait donc
        aucune contention avec un `ops-loading-consolidation:<id>`, et sous
        `REPEATABLE READ` notre instantané est figé depuis le premier ordre
        SQL : `invalidate_recordset` ne vide que le cache ORM, la relecture de
        `state` restait sur l'instantané, et une ligne pouvait naître après
        `collection_closed`.

        ## Ce que `FOR UPDATE` apporte

        Il porte sur la **ligne réelle**, celle que la clôture modifie. Si le
        départ a changé depuis notre instantané, PostgreSQL refuse le verrou
        avec une erreur de sérialisation ; s'il est tenu par une clôture en
        cours, `NOWAIT` refuse immédiatement plutôt que de rendre la main sur
        un instantané périmé.

        Les deux erreurs — `SerializationFailure` (40001) et
        `LockNotAvailable` (55P03) — figurent déjà dans
        `PG_CONCURRENCY_EXCEPTIONS_TO_RETRY` d'Odoo : vérifié dans cet
        environnement, avec psycopg2 2.9.9. Aucune conversion n'est donc
        nécessaire, `retrying` les rejoue telles quelles.

        Ce verrou ne sérialise **pas** deux gestes Ops entre eux : cette
        garantie appartient à `_verrouiller_avant_instantane`, pris plus tôt.
        """
        self.env.cr.execute(
            "SELECT id FROM dally_freight_consolidation WHERE id = %s "
            "FOR UPDATE NOWAIT",
            [depart.id],
        )

    # ------------------------------------------------------------------
    # Idempotence
    # ------------------------------------------------------------------

    @api.model
    def _intention(self, depart, colis, action):
        return hashlib.sha256(json.dumps({
            "consolidation": depart.id,
            "package": colis.id,
            "action": action,
        }, sort_keys=True).encode("utf-8")).hexdigest()

    @api.model
    def _rejeu(self, request_uuid, intention):
        """Le même geste, ou un autre qui usurpe son identifiant."""
        precedent = self.env["dally.ops.loading.request"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("request_uuid", "=", request_uuid),
        ], limit=1)
        if not precedent:
            return None
        if precedent.intent_hash != intention:
            raise DallyOpsConflict(
                _("Cet identifiant de geste a déjà servi à une autre "
                  "opération."),
                code="loading_request_conflict",
            )
        return precedent

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @api.model
    def _valider(self, payload):
        if not isinstance(payload, dict):
            raise DallyOpsError(_("Demande de chargement invalide."))
        attendus = {"request_uuid", "action", "package_reference"}
        if set(payload) != attendus:
            raise DallyOpsError(_("Demande de chargement invalide."))
        action = payload.get("action")
        if action not in ACTIONS:
            raise DallyOpsError(
                _("Action de chargement inconnue."), code="loading_action_invalid")
        reference_colis = payload.get("package_reference")
        if isinstance(reference_colis, str):
            reference_colis = reference_colis.strip()
        return {
            "request_uuid": self.env["dally.ops.intake.service"]._uuid(
                payload.get("request_uuid"), "request_uuid"),
            "action": action,
            # Pas de coercition : `(42 or "").strip()` lèverait une
            # `AttributeError`, et la route rendrait 500 là où le contrat
            # promet un refus. La valeur passe telle quelle, et
            # `_resoudre_colis` — qui sait déjà refuser ce qui n'est pas du
            # texte — rend « colis introuvable ».
            "package_reference": reference_colis,
        }

    @api.model
    def _request_uuid_pour_verrou(self, payload):
        """Une clé de verrou sans lecture ORM.

        La validation complète reste dans `_valider`, après le contrôle de
        rôle. Ici, on extrait seulement une valeur stable pour sérialiser deux
        envois concurrents avant qu'Odoo n'ouvre un snapshot métier.
        """
        if not isinstance(payload, dict):
            return "invalid"
        valeur = payload.get("request_uuid")
        if not isinstance(valeur, str):
            return "invalid"
        try:
            # `.strip()` comme `_uuid` : sans lui, « <uuid> » entouré d'espaces
            # tomberait sur la clé « invalid » tandis que le même identifiant
            # sans espaces prendrait la sienne. Les deux gestes échapperaient
            # alors à la sérialisation, et le second heurterait la contrainte
            # d'unicité du registre au lieu de se reconnaître comme un rejeu.
            return str(uuid.UUID(valeur.strip()))
        except (TypeError, ValueError):
            return "invalid"

    # ------------------------------------------------------------------
    # Ce que le quai voit
    # ------------------------------------------------------------------

    @api.model
    def _entete(self, depart):
        etats = dict(
            self.env["dally.freight.consolidation"]._fields["state"]
            ._description_selection(self.env))
        return {
            "reference": depart.name or "",
            "state": depart.state or "",
            "state_label": etats.get(depart.state, depart.state or ""),
            "transport_mode": depart.transport_mode or "",
            "direction": depart.direction or "",
            # La forme maison d'un lieu : l'écran préfère la ville au code
            # d'escale — un logisticien connaît Paris, pas forcément CDG.
            "origin": {
                "country_code": depart.origin_country_id.code or "",
                "city": depart.origin_city or "",
                "location": depart.origin_location or "",
            },
            "destination": {
                "country_code": depart.destination_country_id.code or "",
                "city": depart.destination_city or "",
                "location": depart.destination_location or "",
            },
            "collection_close_on": self._date(depart.collection_close_on),
            "scheduled_departure": self._date(depart.scheduled_departure),
            "can_load": depart.state == ETAT_MUTABLE,
        }

    @api.model
    def _detail(self, depart):
        attendus = depart._expected_shipments()
        releve = self._charges(depart, attendus.mapped("package_ids"))
        dossiers = [
            self._dossier(depart, shipment, releve)
            for shipment in attendus.sorted(lambda rec: rec.external_reference or "")
        ]
        return {
            **self._entete(depart),
            "summary": self._resume(depart, attendus, releve),
            "shipments": dossiers,
        }

    @api.model
    def _dossier(self, depart, shipment, releve):
        colis = [self._colis(depart, paquet, releve)
                 for paquet in shipment.package_ids.sorted("sequence")]
        return {
            "reference": shipment.external_reference or "",
            "local_reference": shipment.collection_local_ref or "",
            # Le nom seul : préparer un départ demande de reconnaître le
            # dossier, pas de joindre le client.
            "customer": {"name": shipment.partner_id.name or ""},
            "complete": bool(colis) and all(
                item["status"] == STATUT_CHARGE for item in colis),
            "packages": colis,
        }

    @api.model
    def _colis(self, depart, paquet, releve):
        ici, ailleurs = releve[0].get(paquet.id, 0), releve[1].get(paquet.id, 0)
        mutable = depart.state == ETAT_MUTABLE
        if ailleurs:
            statut, blocage = STATUT_BLOQUE, _(
                "Déjà chargé sur un autre départ actif.")
        elif ici >= paquet.quantity and paquet.quantity:
            statut, blocage = STATUT_CHARGE, None
        elif ici:
            statut, blocage = STATUT_PARTIEL, None
        else:
            statut, blocage = STATUT_NON_CHARGE, None
        return {
            "reference": paquet.ops_loading_uuid or "",
            "description": paquet.description or "",
            "goods_category": paquet.goods_category or "",
            "package_type": paquet.package_type or "",
            "expected_quantity": paquet.quantity,
            "loaded_quantity": ici,
            "remaining_quantity": max(paquet.quantity - ici, 0),
            "exact_weight_kg": paquet.total_weight_kg,
            "volume_cbm": paquet.total_volume_cbm,
            "status": statut,
            "can_load": mutable and statut in (STATUT_NON_CHARGE, STATUT_PARTIEL),
            "can_unload": mutable and statut in (STATUT_CHARGE, STATUT_PARTIEL),
            "blocker": blocage,
        }

    @api.model
    def _resume(self, depart, attendus=None, releve=None):
        """Des comptes, pas un pourcentage.

        Un taux unique cacherait la question qui compte au quai : *lesquels*
        manquent. « 12 sur 18 » se vérifie d'un coup d'œil sur la pile ; « 83 %
        » ne se vérifie pas du tout, et se trompe dès que les colis n'ont pas
        le même poids.
        """
        if attendus is None:
            attendus = depart._expected_shipments()
        paquets = attendus.mapped("package_ids")
        # `charges` est déjà le compteur de colis chargés, plus bas : le
        # relevé porte donc un autre nom, faute de quoi il serait écrasé.
        if releve is None:
            releve = self._charges(depart, paquets)
        charges = partiels = bloques = 0
        quantite_attendue = quantite_chargee = 0
        poids_attendu = poids_charge = 0.0
        volume_attendu = volume_charge = 0.0
        complets = 0
        for shipment in attendus:
            colis_complets = bool(shipment.package_ids)
            for paquet in shipment.package_ids:
                ici = releve[0].get(paquet.id, 0)
                ailleurs = releve[1].get(paquet.id, 0)
                quantite_attendue += paquet.quantity
                quantite_chargee += ici
                poids_attendu += paquet.total_weight_kg
                volume_attendu += paquet.total_volume_cbm
                if ailleurs:
                    bloques += 1
                    colis_complets = False
                elif ici >= paquet.quantity and paquet.quantity:
                    charges += 1
                    poids_charge += paquet.total_weight_kg
                    volume_charge += paquet.total_volume_cbm
                else:
                    colis_complets = False
                    if ici:
                        partiels += 1
            if colis_complets:
                complets += 1
        return {
            "shipments_expected": len(attendus),
            "shipments_complete": complets,
            "packages_expected": len(paquets),
            "packages_loaded": charges,
            "packages_partial": partiels,
            "packages_remaining": len(paquets) - charges - partiels - bloques,
            "packages_blocked": bloques,
            "quantity_expected": quantite_attendue,
            "quantity_loaded": quantite_chargee,
            "weight_expected_kg": poids_attendu,
            "weight_loaded_kg": poids_charge,
            "volume_expected_cbm": volume_attendu,
            "volume_loaded_cbm": volume_charge,
        }

    # ------------------------------------------------------------------
    # Outils
    # ------------------------------------------------------------------

    @api.model
    def _ligne(self, depart, paquet):
        return self.env["dally.freight.consolidation.line"].sudo().search([
            ("consolidation_id", "=", depart.id),
            ("package_id", "=", paquet.id),
        ], limit=1)

    @api.model
    def _charges(self, depart, paquets):
        """Ce qui est chargé, ici et ailleurs, en deux requêtes pour tous.

        La version naïve interrogeait la base deux fois **par colis**. Sur le
        départ de banc — 713 colis — cela faisait plus de mille requêtes pour
        afficher un écran. Le relevé est donc fait une fois, pour l'ensemble,
        et les vues se contentent de le lire.
        """
        Ligne = self.env["dally.freight.consolidation.line"].sudo()
        ici = dict.fromkeys(paquets.ids, 0)
        ailleurs = dict.fromkeys(paquets.ids, 0)
        if not paquets:
            return ici, ailleurs
        for ligne in Ligne.search([("package_id", "in", paquets.ids)]):
            paquet_id = ligne.package_id.id
            if ligne.consolidation_id == depart:
                ici[paquet_id] = ici.get(paquet_id, 0) + ligne.quantity_loaded
            elif ligne.consolidation_id.state != "cancelled":
                ailleurs[paquet_id] = ailleurs.get(paquet_id, 0) + ligne.quantity_loaded
        return ici, ailleurs

    @api.model
    def _quantite_ici(self, depart, paquet):
        return sum(self._ligne(depart, paquet).mapped("quantity_loaded"))

    @api.model
    def _quantite_ailleurs(self, depart, paquet):
        lignes = self.env["dally.freight.consolidation.line"].sudo().search([
            ("package_id", "=", paquet.id),
            ("consolidation_id", "!=", depart.id),
        ])
        return sum(lignes.filtered(
            lambda ligne: ligne.consolidation_id.state != "cancelled"
        ).mapped("quantity_loaded"))

    def _journaliser(self, action, depart, colis, donnees, avant, apres):
        """Ancre la trace sur le départ, jamais sur la ligne.

        Un retrait supprime la ligne : l'ancrer sur elle laisserait dans le
        journal un identifiant qui ne résout plus rien, et rendrait les deux
        actions dissymétriques pour qui relit la piste. Le départ, lui, existe
        avant et après. Le colis est nommé par son identité opaque, et la
        quantité dit ce qui a réellement changé.
        """
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": action,
            "entity_model": "dally.freight.consolidation",
            "entity_res_id": depart.id,
            "shipment_id": colis.shipment_id.id,
            "request_uuid": donnees["request_uuid"],
            "changes_json": [{
                "field": "package_reference",
                "old_value": "",
                "new_value": colis.ops_loading_uuid or "",
            }, {
                "field": "quantity_loaded",
                "old_value": str(avant),
                "new_value": str(apres),
            }],
        })

    @staticmethod
    def _date(valeur):
        return valeur.isoformat() if valeur else ""
