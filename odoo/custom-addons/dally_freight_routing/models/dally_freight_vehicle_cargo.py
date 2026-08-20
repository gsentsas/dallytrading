# -*- coding: utf-8 -*-
"""La cargaison véhicule, qui porte le mode que le service ne dit pas.

## Pourquoi ce fichier existe

Le mode d'un transport de véhicule ne se lit ni sur le service — « transport de
véhicule » ne dit pas si la voiture part par bateau ou par camion — ni sur la
demande, mais sur la cargaison elle-même. Or c'est la demande qui porte le port
d'embarquement.

La demande ne peut pas surveiller ce changement toute seule :
`vehicle_cargo_id` y est un champ **calculé**, il n'apparaît donc jamais dans
les valeurs d'une écriture, et le nettoyage par mode ne se déclenchait pas.
Mesuré : une demande véhicule avec un port maritime gardait ce port après que
la cargaison soit passée en routier.

C'est donc la cargaison qui prévient — elle sait, elle, quand son mode change.

## Ce que ça ne fait pas

Le port n'est pas *deviné* à partir du mode : il est seulement **retiré** quand
il devient contradictoire. Tant que le mode est inconnu, un port déclaré est
conservé tel quel ; rien n'est inventé, et rien n'est effacé sans raison.
"""

from odoo import api, models


class DallyFreightVehicleCargo(models.Model):
    # `_name` explicite : un `_inherit` sans lui créerait un modèle fantôme.
    _name = "dally.freight.vehicle.cargo"
    _inherit = "dally.freight.vehicle.cargo"

    @api.model_create_multi
    def create(self, vals_list):
        cargaisons = super().create(vals_list)
        cargaisons._dally_repercuter_le_mode()
        return cargaisons

    def write(self, vals):
        resultat = super().write(vals)
        if {"transport_mode", "quote_request_id"} & set(vals):
            self._dally_repercuter_le_mode()
        return resultat

    def _dally_repercuter_le_mode(self):
        """Retire de la demande ce que le mode de la cargaison rend faux."""
        for cargaison in self:
            devis = cargaison.quote_request_id
            if not devis:
                continue
            menage = devis._dally_menage_de_mode()
            if menage:
                devis.write(menage)
