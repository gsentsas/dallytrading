# -*- coding: utf-8 -*-
"""L'identité par laquelle le terrain désigne un colis, et elle seule.

## Pourquoi un champ de plus alors que le colis est déjà unique

Le colis possède deux identifiants uniques, et aucun des deux n'est
publiable.

`id` est la clé PostgreSQL : la publier apprendrait au navigateur à compter
les colis de la société et à en deviner d'autres.

`external_line_key` porte une contrainte d'unicité, mais c'est une **clé
d'idempotence** de la synchronisation, et sa valeur décrit la structure
interne : `ops:<clé source>:line:<uuid de ligne>` côté natif,
`<consolidation>|<réf locale>|A|<n>` côté repris. La publier livrerait la
référence d'un départ, le numéro local d'un dossier, et l'uuid de gestes
d'idempotence encore actifs.

`line_uuid` — le suffixe natif — conviendrait aux dossiers nés de Dally Ops,
mais les dossiers repris n'en ont pas. Or le chargement les couvre.

D'où cette identité : tirée au hasard, sans rapport avec les données, valable
pour tout colis quelle que soit son origine.

## Ce qu'elle n'est pas

Ni une référence métier — elle ne s'imprime pas, ne se dicte pas au
téléphone, ne figure sur aucune étiquette. Ni un secret : la connaître ne
donne aucun droit, le service revérifie la société, le départ prévu et
l'état à chaque geste.
"""

import uuid

from odoo import api, fields, models


class DallyShipmentPackage(models.Model):
    _name = "dally.shipment.package"
    _inherit = "dally.shipment.package"

    ops_loading_uuid = fields.Char(
        string="Identité de chargement",
        index=True,
        copy=False,
        readonly=True,
        help="Identifiant opaque par lequel Dally Ops désigne ce colis. "
             "Tiré au hasard : il ne dérive d'aucun identifiant technique et "
             "ne décrit aucune donnée métier.",
    )

    _ops_loading_uuid_unique = models.Constraint(
        "UNIQUE(ops_loading_uuid)",
        "L'identité de chargement doit être unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Attribuée à la création, jamais par l'appelant : un colis dont on
        # choisirait l'identité serait un colis dont on peut deviner celle des
        # autres.
        for vals in vals_list:
            vals["ops_loading_uuid"] = str(uuid.uuid4())
        return super().create(vals_list)
