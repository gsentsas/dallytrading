# -*- coding: utf-8 -*-
"""Projections portail — ce qu'un client voit de chacun de ses dossiers.

## Une deuxième barrière, pas la seule

Ces listes blanches ne remplacent ni les ACL ni les ``groups=`` posés sur les champs
sensibles. Elles s'y ajoutent. La différence compte : un champ protégé par
``groups=`` n'est **pas chargé** par l'ORM pour un utilisateur portail, même s'il le
demande explicitement par ``read()``. Une liste blanche, elle, ne protège que ce qui
passe par elle — un futur contrôleur qui sérialiserait un record autrement la
contournerait sans s'en apercevoir.

L'ordre de défense est donc : ACL → record rule → ``groups=`` sur les champs →
projection. Ce fichier est la dernière couche, la plus visible et la moins
essentielle.

## Pourquoi des listes explicites plutôt qu'une exclusion

Une liste d'exclusion protège les champs qu'on a pensé à exclure. Un champ ajouté
demain à ``dally.trade.opportunity`` serait exposé par défaut. Une liste blanche fait
l'inverse : il est absent tant que quelqu'un ne l'ajoute pas sciemment.
"""

from odoo import fields, models


class DallyPortalProjectionMixin(models.AbstractModel):
    """Le détail vaut la liste, sauf mention contraire.

    Une liste doit rester légère : y joindre les propositions de chaque demande de
    sourcing ferait une requête par ligne pour des données que la liste n'affiche
    pas. Une page de détail, elle, a besoin de plus.

    D'où deux projections, et un défaut qui les rend identiques. Un modèle qui n'a
    rien de plus à montrer en détail n'a rien à écrire ; celui qui en a surcharge
    cette méthode. L'alternative — enrichir depuis le contrôleur — remettrait de la
    logique de projection à l'endroit précis d'où on l'a sortie.
    """

    _name = "dally.portal.projection.mixin"
    _description = "Portal projection helpers"

    def _dally_portal_detail_payload(self):
        self.ensure_one()
        return self._dally_portal_payload()


class DallyQuoteRequestPortal(models.Model):
    # `_name` EST OBLIGATOIRE ici, et sa valeur doit répéter le modèle étendu.
    #
    # Avec `_inherit` sous forme de liste et sans `_name`, Odoo 19 ne comprend
    # pas « étendre ce modèle » : il dérive un nom depuis le nom de la classe et
    # crée un modèle NEUF — ici `dally.quote.request.portal` — avec sa propre
    # table. Les projections disparaissent alors du vrai modèle sans qu'aucune
    # erreur ne soit levée, et un `upgrade` en production créerait la table.
    # Constaté sur l'instance E2E, en vérifiant le MRO.
    _name = "dally.quote.request"
    _inherit = ["dally.quote.request", "dally.portal.projection.mixin"]

    PORTAL_PAYLOAD_KEYS = (
        "reference", "service", "status", "createdOn",
        "origin", "destination", "goodsDescription", "quantity",
        "canDecide", "customerDecisionAt",
    )

    def _dally_portal_payload(self):
        """Ce que le client voit de sa demande de devis.

        Absents volontairement : `internal_notes` et `user_id` (protégés par
        ``groups=``), `lead_id`, `sale_order_ids` et les champs UTM. La provenance
        marketing d'une demande est une information sur nous, pas sur le client.
        """
        self.ensure_one()
        payload = {
            "reference": self.reference,
            "service": self.service_code or None,
            "status": self.state,
            "createdOn": (
                self.create_date.date().isoformat() if self.create_date else None
            ),
            "origin": ", ".join(filter(None, [
                self.origin_city, self.origin_country_id.name])) or None,
            "destination": ", ".join(filter(None, [
                self.destination_city, self.destination_country_id.name])) or None,
            "goodsDescription": self.goods_description or None,
            "quantity": self.quantity or None,
            "canDecide": self._dally_portal_can_decide(),
            "customerDecisionAt": (
                fields.Datetime.to_string(self.customer_decision_at)
                if self.customer_decision_at else None
            ),
        }
        return {key: payload[key] for key in self.PORTAL_PAYLOAD_KEYS}

    def _dally_portal_detail_payload(self):
        """La demande, plus le véhicule qu'elle décrit s'il y en a un.

        Le véhicule n'apparaît que dans le DÉTAIL, jamais dans la liste : celle-ci
        porte le VIN et l'immatriculation de chaque dossier, et les afficher en
        vrac multiplierait sans raison les endroits où ils circulent.
        """
        self.ensure_one()
        payload = dict(self._dally_portal_payload())
        vehicule = self._dally_portal_vehicle_payload()
        if vehicule:
            payload["vehicle"] = vehicule

        # Le mode d'un envoi groupé, en libellé client.
        #
        # « Groupage » et « Maritime » répondent à deux questions différentes :
        # ce que le client a commandé, et comment sa marchandise voyage. Les
        # afficher séparément évite la confusion que le modèle interne a
        # justement pour but d'empêcher.
        if self.service_code == "freight_groupage" and self.groupage_transport_mode:
            libelles = dict(
                self._fields["groupage_transport_mode"]._description_selection(self.env)
            )
            payload["groupage"] = {
                "transportMode": self.groupage_transport_mode,
                "transportModeLabel": libelles.get(self.groupage_transport_mode),
            }
        return payload

    def _dally_portal_vehicle_payload(self):
        """Projection du véhicule, depuis `dally.freight.vehicle.cargo`.

        La **source est le cargo**, jamais `vehicle_make`/`vehicle_model` du
        devis. Ces trois-là ne sont qu'un miroir entretenu par le cargo ; les
        relire comme source métier réintroduirait la seconde vérité que le
        miroir existe précisément pour éviter.

        `sudo()` après autorisation : c'est le `search` sous l'utilisateur réel,
        plus haut dans la chaîne, qui a établi que ce dossier lui appartient.
        Lire la marchandise de SON dossier en est la conséquence serveur.
        """
        self.ensure_one()
        if "dally.freight.vehicle.cargo" not in self.env:
            return None
        cargo = self.env["dally.freight.vehicle.cargo"].sudo().search(
            [("quote_request_id", "=", self.id)], limit=1
        )
        return cargo._dally_portal_vehicle_projection() if cargo else None


