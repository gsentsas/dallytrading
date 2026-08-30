# -*- coding: utf-8 -*-
"""Le reçu client : son contrat et son PDF.

Deux routes, aucun `sudo`, aucune clé d'API. Le dossier est désigné par sa
référence publique — jamais par un identifiant interne — et la session de
l'opérateur porte tous les droits appliqués.

Le PDF n'est pas servi par une adresse publique devinable : il passe par la
même session que le reste. Un reçu client mis à disposition sans contrôle
serait lisible par quiconque devine une référence de dossier.

L'adresse se termine par `/receipt/pdf` et non `/receipt.pdf` : le nom du
fichier téléchargé est porté par `Content-Disposition`, tandis qu'un point dans
le chemin obligerait à élargir la liste blanche de ressources du BFF — une
grammaire d'URL relâchée pour un agrément d'affichage.
"""

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError

from .ops_base import DallyOpsController


class DallyOpsReceiptsController(DallyOpsController):

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/receipt",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_receipt(self, reference, **kwargs):
        """Le contrat du reçu — celui dont l'aperçu et le PDF sont tirés."""
        return self._servir_recu(
            lambda service: service.receipt_dto(reference),
            "ops/intakes/receipt",
        )

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/receipt/pdf",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_receipt_pdf(self, reference, **kwargs):
        """Le reçu en PDF, rendu par le moteur natif d'Odoo."""
        if not self._a_un_role_ops():
            return self._refus_ops("ops/intakes/receipt/pdf")
        try:
            document = request.env[
                "dally.ops.receipt.service"].receipt_pdf(reference)
        except DallyOpsError as erreur:
            return self._erreur(erreur.code, str(erreur), erreur.status)
        except AccessError:
            return self._refus_ops("ops/intakes/receipt/pdf")

        return request.make_response(
            document["content"],
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", str(len(document["content"]))),
                # `attachment` : un reçu client se télécharge, il ne s'ouvre
                # pas dans le contexte de l'application.
                ("Content-Disposition",
                 'attachment; filename="%s"' % document["filename"]),
                # Aucun intermédiaire ne doit conserver le reçu d'un client :
                # un proxy partagé le servirait au suivant.
                ("Cache-Control", "private, no-store, max-age=0"),
                ("X-Content-Type-Options", "nosniff"),
                ("Referrer-Policy", "no-referrer"),
            ],
        )

    def _servir_recu(self, operation, route):
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            data = operation(request.env["dally.ops.receipt.service"])
        except DallyOpsError as erreur:
            return self._erreur(erreur.code, str(erreur), erreur.status)
        except AccessError:
            return self._refus_ops(route)
        return self._json({"success": True, "data": data})

    @classmethod
    def _erreur(cls, code, message, status):
        return cls._json(
            {"success": False, "error": {"code": code, "message": message}},
            status=status,
        )
