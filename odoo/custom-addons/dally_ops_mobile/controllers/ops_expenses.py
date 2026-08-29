# -*- coding: utf-8 -*-
"""Les dépenses engagées sur un départ.

Quatre routes, aucun `sudo`, aucune clé d'API. Le privilège vit dans le
service ; le contrôleur lit la requête, appelle, met en forme.

La route du justificatif est la seule de Dally Ops à recevoir autre chose que
du JSON. Elle reçoit un `multipart/form-data`, parce qu'une photo envoyée en
base64 dans un corps JSON pèse un tiers de plus et doit être entièrement
reconstruite en mémoire avant d'être écrite. Sur un téléphone au bord du
réseau, ce tiers se paie.
"""

import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError
from odoo.addons.dally_ops_mobile.models.ops_expense_service import TAILLE_MAXIMALE

from .ops_base import DallyOpsController

#: Le champ de formulaire qui porte le fichier.
CHAMP_FICHIER = "receipt"

#: L'enveloppe multipart et le champ `request_uuid` pèsent quelques
#: centaines d'octets ; on laisse large plutôt que de refuser un fichier
#: de dix mébioctets pile à cause de son emballage. La mesure qui fait foi
#: reste celle des octets reçus, dans le service.
MARGE_MULTIPART = 64 * 1024


class DallyOpsExpensesController(DallyOpsController):

    @http.route(
        "/api/v1/ops/expense-consolidations",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_expense_consolidations(self, **kwargs):
        """Les départs sur lesquels une dépense peut être imputée.

        Distincte de `ops/consolidations` : une dépense se paie encore après le
        départ et jusqu'à l'arrivée, alors qu'un colis ne se reçoit que pendant
        la collecte. Servir la même liste aux deux écrans forcerait l'un des
        deux à mentir.
        """
        return self._servir(
            lambda: {"consolidations": request.env[
                "dally.ops.expense.service"].list_expense_consolidations()},
            "ops/expense-consolidations",
        )

    @http.route(
        "/api/v1/ops/expenses",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_expense_record(self, **kwargs):
        """Enregistre une dépense de terrain."""
        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._erreur("invalid_request", _("Corps de requête illisible."), 400)
        return self._servir(
            lambda: request.env["dally.ops.expense.service"].record_expense(corps),
            "ops/expenses",
        )

    @http.route(
        "/api/v1/ops/consolidations/<string:reference>/expenses",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_expense_list(self, reference, **kwargs):
        """Les dépenses déjà enregistrées sur un départ."""
        return self._servir(
            lambda: request.env["dally.ops.expense.service"].list_expenses(reference),
            "ops/consolidations/expenses",
        )

    @http.route(
        "/api/v1/ops/expenses/<string:reference>/receipt",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_expense_receipt(self, reference, **kwargs):
        """Joint la photo du justificatif à une dépense déjà enregistrée.

        La dépense existe déjà quand on arrive ici : c'est ce qui permet à un
        envoi de photo d'échouer sans emporter l'argent avec lui.
        """
        # On refuse sur l'annonce de taille avant de lire quoi que ce soit :
        # inutile de laisser dix mégaoctets de trop traverser le processus pour
        # les rejeter ensuite.
        longueur = request.httprequest.content_length or 0
        if longueur > TAILLE_MAXIMALE + MARGE_MULTIPART:
            return self._erreur(
                "receipt_too_large",
                _("Le justificatif dépasse la taille autorisée."),
                422,
            )

        fichier = request.httprequest.files.get(CHAMP_FICHIER)
        if fichier is None:
            return self._erreur(
                "receipt_missing", _("Aucun justificatif reçu."), 422)
        request_uuid = request.httprequest.form.get("request_uuid")
        contenu = fichier.read(TAILLE_MAXIMALE + 1)

        return self._servir(
            lambda: request.env["dally.ops.expense.service"].attach_receipt(
                reference, request_uuid, fichier.filename, contenu),
            "ops/expenses/receipt",
        )

    def _servir(self, operation, route):
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            return self._json({"success": True, "data": operation()})
        except DallyOpsError as erreur:
            return self._erreur(erreur.code, str(erreur), erreur.status)
        except AccessError:
            return self._refus_ops(route)

    @classmethod
    def _erreur(cls, code, message, status):
        return cls._json(
            {"success": False, "error": {"code": code, "message": message}},
            status=status,
        )