class DallyFreightVehicleCargoPortal(models.Model):
    """Ce qu'un client voit de son propre véhicule.

    Liste blanche explicite, comme partout ailleurs : les champs internes
    (`internal_notes`, `purchase_price`) portent déjà `groups=` et ne sont pas
    chargés pour un utilisateur portail, mais cette projection est appelée en
    `sudo()` — la protection par groupes ne s'y applique donc pas, et c'est
    l'énumération ci-dessous qui décide seule.

    ## Le VIN complet, et pourquoi

    Le VIN sort en entier. C'est une décision produit assumée : ce détail est
    privé et réservé au propriétaire authentifié, et c'est précisément le numéro
    qui lui permet d'identifier son véhicule sans ambiguïté — sur un connaissement,
    auprès d'une douane, dans un litige. Le masquer ici le priverait de la seule
    donnée qui distingue deux voitures identiques.

    Il reste absent des listes, du suivi public et des journaux.
    """

    _name = "dally.freight.vehicle.cargo"
    _inherit = "dally.freight.vehicle.cargo"

    def _dally_portal_vehicle_projection(self):
        self.ensure_one()

        def libelle(champ):
            """Libellé traduit d'une sélection, jamais son code.

            Le client lit « Maritime », pas `sea` : notre vocabulaire interne
            n'a aucune raison de traverser jusqu'à lui.
            """
            valeur = self[champ]
            if not valeur:
                return None
            return dict(
                self._fields[champ]._description_selection(self.env)
            ).get(valeur, valeur)

        return {
            "make": self.make or None,
            "model": self.model or None,
            "year": self.year or None,
            "vin": self.vin or None,
            "registration": self.registration or None,
            "color": self.color or None,
            "category": self.category or None,
            "categoryLabel": libelle("category"),
            "condition": self.condition or None,
            "conditionLabel": libelle("condition"),
            "fuelType": self.fuel or None,
            "fuelTypeLabel": libelle("fuel"),
            "keyCount": self.key_count or 0,
            "transportMode": self.transport_mode or None,
            "transportModeLabel": libelle("transport_mode"),
            "pickupRequested": bool(self.pickup_requested),
            # Adresse projetée seulement si la prestation est demandée : une
            # adresse résiduelle affichée au client lui ferait croire à un
            # enlèvement qui n'aura pas lieu.
            "pickupAddress": (self.pickup_address or None) if self.pickup_requested else None,
            "deliveryRequested": bool(self.delivery_requested),
            "deliveryAddress": (self.delivery_address or None) if self.delivery_requested else None,
        }


