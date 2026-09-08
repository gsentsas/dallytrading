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

import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


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

    #: Un maître ne sert qu'une consolidation.
    #:
    #: C'est la seule chose que cette contrainte garantit, et il faut la lire
    #: pour ce qu'elle est : elle empêche **deux consolidations** de pointer sur
    #: la même expédition — un rattachement croisé par écran, par import ou par
    #: copie.
    #:
    #: Elle ne protège pas de deux créations concurrentes sur la **même**
    #: consolidation : chacune produirait sa propre expédition, les deux clés
    #: seraient distinctes, et rien ne s'y opposerait. Ce cas-là est tenu par le
    #: verrou de ligne pris dans `action_create_master_shipment`, qui sérialise
    #: les deux appels et fait relire le rattachement au second.
    _tk_master_shipment_unique = models.Constraint(
        "UNIQUE (tk_master_shipment_id)",
        "Cette expédition maître est déjà rattachée à une consolidation.",
    )

    @api.constrains("tk_master_shipment_id", "company_id")
    def _check_tk_master_shipment(self):
        """Le maître rattaché est bien un maître, et de la même société.

        La contrainte d'unicité vit en base ; celle-ci ne le peut pas, elle
        traverse deux tables. Elle vaut pourtant autant : un rattachement vers
        une expédition « house » ferait porter la consolidation par un dossier
        client, et un rattachement inter-sociétés ferait voyager une
        consolidation sous l'entité d'une autre — deux erreurs qu'un écran ou un
        import peuvent commettre sans bruit.
        """
        for record in self:
            maitre = record.sudo().tk_master_shipment_id
            if not maitre:
                continue
            if maitre.operation != "master":
                raise ValidationError(_(
                    "L'expédition %(reference)s n'est pas une expédition maître "
                    "(type « %(type)s ») : une consolidation ne peut pas s'y "
                    "rattacher.",
                    reference=maitre.display_name, type=maitre.operation or "—",
                ))
            if maitre.company_id and record.company_id and maitre.company_id != record.company_id:
                raise ValidationError(_(
                    "L'expédition maître appartient à %(maitre)s et la "
                    "consolidation à %(consolidation)s.",
                    maitre=maitre.company_id.display_name,
                    consolidation=record.company_id.display_name,
                ))

    @api.depends("tk_master_shipment_id")
    def _compute_tk_master_shipment_count(self):
        for record in self:
            record.tk_master_shipment_count = 1 if record.tk_master_shipment_id else 0

    # ------------------------------------------------------------------
    # La résolution des ports
    # ------------------------------------------------------------------

    @staticmethod
    def _dally_code_iata(texte):
        """Le code à trois lettres contenu dans un libellé, s'il n'y en a qu'un.

        Les libellés de terrain mêlent le nom et le code : « AIBD-DSS »,
        « Roissy CDG ». L'extraction découpe sur tout ce qui n'est pas
        alphanumérique et ne retient que les jetons de **exactement trois
        lettres**. C'est déterministe et sans jokers : « AIBD » fait quatre
        lettres, « Roissy » six.

        Deux codes dans le même libellé — « LEH BKO » — ne donnent rien : on ne
        choisit pas lequel est l'origine. C'est le fail-closed, appliqué à
        l'extraction elle-même.
        """
        jetons = re.findall(r"[A-Za-z0-9]+", texte or "")
        codes = {jeton.upper() for jeton in jetons
                 if len(jeton) == 3 and jeton.isalpha()}
        return codes.pop() if len(codes) == 1 else None

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

        # Du plus précis au moins précis : un code vaut mieux qu'un nom, et un
        # nom mieux qu'une ville. Le code extrait passe juste après le libellé
        # brut — « DSS » se résout tel quel, « AIBD-DSS » par extraction.
        tentatives = []
        if libelle:
            tentatives.append(("code", libelle.strip()))
            extrait = self._dally_code_iata(libelle)
            if extrait and extrait != libelle.strip().upper():
                tentatives.append(("code", extrait))
            tentatives.append(("name", libelle.strip()))
        if ville:
            extrait_ville = self._dally_code_iata(ville)
            if extrait_ville:
                tentatives.append(("code", extrait_ville))
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
        # Un poids sans nombre de pièces ne se complète pas d'un « 1 » de
        # confort : le maître déclarerait une pièce que personne n'a comptée, et
        # le poids s'y trouverait attaché. On refuse et on dit quoi saisir.
        if self.master_piece_count <= 0:
            raise UserError(_(
                "Un poids brut maître est déclaré (%(poids)s kg) sans nombre de "
                "pièces. Renseignez les pièces MAWB avant de créer l'expédition "
                "maître : le document ne peut pas déclarer un poids sans colis.",
                poids=self.master_gross_weight_kg,
            ))
        return {
            "name": self.name,
            "package_type": "item",
            "transport": MODE_TO_TRANSPORT[self.transport_mode],
            "qty": self.master_piece_count,
            "gross_weight": self.master_gross_weight_kg or 0.0,
            "volume": self.client_volume_cbm or 0.0,
        }

    # ------------------------------------------------------------------
    # Les gestes
    # ------------------------------------------------------------------

    def action_create_master_shipment(self):
        """Crée l'expédition maître, une seule fois.

        ## L'ordre compte, et il est celui-ci

        Verrou, relecture, revalidation, création. Pas un autre.

        Une version précédente validait avant de verrouiller, au motif qu'une
        validation ne lit que des champs et qu'échouer verrou en main ferait
        attendre l'autre transaction pour rien. C'était un raisonnement de
        confort qui ouvrait une fenêtre : entre la lecture des champs et
        l'obtention du verrou, une autre transaction peut clôturer la collecte,
        changer le mode, la route, le poids déclaré — et le maître se créait
        alors avec des valeurs déjà périmées, sur un dossier qui n'était plus
        dans l'état vérifié.

        Le verrou ne protège que ce qui est lu **après** lui. Tout ce qui décide
        est donc relu après, sur des données fraîches : l'invalidation force la
        relecture en base plutôt que dans le cache de la transaction, qui porte
        encore les valeurs d'avant.
        """
        self.ensure_one()
        # Sortie de courtoisie, sans garantie : elle évite un verrou inutile sur
        # le cas courant du double clic. La vraie décision se prend après.
        if self.tk_master_shipment_id:
            return self.action_open_master_shipment()

        # Le verrou. `UNIQUE (tk_master_shipment_id)` empêche deux
        # consolidations de partager un maître ; elle ne fait rien contre deux
        # créations sur la MÊME consolidation, qui produiraient deux expéditions
        # distinctes dont l'une resterait orpheline.
        self.env.cr.execute(
            "SELECT id FROM dally_freight_consolidation WHERE id = %s FOR UPDATE",
            [self.id],
        )
        if not self.env.cr.fetchone():
            raise UserError(_("Cette consolidation n'existe plus."))

        # Tout ce qui a été lu avant le verrou est suspect : on repart de la
        # base. `invalidate_recordset()` sans argument vide le cache de tous les
        # champs — état, mode, direction, route, poids, pièces et rattachement.
        self.invalidate_recordset()

        if self.tk_master_shipment_id:
            return self.action_open_master_shipment()

        if self.state not in STATES_ALLOWING_MASTER:
            raise UserError(_(
                "L'expédition maître se crée avant le départ. Cette consolidation "
                "est à l'état « %s ».",
                dict(self._fields["state"].selection).get(self.state, self.state),
            ))

        # Revalidation sur les valeurs fraîches, et toujours avant la moindre
        # écriture : un refus ne doit laisser aucune expédition derrière lui.
        vals = self._dally_master_shipment_values()
        ligne_colis = self._dally_master_package_values()

        expedition = self.env["freight.shipment"].create(vals)

        if ligne_colis:
            self.env["shipment.package.line"].create(
                dict(ligne_colis, shipment_id=expedition.id))

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
