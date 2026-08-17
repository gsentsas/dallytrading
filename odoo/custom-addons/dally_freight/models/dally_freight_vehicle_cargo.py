# -*- coding: utf-8 -*-
"""
Le véhicule d'un client, transporté **comme marchandise**.

## Pourquoi ce n'est pas `fleet.vehicle`

`fleet.vehicle` décrit un véhicule que l'entreprise *utilise* : sa flotte, ses
contrats d'entretien, ses chauffeurs, ses coûts kilométriques. La voiture qu'un
client nous confie n'est rien de tout cela — c'est du fret, avec une origine,
une destination, un mode de transport et un prix au dossier.

Détourner `fleet.vehicle` pour la représenter mélangerait deux comptabilités qui
n'ont pas la même nature : le camion qui transporte et la voiture transportée
finiraient dans la même table, et le jour où DallyTrading acquiert son propre
porte-voitures, plus personne ne saurait distinguer l'un de l'autre.

## Le service commercial n'est pas le mode physique

C'est la distinction structurante de ce modèle, et elle est facile à manquer.

`freight_vehicle` répond à la question « qu'est-ce que le client achète ? ». Il
ne dit **rien** de la façon dont la voiture voyage. Une voiture Paris → Dakar
part par bateau ; la même voiture Dakar → Bamako part par camion. Traduire
mécaniquement « véhicule » par « routier » produirait une expédition maritime
étiquetée routière — fausse pour le client, fausse pour l'exploitation, et
silencieusement.

`transport_mode` porte donc le mode physique, en valeurs closes, et il est
**obligatoire**. Il n'existe aucune valeur par défaut : un dossier dont le mode
n'est pas su est un dossier qu'on ne provisionne pas.
"""

import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

#: Catégories de véhicule. Ferment la liste : « autre » existe, mais le texte
#: libre non — c'est sur ces catégories que la tarification s'appuiera.
VEHICLE_CATEGORIES = [
    ("car", "Voiture"),
    ("suv", "SUV / 4x4"),
    ("van", "Utilitaire"),
    ("motorcycle", "Moto"),
    ("truck", "Camion"),
    ("other", "Autre"),
]

#: État du véhicule à la prise en charge.
#:
#: À ne pas confondre avec l'état de l'expédition : un véhicule non roulant
#: voyage très bien, il change seulement la manière de le charger — et le prix.
VEHICLE_CONDITIONS = [
    ("running", "Roulant"),
    ("non_running", "Non roulant"),
]

VEHICLE_FUELS = [
    ("petrol", "Essence"),
    ("diesel", "Diesel"),
    ("hybrid", "Hybride"),
    ("electric", "Électrique"),
    ("other", "Autre"),
]

#: Modes physiques provisionnables aujourd'hui.
#:
#: `multimodal` n'y figure pas volontairement : il demanderait de décrire une
#: succession de segments, donc un modèle de segments. Tant que ce modèle
#: n'existe pas, l'annoncer serait une promesse que le provisionnement ne sait
#: pas tenir.
VEHICLE_TRANSPORT_MODES = [
    ("sea", "Maritime"),
    ("road", "Routier"),
]

#: Le VIN moderne fait 17 caractères sans I, O ni Q. On borne large : les
#: véhicules d'avant 1981 et certains marchés portent des numéros de châssis
#: plus courts, et refuser un dossier légitime pour cette raison serait un défaut
#: bien plus coûteux que d'accepter un numéro atypique.
VIN_MAX_LENGTH = 32
_VIN_ALLOWED = re.compile(r"^[A-Z0-9-]+$")
_UNSAFE_TEXT = re.compile(r"[\x00-\x1f\x7f<>]")


