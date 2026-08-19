# -*- coding: utf-8 -*-
"""L'acheminement, exprimé en relations plutôt qu'en texte.

## Un seul vocabulaire

`freight.port` porte trois drapeaux — `ocean`, `air`, `land` — et le pont
`dally_freight_bridge` désigne le transport par ces trois mêmes mots. Ce n'est
pas une coïncidence exploitée après coup : c'est ce qui permet d'écrire le
domaine d'un port comme `[(transport, "=", True)]`, sans table de
correspondance intermédiaire, donc sans endroit où deux vérités puissent
diverger.

Le mode commercial de Dally — `sea`, `air`, `road` — reste distinct et n'est
traduit qu'ici, par les tables du pont. Les deux vocabulaires cohabitent parce
qu'ils décrivent deux choses : ce que le client achète, et par quoi la
marchandise voyage.

## Pourquoi un mixin

Une demande de devis et une expédition posent les mêmes questions d'origine, de
destination et de transport, mais ne savent pas leur mode de la même façon :
l'expédition le porte en clair, le devis le déduit de son service et, pour le
groupage ou le véhicule, de la marchandise elle-même. Le mixin tient tout ce
qui est commun et laisse un seul point ouvert, `_dally_transport`, que chaque
modèle remplit à sa manière.

## Les domaines, calculés côté serveur

Un domaine qui dépend du mode ne s'écrit pas lisiblement dans une vue : il
faudrait imbriquer des conditions dans une expression évaluée par le
navigateur. Odoo 19 offre mieux — un champ `Binary` calculé, référencé par
`domain="nom_du_champ"` (motif du noyau, `account.tax.repartition.line`). La
règle reste en Python, où elle se lit et se teste.
"""

from odoo import api, fields, models

from odoo.addons.dally_freight_bridge.models.freight_mapping import (
    GROUPAGE_MODE_TO_TRANSPORT,
    VEHICLE_MODE_TO_TRANSPORT,
)

#: Les trois transports physiques, dans le vocabulaire du fournisseur, qui est
#: aussi celui des drapeaux de `freight.port`.
TRANSPORTS = [("ocean", "Maritime"), ("air", "Aérien"), ("land", "Terrestre")]

#: Ce qu'un changement de transport rend caduc.
#:
#: Un navire n'a rien à faire sur un envoi aérien, ni une compagnie aérienne sur
#: un envoi maritime. Le transporteur partenaire disparaît aussi en aérien : la
#: compagnie y est portée par `airline_id`, et laisser les deux renseignés
#: créerait deux réponses à « qui transporte ».
CHAMPS_PAR_TRANSPORT = {
    "ocean": {"airline_id"},
    "air": {"vessel_id", "carrier_partner_id"},
    "land": {"vessel_id", "airline_id"},
}


