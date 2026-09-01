# -*- coding: utf-8 -*-
"""Les quatre routes des preuves photographiques.

Aucun `sudo` ici, aucune clé d'API : le privilège vit dans le service, derrière
le rôle Ops. Le dossier et la photo sont désignés par leurs références
publiques — jamais par un identifiant interne.

La route d'envoi est, avec le justificatif de caisse, la seule de Dally Ops à
recevoir autre chose que du JSON. Elle refuse sur l'annonce de taille avant de
lire quoi que ce soit : laisser traverser dix mégaoctets de trop pour les
rejeter ensuite reviendrait à financer l'attaque qu'on prétend arrêter.

Les octets d'une photo sont servis en `inline` — l'écran les affiche, il ne les
télécharge pas — mais jamais sans `nosniff` : c'est ce qui empêche un
navigateur de rendre en HTML un fichier qui a passé le contrôle de type.
"""

import json

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.dally_ops_mobile.models.ops_errors import DallyOpsError
from odoo.addons.dally_ops_mobile.models.ops_photo_service import MAX_FILE_BYTES

from .ops_base import DallyOpsController

CHAMP_FICHIER = "photo"

#: L'enveloppe multipart et les champs de formulaire pèsent quelques centaines
#: d'octets ; on laisse large plutôt que de refuser une photo de dix mébioctets
#: pile à cause de son emballage. La mesure qui fait foi reste celle des octets
#: reçus, dans le service.
MARGE_MULTIPART = 64 * 1024


class DallyOpsPhotosController(DallyOpsController):

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/photos",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_photos_list(self, reference, **kwargs):
        """Les preuves du dossier, sans leurs octets."""
        return self._servir_photo(
            lambda service: service.list_photos(reference),
            "ops/intakes/photos",
        )

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/photos",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def ops_photo_add(self, reference, **kwargs):
        """Joint une preuve au dossier."""
        longueur = request.httprequest.content_length or 0
        if longueur > MAX_FILE_BYTES + MARGE_MULTIPART:
            return self._erreur(
                "photo_too_large",
                _("La photo dépasse la taille autorisée."),
                422,
            )

        fichier = request.httprequest.files.get(CHAMP_FICHIER)
        if fichier is None:
            return self._erreur(
                "photo_missing", _("Aucune photo reçue."), 422)
        request_uuid = request.httprequest.form.get("request_uuid")
        kind = request.httprequest.form.get("kind")
        contenu = fichier.read(MAX_FILE_BYTES + 1)

        return self._servir_photo(
            lambda service: service.add_photo(
                reference, request_uuid, kind, fichier.filename, contenu),
            "ops/intakes/photos",
        )

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/photos/<string:photo_uuid>",
        type="http",
        auth="user",
        readonly=True,
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def ops_photo_read(self, reference, photo_uuid, **kwargs):
        """Les octets d'une preuve, sous la session de l'opérateur."""
        if not self._a_un_role_ops():
            return self._refus_ops("ops/intakes/photos/read")
        try:
            image = request.env["dally.ops.photo.service"].read_photo(
                reference, photo_uuid)
        except DallyOpsError as erreur:
            return self._erreur(erreur.code, str(erreur), erreur.status)
        except AccessError:
            return self._refus_ops("ops/intakes/photos/read")

        return request.make_response(
            image["content"],
            headers=[
                ("Content-Type", image["mime_type"]),
                ("Content-Length", str(len(image["content"]))),
                # `inline` : la photo s'affiche dans la fiche. Le nom du
                # fichier n'accompagne pas la réponse — il ne dit rien à
                # l'opérateur et voyagerait pour rien.
                ("Content-Disposition", "inline"),
                ("Cache-Control", "private, no-store, max-age=0"),
                # Sans cela, un navigateur pourrait rendre en HTML un fichier
                # dont le type a pourtant été validé sur ses octets.
                ("X-Content-Type-Options", "nosniff"),
                # Rien n'est exécuté depuis une preuve de terrain.
                ("Content-Security-Policy",
                 "default-src 'none'; img-src 'self' data:; sandbox"),
                ("Referrer-Policy", "no-referrer"),
            ],
        )

    @http.route(
        "/api/v1/ops/intakes/<string:reference>/photos/<string:photo_uuid>",
        type="http",
        auth="user",
        methods=["DELETE"],
        csrf=False,
        save_session=False,
    )
    def ops_photo_delete(self, reference, photo_uuid, **kwargs):
        """Retire une preuve de la vue. Les octets, eux, restent."""
        try:
            corps = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return self._erreur(
                "invalid_request", _("Corps de requête illisible."), 400)
        if not isinstance(corps, dict):
            return self._erreur(
                "invalid_request", _("Corps de requête illisible."), 400)
        return self._servir_photo(
            lambda service: service.delete_photo(
                reference, photo_uuid, corps.get("request_uuid")),
            "ops/intakes/photos/delete",
        )

    def _servir_photo(self, operation, route):
        if not self._a_un_role_ops():
            return self._refus_ops(route)
        try:
            data = operation(request.env["dally.ops.photo.service"])
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
