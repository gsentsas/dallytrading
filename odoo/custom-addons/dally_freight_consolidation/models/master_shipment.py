# -*- coding: utf-8 -*-
"""Une consolidation, une expédition maître tk_freight.

Une consolidation Dally décrit un départ physique : un mode, une route, une
fenêtre de collecte, un poids et un nombre de pièces déclarés sur la LTA mère.
`tk_freight` décrit le même départ dans son propre vocabulaire, avec ses ports,
ses compagnies et ses documents. Ce module fait le pont entre les deux — dans
un seul sens, à un seul moment : à la création du maître.

## Pourquoi ici et non dans le pont

`dally_freight_consolidation` dépend déjà de `dally_freight_bridge`. Y placer un
champ qui pointe vers la consolidation créerait une dépendance circulaire. Le
pont reste donc générique — il traduit du tk vers du Dally sans rien savoir des
consolidations — et c'est la consolidation qui connaît son maître.

## Ce que ce module ne fait pas

Il ne pilote **aucune étape** tk depuis l'état de la consolidation. Les deux
objets ont leur propre cycle de vie, et les faire s'écrire mutuellement ouvre
une boucle dont on ne sort qu'en ajoutant des jetons partout. La création
remplit ; ensuite, chacun vit sa vie.

Il ne touche pas non plus au `parent_id` ni à l'`operation` des expéditions
clientes existantes. Rattacher les maisons au maître est un autre sujet, avec
ses propres effets sur la facturation du fournisseur.

## Pourquoi la résolution des ports échoue plutôt que de deviner

`freight.shipment` route par `freight.port` — des enregistrements, contraints
par `port_ids`, et chacun marqué des modes qu'il sert. La consolidation, elle,
décrit sa route en texte libre : « Dakar », « Aéroport Blaise Diagne ». Passer
de l'un à l'autre par approximation finirait par router une consolidation
aérienne sur un port maritime, ou Dakar sur le mauvais Dakar.

La correspondance est donc **exacte et unique**, ou elle échoue en disant
pourquoi. Une consolidation qui ne peut pas créer son maître est un incident
visible qu'on corrige en configurant un port ; un maître routé au mauvais
endroit est un incident invisible qu'on découvre à l'arrivée.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


#: Mode Dally → `transport` tk. Les deux vocabulaires ne coïncident pas :
#: « maritime » se dit `sea` chez nous et `ocean` chez le fournisseur.
MODE_TO_TRANSPORT = {"air": "air", "sea": "ocean", "road": "land"}

#: Mode Dally → booléen de `freight.port` qui autorise ce mode.
MODE_TO_PORT_FLAG = {"air": "air", "sea": "ocean", "road": "land"}

#: États depuis lesquels le maître peut naître. Après le départ, la composition
#: est figée : créer le maître à ce moment-là écrirait dans un dossier clos.
STATES_ALLOWING_MASTER = ("draft", "collecting", "collection_closed", "ready")


class DallyFreightConsolidation(models.Model):
    _name = "dally.freight.consolidation"
    _inherit = "dally.freight.consolidation"

    tk_master_shipment_id = fields.Many2one(
        comodel_name="freight.shipment",
        string="Expédition maître",
        index=True,
        ondelete="set null",
        copy=False,
        # Même confinement que `dally.shipment.tk_shipment_id` : le portail ne
        # connaît que les références Dally. `group_dally_readonly` est impliqué
        # par tous les rôles Dally, donc le champ reste lisible en interne.
        groups="dally_core.group_dally_readonly",
        help="Expédition tk_freight qui porte cette consolidation. "
             "Vide tant que le maître n'a pas été créé.",
    )

    tk_master_shipment_count = fields.Integer(
        compute="_compute_tk_master_shipment_count",
        string="Maître",
    )

    #: Un maître, une consolidation. La contrainte est posée en base et non en
    #: Python : deux clics simultanés sur « Créer l'expédition » passent tous
    #: les deux la lecture avant que l'un ait écrit, et seule une contrainte
    #: d'unicité les sépare.
    _tk_master_shipment_unique = models.Constraint(
        "UNIQUE (tk_master_shipment_id)",
        "Cette expédition maître est déjà rattachée à une consolidation.",
    )

    @api.depends("tk_master_shipment_id")
    def _compute_tk_master_shipment_count(self):
        for record in self:
            record.tk_master_shipment_count = 1 if record.tk_master_shipment_id else 0

    # ------------------------------------------------------------------
    # La résolution des ports
    # ------------------------------------------------------------------

    def _dally_resolve_port(self, libelle, ville, pays):
        """Le `freight.port` de cette route, ou une erreur qui dit laquelle.

        Aucune recherche approximative : les comparaisons sont exactes, à la
        casse près. Un `ilike` avec jokers trouverait « Dakar » dans
        « Port-Dakar-Sud » et router ailleurs sans le dire.
        """
        self.ensure_one()
        drapeau = MODE_TO_PORT_FLAG[self.transport_mode]
        Port = self.env["freight.port"].sudo()
        socle = [(drapeau, "=", True), ("active", "=", True)]
        if pays:
            socle.append(("country_id", "=", pays.id))

        # Du plus précis au moins précis : un code IATA/OACI vaut mieux qu'un
        # nom, et un nom mieux qu'une ville.
        tentatives = []
        if libelle:
            tentatives.append(("code", libelle.strip()))
            tentatives.append(("name", libelle.strip()))
        if ville:
            tentatives.append(("city", ville.strip()))

        for champ, valeur in tentatives:
            if not valeur:
                continue
            trouves = Port.search(socle + [(champ, "=ilike", valeur)])
            if len(trouves) == 1:
                return trouves
            if len(trouves) > 1:
                raise UserError(_(
                    "Plusieurs ports « %(valeur)s » servent le mode %(mode)s : "
                    "%(liste)s. Précisez le port avant de créer l'expédition maître.",
                    valeur=valeur,
                    mode=self.transport_mode,
                    liste=", ".join(trouves.mapped("display_name")),
                ))

        raise UserError(_(
            "Aucun port ne correspond à « %(libelle)s / %(ville)s » pour le mode "
            "%(mode)s. Configurez le port dans Gestion du fret avant de créer "
            "l'expédition maître.",
            libelle=libelle or "—", ville=ville or "—", mode=self.transport_mode,
        ))

    def _dally_resolve_carrier(self, vals):
        """Le transporteur, s'il est identifiable sans ambiguïté.

        Contrairement à la route, un transporteur absent ne fait rien partir au
        mauvais endroit : on le remplit quand la correspondance est exacte et
        unique, et on laisse le champ vide sinon. C'est une commodité de
        saisie, pas une règle de routage.
        """
        self.ensure_one()
        nom = (self.carrier_name or "").strip()
        if not nom:
            return
        if self.transport_mode == "air":
            modele, champ, proprietaire = "freight.airline", "airline_id", "airline_owner_id"
        elif self.transport_mode == "sea":
            modele, champ, proprietaire = "freight.vessel", "vessel_id", "ship_owner_id"
        else:
            return
        trouves = self.env[modele].sudo().search([("name", "=ilike", nom)])
        if len(trouves) != 1:
            return
        vals[champ] = trouves.id
        # Le domaine du fournisseur lie la compagnie à son propriétaire : le
        # renseigner garde la fiche cohérente à l'écran.
        if trouves.owner_id:
            vals[proprietaire] = trouves.owner_id.id

    # ------------------------------------------------------------------
    # La table de correspondance
    # ------------------------------------------------------------------

    def _dally_master_shipment_values(self):
        """Les valeurs de l'expédition maître, ou une erreur explicite.

        Les trois incompatibilités bloquantes sont vérifiées ici, avant toute
        écriture : la direction, le mode, et la route. Ce sont les trois choses
        qu'un maître mal rempli enverrait au mauvais endroit.
        """
        self.ensure_one()

        # `tk_freight` ne connaît que l'import et l'export. Une consolidation
        # domestique n'a pas de maître à créer : il n'existe pas de valeur
        # honnête à mettre dans `direction`.
        if self.direction == "domestic":
            raise UserError(_(
                "Une consolidation domestique n'a pas d'équivalent dans le moteur "
                "fret, qui ne distingue que l'import et l'export."
            ))
        if self.direction not in ("import", "export"):
            raise UserError(_(
                "Direction « %s » sans équivalent dans le moteur fret.", self.direction or "—"
            ))

        transport = MODE_TO_TRANSPORT.get(self.transport_mode)
        if not transport:
            raise UserError(_(
                "Mode de transport « %s » sans équivalent dans le moteur fret.",
                self.transport_mode or "—",
            ))

        origine = self._dally_resolve_port(
            self.origin_location, self.origin_city, self.origin_country_id)
        destination = self._dally_resolve_port(
            self.destination_location, self.destination_city, self.destination_country_id)
        if origine == destination:
            raise UserError(_(
                "L'origine et la destination se résolvent sur le même port (%s).",
                origine.display_name,
            ))

        vals = {
            # `transport` doit être posé dès la création : la séquence de
            # référence du fournisseur en dépend.
            "transport": transport,
            "direction": self.direction,
            "operation": "master",
            "company_id": self.company_id.id,
            # `port_ids` conditionne le domaine des deux champs de route : sans
            # lui, l'écran refuserait les ports qu'on vient d'y écrire.
            "port_ids": [(6, 0, (origine | destination).ids)],
            "source_location_id": origine.id,
            "destination_location_id": destination.id,
            "pickup_datetime": self.scheduled_departure or False,
            "arrival_datetime": self.estimated_arrival or False,
            "notes": self.goods_nature or False,
        }

        # Le document maître ne porte pas le même nom selon le mode.
        reference_maitre = (self.mawb_number or "").strip()
        voyage = (self.flight_number or "").strip()
        if self.transport_mode == "air":
            vals["mawb_no"] = reference_maitre or False
            vals["flight_no"] = voyage or False
        elif self.transport_mode == "sea":
            vals["bl_number"] = reference_maitre or False
            vals["voyage_no"] = voyage or False
        else:
            vals["truck_ref"] = reference_maitre or False
            vals["trucker_number"] = voyage or False

        self._dally_resolve_carrier(vals)
        return vals

    def _dally_master_package_values(self):
        """La ligne colis agrégée du maître, ou rien.

        Un maître déclare un nombre de pièces et un poids brut — c'est ce que
        porte la LTA mère. `freight.shipment` les lit de ses lignes colis, dont
        les totaux sont calculés : on ne peut pas y écrire un poids directement.
        Une ligne unique, au nom de la consolidation, dit donc exactement ce que
        le document déclare, sans inventer de colis individuels.

        Si rien n'est déclaré, aucune ligne n'est créée : une ligne à zéro pièce
        serait un renseignement faux.
        """
        self.ensure_one()
        if self.master_piece_count <= 0 and self.master_gross_weight_kg <= 0:
            return None
        return {
            "name": self.name,
            "package_type": "item",
            "transport": MODE_TO_TRANSPORT[self.transport_mode],
            "qty": self.master_piece_count or 1,
            "gross_weight": self.master_gross_weight_kg or 0.0,
            "volume": self.client_volume_cbm or 0.0,
        }

    # ------------------------------------------------------------------
    # Les gestes
    # ------------------------------------------------------------------

    def action_create_master_shipment(self):
        """Crée l'expédition maître, une seule fois.

        Idempotente à deux niveaux. Si le lien existe déjà, on ouvre
        l'existante sans rien créer — c'est le cas du double clic et du rejeu
        d'un appel. Et si deux transactions passent malgré tout la lecture en
        même temps, la contrainte d'unicité en base refuse la seconde.
        """
        self.ensure_one()
        if self.tk_master_shipment_id:
            return self.action_open_master_shipment()

        if self.state not in STATES_ALLOWING_MASTER:
            raise UserError(_(
                "L'expédition maître se crée avant le départ. Cette consolidation "
                "est à l'état « %s ».",
                dict(self._fields["state"].selection).get(self.state, self.state),
            ))

        vals = self._dally_master_shipment_values()
        expedition = self.env["freight.shipment"].create(vals)

        ligne = self._dally_master_package_values()
        if ligne:
            self.env["shipment.package.line"].create(
                dict(ligne, shipment_id=expedition.id))

        self.tk_master_shipment_id = expedition
        self.message_post(body=_(
            "Expédition maître %s créée pour cette consolidation.",
            expedition.display_name,
        ))
        return self.action_open_master_shipment()

    def action_open_master_shipment(self):
        """Ouvre l'expédition maître de cette consolidation."""
        self.ensure_one()
        if not self.tk_master_shipment_id:
            raise UserError(_("Cette consolidation n'a pas encore d'expédition maître."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Expédition maître"),
            "res_model": "freight.shipment",
            "res_id": self.tk_master_shipment_id.id,
            "view_mode": "form",
        }


class FreightShipment(models.Model):
    """Le chemin de retour : d'une expédition vers sa consolidation."""

    _name = "freight.shipment"
    _inherit = "freight.shipment"

    #: Une relation inverse plutôt qu'une colonne : la clé vit sur la
    #: consolidation, et la contrainte d'unicité garantit que cette liste
    #: contient zéro ou un élément.
    dally_consolidation_ids = fields.One2many(
        comodel_name="dally.freight.consolidation",
        inverse_name="tk_master_shipment_id",
        string="Consolidations Dally",
        groups="dally_core.group_dally_readonly",
    )

    dally_consolidation_id = fields.Many2one(
        comodel_name="dally.freight.consolidation",
        string="Consolidation Dally",
        compute="_compute_dally_consolidation_id",
        groups="dally_core.group_dally_readonly",
    )

    @api.depends("dally_consolidation_ids")
    def _compute_dally_consolidation_id(self):
        for record in self:
            record.dally_consolidation_id = record.dally_consolidation_ids[:1]

    def action_open_dally_consolidation(self):
        """Ouvre la consolidation portée par cette expédition."""
        self.ensure_one()
        if not self.dally_consolidation_id:
            raise UserError(_("Cette expédition ne porte aucune consolidation Dally."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Consolidation"),
            "res_model": "dally.freight.consolidation",
            "res_id": self.dally_consolidation_id.id,
            "view_mode": "form",
        }
