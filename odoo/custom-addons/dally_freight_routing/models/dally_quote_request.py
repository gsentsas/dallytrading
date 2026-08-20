# -*- coding: utf-8 -*-
"""L'acheminement d'une demande de devis.

Le mode ne s'y lit jamais en clair. Il se déduit du service commercial, et pour
deux services — groupage et véhicule — de la marchandise elle-même, parce que
« transport de véhicule » dit ce que le client achète et non par quoi la
voiture voyage. Ces règles existent déjà dans `dally_freight_bridge`, qui s'en
sert pour provisionner le fournisseur ; les reprendre plutôt que les réécrire
garantit que l'écran et le provisionnement ne se contrediront pas.
"""

import logging
from datetime import date

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

#: Ce que le client peut déclarer et qui n'existait nulle part.
#:
#: Enlèvement, livraison et date souhaitée étaient demandés à l'oral ou dans le
#: champ message. Les porter en clair évite qu'une contrainte de calendrier se
#: perde dans un paragraphe.


class DallyQuoteRequest(models.Model):
    # `_name` explicite : sans lui, Odoo 19 crée un modèle fantôme au lieu
    # d'appliquer le mixin au modèle existant.
    _name = "dally.quote.request"
    _inherit = ["dally.quote.request", "dally.freight.routing.mixin"]

    def _dally_champs_declencheurs(self):
        # `vehicle_cargo_id` n'y figure pas : c'est un champ **calculé**, il
        # n'apparaît donc jamais dans les valeurs d'une écriture et n'aurait
        # rien déclenché. C'est la cargaison qui prévient la demande quand son
        # mode change — voir `dally_freight_vehicle_cargo.py`.
        return {"service_type_id", "groupage_transport_mode"}

    def _dally_transport(self):
        self.ensure_one()
        from odoo.addons.dally_freight_bridge.models.freight_mapping import (
            GROUPAGE_MODE_TO_TRANSPORT,
            SERVICE_CODE_TO_TRANSPORT,
            VEHICLE_MODE_TO_TRANSPORT,
        )
        code = self.service_type_id.code or ""
        direct = SERVICE_CODE_TO_TRANSPORT.get(code)
        if direct:
            return direct
        if code == "freight_groupage":
            couple = GROUPAGE_MODE_TO_TRANSPORT.get(self.groupage_transport_mode or "")
            return couple[0] if couple else False
        if code == "freight_vehicle":
            # La logique véhicule est conservée telle quelle : c'est la
            # marchandise qui porte le mode, et un roulier reste du maritime.
            cargo = self.vehicle_cargo_id
            return VEHICLE_MODE_TO_TRANSPORT.get(cargo.transport_mode or "") if cargo else False
        return False

    # ─── Ce que le client déclare en plus ────────────────────────────

    pickup_requested = fields.Boolean(
        string="Enlèvement demandé",
        help="Le client demande un enlèvement à l'adresse d'origine.",
    )
    pickup_address = fields.Text(string="Adresse d'enlèvement")
    delivery_requested = fields.Boolean(string="Livraison demandée")
    delivery_address = fields.Text(string="Adresse de livraison")
    desired_date = fields.Date(
        string="Date souhaitée",
        help="Date souhaitée par le client. Déclarative : elle n'engage ni le "
             "départ ni l'arrivée, et ne sert qu'à savoir si le dossier est "
             "urgent.",
    )

    # ─── Le payload public, résolu par codes ─────────────────────────

    @api.model
    def _dally_prepare_values(self, payload):
        """Ajoute l'acheminement structuré aux valeurs de la demande.

        ## Des codes, résolus, jamais des identifiants

        Le navigateur envoie « SNDKR », « SN-DK », « FOB ». Chaque code est
        cherché dans son référentiel ; s'il n'existe pas, la valeur est
        simplement absente. Un identifiant, lui, serait toujours plausible :
        rien dans « 7 » ne permet de dire s'il désigne le port qu'on croit.

        ## La vérification de cohérence

        Un port maritime déclaré sur une demande de fret aérien n'est pas
        seulement inutile : il produirait un dossier faux, qu'un commercial
        prendrait pour une saisie du client. Le lieu n'est donc retenu que si
        son drapeau correspond au transport déduit du service — et le refus est
        journalisé, parce qu'un écart entre ce que le formulaire propose et ce
        qu'il envoie signale un défaut à corriger, pas un client à blâmer.

        ## Ce qui n'est jamais lu ici

        Ni transporteur, ni compagnie, ni navire, ni itinéraire fréquent. Ces
        clés n'existent pas dans la liste blanche publique, et si elles y
        entraient un jour, elles ne seraient pas reprises ici : elles relèvent
        de la qualification commerciale, pas de la demande du client.
        """
        valeurs = super()._dally_prepare_values(payload)

        Etat = self.env["res.country.state"]
        Lieu = self.env["freight.port"]
        Incoterm = self.env["account.incoterms"]

        def code(cle):
            brut = payload.get(cle)
            return brut.strip().upper() if isinstance(brut, str) and brut.strip() else ""

        def etat(cle_code, id_pays):
            valeur = code(cle_code)
            if not valeur or not id_pays:
                return False
            # Le code est cherché **dans le pays déjà résolu** : « DK » existe
            # au Sénégal comme ailleurs, et un code seul ne désigne rien.
            trouve = Etat.sudo().search(
                [("code", "=", valeur), ("country_id", "=", id_pays)], limit=1)
            return trouve.id or False

        transport = self._dally_transport_du_payload(payload)

        def lieu(cle_code):
            valeur = code(cle_code)
            if not valeur:
                return False
            trouve = Lieu.sudo().search(
                [("code", "=", valeur), ("active", "=", True)], limit=1)
            if not trouve:
                return False
            if transport and not trouve[transport]:
                _logger.info(
                    "Lieu %s écarté : incompatible avec le transport %s.",
                    valeur, transport)
                return False
            return trouve.id

        def booleen(cle):
            """Le nettoyeur public transforme un booléen en chaîne.

            `_clean_payload` accepte `str`, `int` et `float` ; en Python un
            booléen **est** un entier, si bien que `True` traverse le filtre et
            ressort en « True ». Plutôt que de toucher à un nettoyage partagé
            par tous les points d'entrée, on accepte ici les deux formes.
            """
            brut = payload.get(cle)
            if isinstance(brut, bool):
                return brut
            return str(brut or "").strip().lower() in ("true", "1", "yes", "on")

        def date_souhaitee():
            brut = payload.get("desired_date")
            if not isinstance(brut, str) or not brut.strip():
                return False
            try:
                return date.fromisoformat(brut.strip()[:10])
            except ValueError:
                return False

        incoterm = Incoterm.sudo().search(
            [("code", "=", code("incoterm_code"))], limit=1) if code("incoterm_code") else Incoterm

        valeurs.update({
            "origin_state_id": etat("origin_state_code", valeurs.get("origin_country_id")),
            "destination_state_id": etat(
                "destination_state_code", valeurs.get("destination_country_id")),
            "origin_port_id": lieu("origin_port_code"),
            "destination_port_id": lieu("destination_port_code"),
            "incoterm_id": incoterm.id or False,
            "pickup_requested": booleen("pickup_requested"),
            "pickup_address": (payload.get("pickup_address") or "")[:500] or False,
            "delivery_requested": booleen("delivery_requested"),
            "delivery_address": (payload.get("delivery_address") or "")[:500] or False,
            "desired_date": date_souhaitee(),
        })
        return valeurs

    @api.model
    def _dally_transport_du_payload(self, payload):
        """Transport déduit d'un payload, avant que la demande n'existe.

        Même règle que `_dally_transport` sur l'enregistrement, appliquée à un
        dictionnaire : le service donne le mode, sauf pour le groupage qui le
        porte à part.

        Le véhicule rend `False`, et c'est délibéré : sa cargaison n'est créée
        qu'après la demande, si bien qu'au moment de l'admission le mode n'est
        pas encore connu. Un lieu déclaré est alors **conservé tel quel** — il
        n'y a pas de contradiction à détecter tant qu'il n'y a pas de mode, et
        rien n'est deviné. Le lieu sera retiré plus tard s'il se révèle
        incompatible, quand la cargaison déclarera son mode.
        """
        from odoo.addons.dally_freight_bridge.models.freight_mapping import (
            GROUPAGE_MODE_TO_TRANSPORT,
            SERVICE_CODE_TO_TRANSPORT,
        )
        service = self.env["dally.service.type"]._get_by_code(
            payload.get("service_code"))
        code_service = service.code if service else ""
        direct = SERVICE_CODE_TO_TRANSPORT.get(code_service)
        if direct:
            return direct
        if code_service == "freight_groupage":
            couple = GROUPAGE_MODE_TO_TRANSPORT.get(
                payload.get("groupage_transport_mode") or "")
            return couple[0] if couple else False
        return False