class DallySourcingRequestPortal(models.Model):
    # `_name` EST OBLIGATOIRE ici, et sa valeur doit répéter le modèle étendu.
    #
    # Avec `_inherit` sous forme de liste et sans `_name`, Odoo 19 ne comprend
    # pas « étendre ce modèle » : il dérive un nom depuis le nom de la classe et
    # crée un modèle NEUF — ici `dally.sourcing.request.portal` — avec sa propre
    # table. Les projections disparaissent alors du vrai modèle sans qu'aucune
    # erreur ne soit levée, et un `upgrade` en production créerait la table.
    # Constaté sur l'instance E2E, en vérifiant le MRO.
    _name = "dally.sourcing.request"
    _inherit = ["dally.sourcing.request", "dally.portal.projection.mixin"]

    PORTAL_PAYLOAD_KEYS = (
        "reference", "status", "productName", "productReference",
        "quantity", "unit", "createdOn",
    )

    def _dally_portal_payload(self):
        """Ce que le client voit de sa demande de sourcing.

        Rien de la mise en concurrence : ni fournisseurs consultés, ni offres, ni
        scores, ni coûts rendus. Ces champs sont déjà inaccessibles par ``groups=``
        et par l'absence d'ACL sur ``dally.sourcing.offer`` et
        ``dally.sourcing.supplier`` ; leur absence ici est la troisième expression
        de la même règle.
        """
        self.ensure_one()
        payload = {
            "reference": self.reference,
            "status": self.state,
            "productName": self.product_name or None,
            "productReference": self.product_reference or None,
            "quantity": self.quantity,
            "unit": self.uom_id.name or None,
            "createdOn": (
                self.create_date.date().isoformat() if self.create_date else None
            ),
        }
        return {key: payload[key] for key in self.PORTAL_PAYLOAD_KEYS}

    def _dally_portal_detail_payload(self):
        """La demande, plus les propositions qui lui ont été envoyées.

        ``search`` explicite plutôt que ``self.proposal_ids``. La différence est de
        sécurité : parcourir un one2many renvoie les identifiants liés sans
        appliquer les record rules — la lecture des champs lèverait ensuite une
        ``AccessError`` au lieu de filtrer. Un ``search`` applique la règle et
        **écarte** ce qui n'est pas visible, ce qui est exactement le comportement
        voulu ici : une proposition en brouillon doit être absente, pas provoquer
        une erreur qui trahirait son existence.
        """
        self.ensure_one()
        payload = dict(self._dally_portal_payload())
        proposals = self.env["dally.sourcing.proposal"].search(
            [("request_id", "=", self.id)], order="create_date desc, id desc",
        )
        payload["proposals"] = [
            proposal._dally_portal_payload() for proposal in proposals
        ]
        return payload


class DallySourcingProposalPortal(models.Model):
    _inherit = "dally.sourcing.proposal"

    PORTAL_PAYLOAD_KEYS = (
        "reference", "status", "productName", "quantity", "unit",
        "unitPrice", "total", "currency", "validUntil", "estimatedDelivery",
        "commercialTerms",
    )

    def _dally_portal_payload(self):
        """Ce que le client voit d'une proposition qui lui est faite.

        Le prix de vente et le total y figurent : c'est ce qu'on lui demande
        d'accepter. `cost_basis` et `margin` non — ils portent ``groups=`` et
        décrivent notre position, pas la sienne.
        """
        self.ensure_one()
        payload = {
            "reference": self.reference,
            "status": self.state,
            "productName": self.product_name or None,
            "quantity": self.quantity,
            "unit": self.uom_id.name or None,
            "unitPrice": self.selling_unit_price,
            "total": self.total_amount,
            "currency": self.currency_id.name or None,
            "validUntil": (
                self.validity_date.isoformat() if self.validity_date else None
            ),
            "estimatedDelivery": (
                self.estimated_delivery.isoformat()
                if self.estimated_delivery else None
            ),
            "commercialTerms": self.commercial_terms or None,
        }
        return {key: payload[key] for key in self.PORTAL_PAYLOAD_KEYS}