class DallyQuoteRequest(models.Model):
    """Relation inverse vers le véhicule décrit par la demande."""

    _name = "dally.quote.request"
    _inherit = "dally.quote.request"

    vehicle_cargo_id = fields.Many2one(
        comodel_name="dally.freight.vehicle.cargo",
        string="Véhicule",
        compute="_compute_vehicle_cargo_id",
        help="Véhicule décrit par cette demande, pour les services de transport "
             "de véhicule.",
    )

    def _compute_vehicle_cargo_id(self):
        """Calculé plutôt que stocké : une seule clé étrangère, pas deux.

        `dally.freight.vehicle.cargo.quote_request_id` porte déjà la relation,
        avec un index unique. Stocker l'inverse ajouterait une deuxième écriture
        à tenir d'accord avec la première — et c'est exactement ce que la
        contrainte d'unicité rend inutile.
        """
        cargos = self.env["dally.freight.vehicle.cargo"].sudo().search(
            [("quote_request_id", "in", self.ids)]
        )
        par_devis = {cargo.quote_request_id.id: cargo for cargo in cargos}
        for devis in self:
            devis.vehicle_cargo_id = par_devis.get(devis.id, False)


class DallyFreightVehicleCargo(models.Model):
    """Un véhicule confié au transport. Marchandise, jamais moyen de transport."""

    _name = "dally.freight.vehicle.cargo"
    _description = "DallyTrading Vehicle Cargo"
    _order = "id desc"
    _rec_name = "display_name"

    # ------------------------------------------------------------------
    # Rattachements
    # ------------------------------------------------------------------

    quote_request_id = fields.Many2one(
        comodel_name="dally.quote.request",
        string="Demande de devis",
        required=True,
        ondelete="cascade",
        index=True,
        help="Demande commerciale à l'origine de ce transport de véhicule.",
    )
    # `cascade` ici, contrairement au lien booking→devis du pont : ce véhicule
    # n'existe QUE pour décrire une demande. Sans elle, il n'a plus de sens et
    # ne correspond à aucune opération physique.

    shipment_id = fields.Many2one(
        comodel_name="dally.shipment",
        string="Expédition",
        ondelete="set null",
        index=True,
        copy=False,
        help="Expédition qui transporte ce véhicule, une fois le devis accepté. "
             "Vide tant que le dossier n'est pas provisionné.",
    )
    # `set null` : perdre l'expédition ne doit pas effacer la description du
    # véhicule, qui reste la trace de ce que le client a demandé.

    company_id = fields.Many2one(
        related="quote_request_id.company_id",
        store=True,
        index=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related="quote_request_id.partner_id",
        store=True,
        index=True,
        readonly=True,
        string="Client",
    )

    # ------------------------------------------------------------------
    # Identité du véhicule
    # ------------------------------------------------------------------

    vin = fields.Char(
        string="VIN / Numéro de châssis",
        size=VIN_MAX_LENGTH,
        index=True,
        help="Facultatif : tous les véhicules n'en portent pas un lisible.",
    )
    make = fields.Char(string="Marque", required=True)
    model = fields.Char(string="Modèle", required=True)
    year = fields.Char(string="Année", size=10)
    registration = fields.Char(string="Immatriculation", size=32)
    color = fields.Char(string="Couleur", size=32)

    category = fields.Selection(
        selection=VEHICLE_CATEGORIES,
        string="Type de véhicule",
        required=True,
        default="car",
    )
    condition = fields.Selection(
        selection=VEHICLE_CONDITIONS,
        string="État",
        required=True,
        default="running",
        help="Un véhicule non roulant demande un treuil ou un plateau : c'est "
             "une contrainte de chargement, pas un défaut de l'expédition.",
    )
    fuel = fields.Selection(selection=VEHICLE_FUELS, string="Motorisation")
    key_count = fields.Integer(
        string="Nombre de clés",
        default=1,
        help="Compté à la prise en charge et à la livraison : c'est le litige "
             "le plus fréquent sur ce type de transport.",
    )

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    transport_mode = fields.Selection(
        selection=VEHICLE_TRANSPORT_MODES,
        string="Mode de transport",
        required=True,
        help="Comment le véhicule voyage physiquement. Indépendant du service "
             "commercial : un transport de véhicule peut être maritime ou "
             "routier, et rien dans « transport de véhicule » ne le dit.",
    )

    pickup_requested = fields.Boolean(string="Enlèvement demandé")
    pickup_address = fields.Text(string="Adresse d'enlèvement")
    delivery_requested = fields.Boolean(string="Livraison demandée")
    delivery_address = fields.Text(string="Adresse de livraison")

    customer_notes = fields.Text(
        string="Précisions du client",
        help="Saisi par le client. Nettoyé et borné : voir _check_texts.",
    )

    # ------------------------------------------------------------------
    # Interne — jamais projeté vers le client
    # ------------------------------------------------------------------

    internal_notes = fields.Text(
        string="Notes internes",
        groups="dally_core.group_dally_readonly",
        help="Réservé au personnel. Le champ n'est pas seulement masqué : "
             "l'ORM ne le charge pas pour un utilisateur portail.",
    )
    purchase_price = fields.Monetary(
        string="Valeur d'achat déclarée",
        currency_field="currency_id",
        groups="dally_core.group_dally_readonly",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------

    display_name = fields.Char(compute="_compute_display_name", store=False)

    @api.depends("make", "model", "year", "registration")
    def _compute_display_name(self):
        for cargo in self:
            morceaux = [cargo.make or "", cargo.model or ""]
            if cargo.year:
                morceaux.append(f"({cargo.year})")
            if cargo.registration:
                morceaux.append(f"— {cargo.registration}")
            cargo.display_name = " ".join(p for p in morceaux if p).strip() or _("Véhicule")

    # ------------------------------------------------------------------
    # Contraintes
    # ------------------------------------------------------------------

    _one_cargo_per_quote = models.Constraint(
        "UNIQUE (quote_request_id)",
        "Cette demande de devis décrit déjà un véhicule.",
    )
    # Un véhicule par demande, pour le MVP. La contrainte est en base et non
    # applicative : c'est elle qui tient sous deux soumissions concurrentes du
    # formulaire public, là où un `search` suivi d'un `create` laisserait passer
    # un doublon.

    @api.constrains("vin")
    def _check_vin(self):
        """Le VIN, s'il est fourni, doit être plausible — pas conforme à 2024.

        Deux erreurs opposées sont possibles ici, et la plus coûteuse n'est pas
        celle qu'on croit. Refuser un VIN de 15 caractères bloque un dossier
        légitime — véhicule ancien, marché particulier — et le client abandonne.
        Accepter n'importe quoi laisse passer du HTML dans un champ réaffiché.

        On refuse donc ce qui est manifestement dangereux ou absurde, et on
        accepte le reste.
        """
        for cargo in self:
            if not cargo.vin:
                continue
            vin = cargo.vin.strip().upper()
            if len(vin) < 5:
                raise ValidationError(
                    _("Le numéro de châssis « %s » est trop court pour être "
                      "exploitable.") % cargo.vin
                )
            if not _VIN_ALLOWED.match(vin):
                raise ValidationError(
                    _("Le numéro de châssis ne peut contenir que des lettres, "
                      "des chiffres et des tirets.")
                )

    @api.constrains("customer_notes", "pickup_address", "delivery_address",
                    "make", "model", "registration", "color")
    def _check_texts(self):
        """Refuse balises et caractères de contrôle dans les champs réaffichés.

        Ces valeurs reviennent dans l'espace client et dans des documents. Le
        rendu échappe déjà, mais une donnée propre en base vaut mieux qu'une
        donnée dangereuse correctement échappée à chaque usage : il suffit d'un
        endroit qui oublie.
        """
        for cargo in self:
            for champ in ("customer_notes", "pickup_address", "delivery_address",
                          "make", "model", "registration", "color"):
                valeur = cargo[champ]
                if valeur and _UNSAFE_TEXT.search(valeur):
                    raise ValidationError(
                        _("Le champ « %s » contient des caractères non autorisés.")
                        % cargo._fields[champ].string
                    )

    @api.constrains("pickup_requested", "pickup_address",
                    "delivery_requested", "delivery_address")
    def _check_addresses(self):
        """Une prestation demandée sans adresse n'est pas exécutable."""
        for cargo in self:
            if cargo.pickup_requested and not (cargo.pickup_address or "").strip():
                raise ValidationError(
                    _("Un enlèvement est demandé sans adresse d'enlèvement.")
                )
            if cargo.delivery_requested and not (cargo.delivery_address or "").strip():
                raise ValidationError(
                    _("Une livraison est demandée sans adresse de livraison.")
                )

    @api.constrains("key_count")
    def _check_key_count(self):
        for cargo in self:
            if cargo.key_count < 0 or cargo.key_count > 10:
                raise ValidationError(
                    _("Le nombre de clés doit être compris entre 0 et 10.")
                )

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._dally_normalise(vals)
        cargos = super().create(vals_list)
        cargos._dally_mirror_to_quote()
        return cargos

    def write(self, vals):
        self._dally_normalise(vals)
        resultat = super().write(vals)
        if {"make", "model", "year", "quote_request_id"} & set(vals):
            self._dally_mirror_to_quote()
        return resultat

    def _dally_mirror_to_quote(self):
        """Recopie marque, modèle et année sur la demande de devis.

        ## Pourquoi un miroir plutôt qu'une suppression

        `dally.quote.request` porte `vehicle_make`, `vehicle_model` et
        `vehicle_year` depuis l'origine. Trois consommateurs en dépendent : le
        formulaire back-office, le résumé calculé du dossier, et l'API publique.
        Les retirer casserait ces trois-là pour un gain nul.

        Mais deux sources de vérité qui décrivent la même voiture finissent
        toujours par diverger — quelqu'un corrige d'un côté, pas de l'autre, et
        plus personne ne sait laquelle croire.

        Le miroir est donc **à sens unique et sans exception** : le cargo écrit
        vers le devis, jamais l'inverse. Le provisionnement, lui, ne lit que le
        cargo. `_check_pas_de_divergence` interdit qu'un écart s'installe.
        """
        for cargo in self:
            devis = cargo.quote_request_id
            if not devis:
                continue
            attendu = {
                "vehicle_make": cargo.make or False,
                "vehicle_model": cargo.model or False,
                "vehicle_year": cargo.year or False,
            }
            actuel = {champ: devis[champ] or False for champ in attendu}
            if actuel != attendu:
                devis.sudo().write(attendu)

    # Il n'y a **pas** de contrainte interdisant au devis de diverger du
    # véhicule, et c'est un choix, pas un oubli.
    #
    # Une première version en posait une. Elle se déclenchait pendant `create`,
    # avant que le miroir n'ait pu s'exécuter : le devis avait encore ses champs
    # vides quand le véhicule portait déjà sa marque, et toute création
    # échouait. La corriger aurait demandé de lutter contre l'ordre
    # d'évaluation de l'ORM pour un gain douteux.
    #
    # Ce qui protège réellement est ailleurs, et c'est plus solide : le
    # provisionnement ne lit **que** le véhicule. Un écart introduit par une
    # écriture directe sur le devis n'a donc aucun effet sur l'expédition
    # produite — il est cosmétique, et la prochaine écriture sur le véhicule le
    # résorbe. `test_le_provisioning_ignore_les_champs_historiques` le prouve.

    @staticmethod
    def _dally_normalise(vals):
        """Met le VIN en majuscules et retire les espaces superflus.

        Fait ici plutôt que dans le formulaire : un VIN arrive aussi par l'API
        et par un import, et une normalisation qui ne vit que dans l'interface
        n'est pas une normalisation.
        """
        if vals.get("vin"):
            vals["vin"] = vals["vin"].strip().upper()
        for champ in ("make", "model", "registration", "color", "year"):
            if vals.get(champ):
                vals[champ] = vals[champ].strip()
