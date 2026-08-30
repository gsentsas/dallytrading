# -*- coding: utf-8 -*-
"""GET /api/v1/ops/consolidations — sur quel départ enregistrer ce colis ?

## Pourquoi pas ``/api/v1/freight/consolidations/open``

La route existe déjà et calcule presque la même chose. Elle ne convient pas :
elle s'authentifie par clé d'API, exige la portée ``freight:write`` et le
groupe technique du connecteur tableur. La brancher ici obligerait à poser une
clé privilégiée dans l'application terrain — exactement ce que l'étape
précédente a rendu structurellement impossible.

On reprend donc la **logique** et le **modèle**, pas le point d'entrée HTTP.

## Ce que ce contrôleur fait, et ce qu'il ne fait pas

Il authentifie, appelle le service, sérialise. Il ne connaît ni le modèle
``dally.freight.consolidation``, ni son domaine, ni ``sudo``. Le privilège vit
dans ``dally.ops.consolidation.service`` et nulle part ailleurs : c'est ce qui
permet d'en écrire la portée en une phrase et de la vérifier par un test.

Aucun paramètre de requête n'est lu. Ni société, ni état, ni domaine, ni tri :
le navigateur ne peut pas élargir la recherche parce qu'il n'a rien à dire.
"""

from odoo import http

from .ops_base import DallyOpsController


class DallyOpsConsolidationsController(DallyOpsController):

    @http.route(
        "/api/v1/ops/consolidations",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_consolidations(self, **kwargs):
        """Les départs encore ouverts à la réception.

        ``kwargs`` est accepté par la signature mais jamais lu : Odoo passe la
        requête telle quelle, et ignorer explicitement son contenu vaut mieux
        que de refuser une requête à laquelle un proxy aurait ajouté un
        paramètre de traçage.
        """
        if not self._a_un_role_ops():
            return self._refus_ops("ops/consolidations")

        consolidations = http.request.env[
            "dally.ops.consolidation.service"
        ].list_open_for_intake()
        return self._json({"success": True, "data": {"consolidations": consolidations}})