class DallyTradeOpportunityPortal(models.Model):
    # `_name` EST OBLIGATOIRE ici, et sa valeur doit répéter le modèle étendu.
    #
    # Avec `_inherit` sous forme de liste et sans `_name`, Odoo 19 ne comprend
    # pas « étendre ce modèle » : il dérive un nom depuis le nom de la classe et
    # crée un modèle NEUF — ici `dally.trade.opportunity.portal` — avec sa propre
    # table. Les projections disparaissent alors du vrai modèle sans qu'aucune
    # erreur ne soit levée, et un `upgrade` en production créerait la table.
    # Constaté sur l'instance E2E, en vérifiant le MRO.
    _name = "dally.trade.opportunity"
    _inherit = ["dally.trade.opportunity", "dally.portal.projection.mixin"]

    PORTAL_PAYLOAD_KEYS = (
        "reference", "subject", "operationType", "operationTypeLabel",
        "status", "saleTotal", "currency", "origin", "destination",
        "expectedClose", "createdOn",
    )

    def _dally_portal_payload(self):
        """Projection **client** d'une opération, pas le modèle interne.

        Un dossier de trading a deux contreparties. Le client n'en est qu'une : il
        voit le volet qui le concerne — l'objet, le type, l'état, le montant de
        vente — et rien du volet achat. `supplier_id`, `purchase_subtotal`, les
        coûts, les commissions et les marges portent tous ``groups=`` et ne sont
        pas chargés pour lui.
        """
        self.ensure_one()
        from odoo.addons.dally_trade.models.dally_trade_rules import OPERATION_TYPES
        labels = dict(OPERATION_TYPES)
        payload = {
            "reference": self.reference,
            "subject": self.name,
            "operationType": self.operation_type,
            "operationTypeLabel": labels.get(
                self.operation_type, self.operation_type),
            "status": self.state,
            "saleTotal": self.sale_subtotal,
            "currency": self.sale_currency_id.name or None,
            "origin": self.origin_country_id.name or None,
            "destination": self.destination_country_id.name or None,
            "expectedClose": (
                self.expected_close_date.isoformat()
                if self.expected_close_date else None
            ),
            "createdOn": (
                self.create_date.date().isoformat() if self.create_date else None
            ),
        }
        return {key: payload[key] for key in self.PORTAL_PAYLOAD_KEYS}