class DallyFreightRoutingMixin(models.AbstractModel):
    _name = "dally.freight.routing.mixin"
    _description = "Acheminement structuré (origine, destination, transport)"

    # ─── Géographie ──────────────────────────────────────────────────

    origin_state_id = fields.Many2one(
        comodel_name="res.country.state", string="Région d'origine",
        ondelete="restrict", index=True,
        help="Subdivision administrative du pays d'origine.",
    )
    destination_state_id = fields.Many2one(
        comodel_name="res.country.state", string="Région de destination",
        ondelete="restrict", index=True,
    )
    origin_port_id = fields.Many2one(
        comodel_name="freight.port", string="Port / aéroport d'origine",
        ondelete="restrict", index=True,
        help="Le lieu réel de départ de la marchandise. Il n'est pas filtré "
             "par le pays d'origine : une expédition partie de Bamako "
             "s'embarque à Dakar, et brider le choix au pays interdirait le "
             "cas le plus courant de la sous-région.",
    )
    destination_port_id = fields.Many2one(
        comodel_name="freight.port", string="Port / aéroport de destination",
        ondelete="restrict", index=True,
    )

    # ─── Transport ───────────────────────────────────────────────────

    freight_transport = fields.Selection(
        selection=TRANSPORTS, string="Transport physique",
        compute="_compute_freight_transport",
        help="Déduit du mode ou du service. Sert à filtrer les lieux et les "
             "transporteurs, et à masquer ce qui ne s'applique pas.",
    )
    frequent_route_id = fields.Many2one(
        comodel_name="freight.frequent.route", string="Itinéraire fréquent",
        ondelete="set null",
        help="Raccourci de saisie. Il propose les deux lieux ; il ne les impose "
             "pas et n'écrase jamais un choix déjà fait.",
    )
    carrier_partner_id = fields.Many2one(
        comodel_name="res.partner", string="Transporteur",
        ondelete="restrict", index=True,
        help="Compagnie maritime ou transporteur routier, selon le mode. En "
             "aérien, c'est `airline_id` qui fait foi.",
    )
    airline_id = fields.Many2one(
        comodel_name="freight.airline", string="Compagnie aérienne",
        ondelete="restrict",
    )
    vessel_id = fields.Many2one(
        comodel_name="freight.vessel", string="Navire", ondelete="restrict",
    )
    incoterm_id = fields.Many2one(
        comodel_name="account.incoterms", string="Incoterm",
        ondelete="restrict",
        help="Incoterm Odoo natif. `freight.incoterms`, livré presque vide par "
             "le fournisseur, n'est pas utilisé : deux référentiels d'incoterms "
             "seraient deux vérités.",
    )

    # ─── Domaines dynamiques ─────────────────────────────────────────

    port_domain = fields.Binary(
        string="Domaine des lieux", compute="_compute_routing_domains",
        help="Technique. Restreint les lieux au mode courant.",
    )
    carrier_domain = fields.Binary(
        string="Domaine des transporteurs", compute="_compute_routing_domains",
    )
    frequent_route_domain = fields.Binary(
        string="Domaine des itinéraires", compute="_compute_routing_domains",
    )

    # ------------------------------------------------------------------
    # Le point ouvert
    # ------------------------------------------------------------------

    def _dally_transport(self):
        """Transport physique de cet enregistrement : ocean, air, land ou False.

        `False` n'est pas une erreur : un service de conseil ou une demande
        encore imprécise n'a pas de mode, et il vaut mieux le dire que de
        supposer du maritime parce que c'est le plus fréquent. Les domaines
        restent alors ouverts et les champs propres à un mode sont masqués —
        jamais remplis d'office.
        """
        self.ensure_one()
        return False

    def _dally_champs_declencheurs(self):
        """Champs dont l'écriture peut changer le transport."""
        return set()

    @api.depends_context("uid")
    def _compute_freight_transport(self):
        for record in self:
            record.freight_transport = record._dally_transport()

    @api.depends("freight_transport")
    def _compute_routing_domains(self):
        etiquettes = self.env["ir.model.data"]
        for record in self:
            transport = record.freight_transport
            record.port_domain = [(transport, "=", True)] if transport else []

            # Le transporteur suit la taxonomie posée par `dally_freight_data` :
            # compagnie maritime en `ocean`, transporteur routier en `land`.
            # Hors de ces deux cas, aucune restriction — mieux vaut une liste
            # large qu'une liste fausse.
            categorie = {
                "ocean": "partner_category_shipping_line",
                "land": "partner_category_road_carrier",
            }.get(transport)
            if categorie:
                reference = etiquettes._xmlid_to_res_id(
                    "dally_freight_data.%s" % categorie, raise_if_not_found=False)
                record.carrier_domain = (
                    [("category_id", "in", [reference])] if reference else [])
            else:
                record.carrier_domain = []

            if transport:
                record.frequent_route_domain = [
                    ("source_location_id.%s" % transport, "=", True),
                    ("destination_location_id.%s" % transport, "=", True),
                ]
            else:
                record.frequent_route_domain = []

    # ------------------------------------------------------------------
    # Assistance à la saisie
    # ------------------------------------------------------------------

    @api.onchange("origin_country_id")
    def _onchange_origin_country_routing(self):
        """Une région qui n'est plus dans le pays choisi ne peut pas rester."""
        for record in self:
            if record.origin_state_id.country_id != record.origin_country_id:
                record.origin_state_id = False

    @api.onchange("destination_country_id")
    def _onchange_destination_country_routing(self):
        for record in self:
            if record.destination_state_id.country_id != record.destination_country_id:
                record.destination_state_id = False

    @api.onchange("frequent_route_id")
    def _onchange_frequent_route_id(self):
        """Propose les deux lieux de l'itinéraire, sans jamais écraser un choix.

        Un itinéraire fréquent est un raccourci, pas une décision. Si l'origine
        est déjà renseignée avec autre chose, c'est que quelqu'un l'a voulu :
        la remplacer ferait disparaître une information sans le dire, et la
        personne ne s'en apercevrait qu'à la relecture du dossier.
        """
        for record in self:
            route = record.frequent_route_id
            if not route:
                continue
            if not record.origin_port_id:
                record.origin_port_id = route.source_location_id
            if not record.destination_port_id:
                record.destination_port_id = route.destination_location_id

    @api.onchange("origin_port_id")
    def _onchange_origin_port_id(self):
        """Recopie la ville du lieu, si elle manque.

        `origin_city` reste lu par le portail, l'API et les projections. Tant
        qu'ils existent, la chaîne doit rester cohérente avec la relation —
        mais elle n'est renseignée que si elle est vide : une ville saisie à la
        main peut être plus précise que celle du port.
        """
        for record in self:
            if record.origin_port_id and not record.origin_city:
                record.origin_city = record.origin_port_id.city

    @api.onchange("destination_port_id")
    def _onchange_destination_port_id(self):
        for record in self:
            if record.destination_port_id and not record.destination_city:
                record.destination_city = record.destination_port_id.city

    @api.onchange("carrier_partner_id")
    def _onchange_carrier_partner_id(self):
        """Même miroir pour le nom du transporteur."""
        for record in self:
            if record.carrier_partner_id and not record._dally_champ_transporteur_texte():
                record._dally_ecrire_transporteur_texte(
                    record.carrier_partner_id.name)

    def _dally_champ_transporteur_texte(self):
        """Valeur du champ texte historique, ou None s'il n'existe pas ici."""
        return getattr(self, "carrier_name", None) if "carrier_name" in self._fields else None

    def _dally_ecrire_transporteur_texte(self, valeur):
        if "carrier_name" in self._fields:
            self.carrier_name = valeur

    # ------------------------------------------------------------------
    # Le ménage, à l'écriture — pas seulement à l'écran
    # ------------------------------------------------------------------

    def _dally_menage_de_mode(self):
        """Champs à vider parce qu'ils ne veulent plus rien dire.

        Deux familles : les intervenants propres à un mode (navire, compagnie
        aérienne, transporteur), et les lieux dont le drapeau ne correspond plus
        — un port maritime sur une expédition devenue aérienne désignerait un
        quai où aucun avion ne se pose.

        Ce ménage est fait à l'écriture et non dans un `onchange`, parce qu'un
        `onchange` ne protège que la saisie à l'écran. Une écriture par RPC, un
        import ou le provisionnement automatique passeraient à côté, et
        laisseraient un enregistrement qui se contredit lui-même.
        """
        self.ensure_one()
        transport = self._dally_transport()
        menage = {}
        for champ in CHAMPS_PAR_TRANSPORT.get(transport, ()):
            if self[champ]:
                menage[champ] = False
        if transport:
            for champ in ("origin_port_id", "destination_port_id"):
                lieu = self[champ]
                if lieu and not lieu[transport]:
                    menage[champ] = False
            route = self.frequent_route_id
            if route and not (route.source_location_id[transport]
                              and route.destination_location_id[transport]):
                menage["frequent_route_id"] = False
        return menage

    def write(self, vals):
        declencheurs = self._dally_champs_declencheurs()
        if not declencheurs & set(vals) or self.env.context.get("dally_menage_en_cours"):
            return super().write(vals)

        avant = {record.id: record._dally_transport() for record in self}
        resultat = super().write(vals)
        for record in self:
            if record._dally_transport() == avant.get(record.id):
                continue
            menage = record._dally_menage_de_mode()
            if menage:
                super(DallyFreightRoutingMixin,
                      record.with_context(dally_menage_en_cours=True)).write(menage)
        return resultat