class DallyShipmentPortal(models.Model):
    # `_name` EST OBLIGATOIRE ici, et sa valeur doit répéter le modèle étendu.
    #
    # Avec `_inherit` sous forme de liste et sans `_name`, Odoo 19 ne comprend
    # pas « étendre ce modèle » : il dérive un nom depuis le nom de la classe et
    # crée un modèle NEUF — ici `dally.shipment.portal` — avec sa propre
    # table. Les projections disparaissent alors du vrai modèle sans qu'aucune
    # erreur ne soit levée, et un `upgrade` en production créerait la table.
    # Constaté sur l'instance E2E, en vérifiant le MRO.
    _name = "dally.shipment"
    _inherit = ["dally.shipment", "dally.portal.projection.mixin"]

    def _dally_portal_payload(self):
        """Réutilise la projection publique du suivi, déjà éprouvée.

        `dally_tracking` expose déjà une vue publique de l'expédition, avec sa
        propre liste blanche et sa timeline filtrée sur `visible_to_customer`. La
        redéfinir ici créerait une seconde définition de « ce qu'un client voit
        d'une expédition », et les deux divergeraient — c'est toujours la moins
        relue qui finit par exposer quelque chose.

        La différence tient au chemin d'accès, pas au contenu : le suivi public
        exige référence + token, le portail s'appuie sur l'identité authentifiée.
        """
        self.ensure_one()
        return self._dally_public_payload()

    def _dally_portal_detail_payload(self):
        """L'expédition, plus le détail de ses colis.

        Le suivi public s'arrête à ``packagesCount`` : un visiteur muni d'un lien de
        suivi n'a pas à connaître le contenu et les dimensions de chaque colis. Le
        client authentifié, lui, regarde son propre envoi — c'est la seule
        différence de fond entre les deux chemins d'accès, et elle est ici.

        ``search`` plutôt que ``self.package_ids``, pour la même raison que sur le
        sourcing : c'est le ``search`` qui applique la record rule.
        """
        self.ensure_one()
        payload = dict(self._dally_public_payload())
        packages = self.env["dally.shipment.package"].search(
            [("shipment_id", "=", self.id)], order="sequence, id",
        )
        payload["packages"] = packages._dally_portal_package_payload()

        # Les documents publiés de cette expédition, dans la même forme que sur
        # la page Documents : un seul contrat pour un document, quel que soit
        # l'endroit d'où le client l'atteint. Deux formes divergeraient, et
        # c'est la moins relue qui finirait par exposer un champ de trop.
        #
        # `search` et non `self.document_ids` : c'est le `search` qui applique
        # la record rule. Le filtre sur `published_to_portal` est redondant avec
        # elle, et c'est voulu — la publication est une décision explicite, elle
        # mérite d'être exigée deux fois.
        documents = self.env["dally.portal.document"].search(
            [
                ("shipment_id", "=", self.id),
                ("published_to_portal", "=", True),
            ],
            order="create_date desc, id desc",
        )
        payload["documents"] = [
            document._dally_portal_payload() for document in documents
        ]

        # Véhicule transporté, s'il y en a un. Même source que sur le devis :
        # `dally.freight.vehicle.cargo`, jamais les champs miroir.
        vehicule = self._dally_portal_shipment_vehicle()
        if vehicule:
            payload["vehicle"] = vehicule

        # Type d'envoi, distinct du mode physique déjà présent dans le payload.
        #
        # Le mode dit « Maritime » ou « Aérien » ; ceci dit « Groupage ». Une
        # expédition groupée aérienne affiche donc les deux, ce qui est la
        # lecture juste — et jamais « groupage » comme mode de transport, qui
        # calculerait le poids taxable au mauvais ratio.
        type_envoi = self._dally_portal_shipment_service()
        if type_envoi:
            payload["shipmentType"] = type_envoi

        return payload

    def _dally_portal_shipment_service(self):
        """Type d'envoi hérité du devis d'origine, s'il est remarquable.

        On remonte au devis par le booking du fournisseur plutôt que de stocker
        l'information une seconde fois : le lien existe déjà, et une donnée
        recopiée finit toujours par diverger de sa source.
        """
        self.ensure_one()
        if "shipment.freight.booking" not in self.env:
            return None
        expedition = self.sudo().tk_shipment_id
        if not expedition or not expedition.booking_id:
            return None
        devis = expedition.booking_id.sudo().dally_quote_request_id
        if not devis or devis.service_code != "freight_groupage":
            return None
        return {"code": "groupage", "label": "Groupage"}

    def _dally_portal_shipment_vehicle(self):
        """Véhicule rattaché à cette expédition, s'il y en a un.

        Le rattachement est posé par le pont au provisionnement. On repart de
        lui plutôt que du devis : une expédition peut exister sans que son devis
        soit encore accessible, et c'est le véhicule réellement transporté qui
        intéresse le client à ce stade.
        """
        self.ensure_one()
        if "dally.freight.vehicle.cargo" not in self.env:
            return None
        cargo = self.env["dally.freight.vehicle.cargo"].sudo().search(
            [("shipment_id", "=", self.id)], limit=1
        )
        return cargo._dally_portal_vehicle_projection() if cargo else None


class DallyShipmentPackagePortal(models.Model):
    _inherit = "dally.shipment.package"

    PORTAL_PAYLOAD_KEYS = (
        "packageType", "description", "quantity",
        "totalWeightKg", "totalVolumeCbm",
    )

    def _dally_portal_package_payload(self):
        """Ce que le client voit de ses colis.

        Les dimensions unitaires ne sont pas reprises : ce sont des données de
        calcul d'affrètement, et le client raisonne en poids et volume totaux.
        Aucun identifiant technique, comme partout ailleurs dans cette couche.
        """
        labels = dict(
            self._fields["package_type"]._description_selection(self.env)
        )
        payload = []
        for package in self:
            row = {
                "packageType": labels.get(
                    package.package_type, package.package_type),
                "description": package.description or None,
                "quantity": package.quantity,
                "totalWeightKg": package.total_weight_kg,
                "totalVolumeCbm": package.total_volume_cbm,
            }
            payload.append({key: row[key] for key in self.PORTAL_PAYLOAD_KEYS})
        return payload
