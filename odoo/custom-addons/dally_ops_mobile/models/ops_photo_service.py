# -*- coding: utf-8 -*-
"""Prendre, lire et retirer les preuves photographiques d'un dossier.

## Ce que le serveur ne délègue jamais au navigateur

L'identité de la photo, l'auteur, la date, la nature acceptée, l'état du
dossier, les quotas, le type réel du fichier et ses dimensions. Le navigateur
n'apporte que trois choses : les octets, l'identifiant de son geste, et la
nature qu'il propose.

## Pourquoi les dimensions se lisent dans l'en-tête

Une image de 60 000 × 60 000 pixels tient dans quelques kilooctets compressés
et réclame plusieurs gigaoctets une fois décodée. Refuser sur la seule taille
du fichier ne protège donc de rien. Mais décoder pour mesurer, c'est subir
l'attaque qu'on prétend arrêter.

Les quatre formats acceptés annoncent tous leurs dimensions dans un en-tête
borné, avant la moindre donnée compressée : segment `SOF` pour JPEG, bloc
`IHDR` pour PNG, entête de trame pour WebP, boîte `ispe` pour HEIC. On les y
lit, on ne décode rien, et un fichier qui ne les annonce pas est refusé plutôt
que d'être accepté sans contrôle.

Ce choix évite aussi une dépendance : Pillow, présent dans l'image Odoo, ne
sait pas ouvrir un HEIC — mesuré en 10.2.0, aucune extension HEIF enregistrée.
Un lecteur d'en-têtes couvre les quatre formats de la même façon.

## Ce qui n'arrive jamais ici

Aucun `dally.shipment.event`, aucune notification client, aucune projection
tableur, aucune publication portail. Une preuve d'exploitation reste interne :
c'est le journal Ops qui la consigne, et lui seul.
"""

import hashlib
import os
import re
import struct
import uuid as uuid_module

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .ops_errors import DallyOpsConflict, DallyOpsError, DallyOpsNotFound
from .ops_photo import PHOTO_KINDS

#: Dix mébioctets, comme le justificatif de caisse : une photo de téléphone en
#: fait deux ou trois, et le terrain n'a pas à se demander quelle limite
#: s'applique où.
MAX_FILE_BYTES = 10 * 1024 * 1024

#: Ce qu'un dossier porte de preuves visibles à la fois.
MAX_ACTIVE_PHOTOS = 20
#: Retirées comprises : sans cela, ajouter et retirer en boucle contournerait
#: la limite précédente sans jamais la franchir.
MAX_RETAINED_PHOTOS = 30
MAX_RETAINED_BYTES = 256 * 1024 * 1024

#: Au-delà, l'image n'est plus une preuve de terrain mais une charge.
MAX_PIXELS = 50_000_000
MAX_DIMENSION = 12_000

#: Les états où une preuve peut encore être prise.
#:
#: Plus large que `ETATS_MODIFIABLES` des articles, et c'est délibéré : à
#: `ready` les articles sont figés, mais c'est précisément le moment où l'on
#: photographie l'emballage terminé. Figer la preuve avec les articles
#: priverait le dossier de la seule image qui compte.
ETATS_AJOUT = ("goods_received", "preparing", "ready")

#: Qui retire quoi, et jusqu'à quand.
ETATS_RETRAIT_LOGISTICIEN = ("goods_received", "preparing")
ETATS_RETRAIT_SUPERVISEUR = ("goods_received", "preparing", "ready")

#: Les natures valides, tirées du modèle : deux listes divergeraient.
KINDS_VALIDES = frozenset(code for code, _libelle in PHOTO_KINDS)

#: Ce qu'un appareil photo de terrain produit, reconnu à ses octets.
SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)

MARQUES_HEIC = (b"heic", b"heix", b"hevc", b"mif1", b"heim", b"heis", b"msf1")

EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}

#: Bornes du parcours d'en-tête. Un fichier qui demande plus que cela pour
#: annoncer sa taille ne l'annonce pas : il fait marcher le lecteur.
MAX_SEGMENTS = 512
MAX_PROFONDEUR_BOITES = 5
#: Un conteneur honnête en compte quelques dizaines.
MAX_BOITES = 512
#: Une vignette, une image principale, quelques dérivées : pas cent.
MAX_ISPE = 16


# ----------------------------------------------------------------------
# Type réel
# ----------------------------------------------------------------------

def type_image_reel(contenu):
    """Le type déduit des **octets**, ou `None`.

    Même règle que le justificatif de caisse : un envoyeur choisit son
    extension et son en-tête, il ne choisit pas ses premiers octets. La
    fonction ne lève rien — chaque appelant reste maître du refus qu'il
    prononce et du code qu'il rend.
    """
    for signature, mimetype in SIGNATURES:
        if contenu.startswith(signature):
            return mimetype
    if contenu[:4] == b"RIFF" and contenu[8:12] == b"WEBP":
        return "image/webp"
    if contenu[4:8] == b"ftyp" and contenu[8:12] in MARQUES_HEIC:
        return "image/heic"
    return None


def nom_de_stockage(filename, mimetype):
    """Un nom de stockage, jamais un chemin venu du client."""
    base = os.path.basename((filename or "").replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9._-]", "", base) or "photo"
    base = re.sub(r"\.+", ".", base).lstrip(".")[:80] or "photo"
    racine = base.rsplit(".", 1)[0] or "photo"
    return "%s%s" % (racine, EXTENSIONS[mimetype])


# ----------------------------------------------------------------------
# Dimensions, lues sans décoder
# ----------------------------------------------------------------------

def _dimensions_jpeg(contenu):
    """Le premier segment `SOF`, en parcourant la chaîne des marqueurs."""
    position = 2
    for _tour in range(MAX_SEGMENTS):
        if position + 4 > len(contenu):
            return None
        if contenu[position] != 0xFF:
            return None
        marqueur = contenu[position + 1]
        # Marqueurs sans charge utile : on avance d'un octet.
        if marqueur in (0xD8, 0x01) or 0xD0 <= marqueur <= 0xD7:
            position += 2
            continue
        longueur = struct.unpack(">H", contenu[position + 2:position + 4])[0]
        if longueur < 2:
            return None
        # Tous les SOF sauf DHT (C4), JPG (C8) et DAC (CC), qui ne décrivent
        # pas une trame.
        if 0xC0 <= marqueur <= 0xCF and marqueur not in (0xC4, 0xC8, 0xCC):
            if position + 9 > len(contenu):
                return None
            hauteur, largeur = struct.unpack(
                ">HH", contenu[position + 5:position + 9])
            return largeur, hauteur
        position += 2 + longueur
    return None


def _dimensions_png(contenu):
    if len(contenu) < 24 or contenu[12:16] != b"IHDR":
        return None
    largeur, hauteur = struct.unpack(">II", contenu[16:24])
    return largeur, hauteur


def _dimensions_webp(contenu):
    """Trois encodages, trois en-têtes : `VP8X`, `VP8L`, `VP8 `."""
    position = 12
    for _tour in range(MAX_SEGMENTS):
        if position + 8 > len(contenu):
            return None
        nom = contenu[position:position + 4]
        taille = struct.unpack("<I", contenu[position + 4:position + 8])[0]
        charge = contenu[position + 8:position + 8 + taille]
        if nom == b"VP8X" and len(charge) >= 10:
            largeur = int.from_bytes(charge[4:7], "little") + 1
            hauteur = int.from_bytes(charge[7:10], "little") + 1
            return largeur, hauteur
        if nom == b"VP8L" and len(charge) >= 5 and charge[0] == 0x2F:
            bits = int.from_bytes(charge[1:5], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if nom == b"VP8 " and len(charge) >= 10:
            if charge[3:6] != b"\x9d\x01\x2a":
                return None
            largeur = struct.unpack("<H", charge[6:8])[0] & 0x3FFF
            hauteur = struct.unpack("<H", charge[8:10])[0] & 0x3FFF
            return largeur, hauteur
        if taille <= 0:
            return None
        position += 8 + taille + (taille % 2)
    return None


class _ConteneurInvalide(Exception):
    """Le conteneur ne se lit pas proprement. On refuse plutôt que de deviner."""


def _collecter_ispe(tampon, etat, profondeur=0, sommet=False):
    """Recense **toutes** les boîtes `ispe` d'un conteneur ISOBMFF.

    ## Pourquoi toutes, et pas la première

    Un HEIC d'iPhone en contient légitimement plusieurs : la vignette et
    l'image principale sont deux éléments, chacun avec son extension spatiale.
    S'arrêter à la première laisserait donc passer une vignette de trente
    pixels suivie d'une image de soixante mille — le fichier serait mesuré sur
    ce qu'il montre de plus petit et stocké pour ce qu'il a de plus grand.

    On les relève toutes, et l'appelant retiendra le pire cas.

    ## Pourquoi une exception plutôt qu'un `None`

    Une taille de boîte nulle au milieu d'un conteneur, une boîte qui déborde
    de son parent, une profondeur qui ne finit pas : ce ne sont pas des
    fichiers qu'on n'a pas su lire, ce sont des fichiers qui mentent. Les
    distinguer permet de refuser sans jamais retomber sur une valeur par
    défaut.
    """
    if profondeur > MAX_PROFONDEUR_BOITES:
        raise _ConteneurInvalide("imbrication excessive")
    position = 0
    while position < len(tampon):
        etat["boites"] -= 1
        if etat["boites"] < 0:
            raise _ConteneurInvalide("trop de boîtes")
        if position + 8 > len(tampon):
            raise _ConteneurInvalide("en-tête de boîte tronqué")

        taille = struct.unpack(">I", tampon[position:position + 4])[0]
        nom = tampon[position + 4:position + 8]
        entete = 8
        if taille == 1:
            if position + 16 > len(tampon):
                raise _ConteneurInvalide("taille étendue tronquée")
            taille = struct.unpack(">Q", tampon[position + 8:position + 16])[0]
            entete = 16
        elif taille == 0:
            # « jusqu'à la fin » n'a de sens qu'à la racine. Imbriquée, cette
            # valeur laisse une boîte enfant déborder de son parent.
            if not sommet:
                raise _ConteneurInvalide("taille nulle imbriquée")
            taille = len(tampon) - position

        if taille < entete:
            raise _ConteneurInvalide("taille de boîte impossible")
        if position + taille > len(tampon):
            raise _ConteneurInvalide("boîte débordant du conteneur")

        if nom == b"ispe":
            corps = tampon[position + entete:position + taille]
            if len(corps) < 12:
                raise _ConteneurInvalide("ispe tronquée")
            etat["ispe"].append(struct.unpack(">II", corps[4:12]))
            if len(etat["ispe"]) > MAX_ISPE:
                raise _ConteneurInvalide("trop d'extensions spatiales")

        elif nom in (b"meta", b"iprp", b"ipco"):
            # `meta` est une FullBox : quatre octets de version et de drapeaux
            # précèdent ses enfants. `iprp` et `ipco` n'en ont pas.
            saut = entete + (4 if nom == b"meta" else 0)
            if taille < saut:
                raise _ConteneurInvalide("conteneur tronqué")
            _collecter_ispe(
                tampon[position + saut:position + taille], etat, profondeur + 1)

        position += taille
    return etat["ispe"]


def _dimensions_isobmff(contenu):
    """Le pire cas annoncé par le conteneur, ou une erreur.

    Largeur et hauteur maximales, prises séparément : un fichier qui déclare
    une image de 20 000 × 1 et une autre de 1 × 20 000 doit être refusé sur les
    deux, et non passer parce qu'aucune ne dépasse en surface.
    """
    etat = {"boites": MAX_BOITES, "ispe": []}
    mesures = _collecter_ispe(contenu, etat, sommet=True)
    if not mesures:
        raise _ConteneurInvalide("aucune extension spatiale")
    return max(l for l, _h in mesures), max(h for _l, h in mesures)


def dimensions_image(contenu, mimetype):
    """Largeur et hauteur annoncées, ou `None` si le fichier ne les annonce pas.

    Aucun bitmap n'est décodé : seuls des en-têtes bornés sont parcourus.
    """
    try:
        if mimetype == "image/jpeg":
            return _dimensions_jpeg(contenu)
        if mimetype == "image/png":
            return _dimensions_png(contenu)
        if mimetype == "image/webp":
            return _dimensions_webp(contenu)
        if mimetype == "image/heic":
            return _dimensions_isobmff(contenu)
    except (_ConteneurInvalide, struct.error, IndexError, ValueError):
        return None
    return None


class DallyOpsPhotoService(models.AbstractModel):
    _name = "dally.ops.photo.service"
    _description = "Dally Ops — preuves photographiques d'un dossier"

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    @api.model
    def list_photos(self, reference):
        """Les preuves visibles du dossier, et ce que l'opérateur peut en faire."""
        self._exiger_role_ops()
        shipment = self._resoudre_dossier(reference)
        photos = self.env["dally.ops.photo"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("shipment_id", "=", shipment.id),
            ("active", "=", True),
        ], order="create_date desc, id desc")
        return {
            "photos": [self._en_dto(photo, shipment) for photo in photos],
            "can_add": self._peut_ajouter(shipment),
            "limits": {
                "max_file_bytes": MAX_FILE_BYTES,
                "max_active_photos": MAX_ACTIVE_PHOTOS,
            },
        }

    @api.model
    def read_photo(self, reference, photo_uuid):
        """Les octets d'une preuve, et rien qui permette d'en deviner d'autres.

        Une photo d'un autre dossier ou d'une autre société répond comme une
        photo inexistante : le même 404, sans distinction, pour qu'un essai ne
        renseigne jamais sur ce qui existe ailleurs.
        """
        self._exiger_role_ops()
        shipment = self._resoudre_dossier(reference)
        photo = self._resoudre_photo(shipment, photo_uuid, actives_seules=True)
        piece = photo.attachment_id.sudo()
        return {
            "mime_type": piece.mimetype or "application/octet-stream",
            "content": piece.raw or b"",
        }

    # ------------------------------------------------------------------
    # Ajout
    # ------------------------------------------------------------------

    @api.model
    def add_photo(self, reference, request_uuid, kind, filename, content):
        """Enregistre une preuve, ou dit précisément pourquoi elle est refusée."""
        self._exiger_role_ops()
        request_uuid = self._identifiant(request_uuid)

        if kind not in KINDS_VALIDES:
            raise DallyOpsError(
                _("Cette nature de photo n'existe pas."),
                code="photo_kind_invalid", status=422)
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise DallyOpsError(
                _("Photo vide."), code="photo_empty", status=422)
        contenu = bytes(content)
        if len(contenu) > MAX_FILE_BYTES:
            raise DallyOpsError(
                _("La photo dépasse la taille autorisée."),
                code="photo_too_large", status=422)

        empreinte = hashlib.sha256(contenu).hexdigest()

        with self.env.cr.savepoint():
            self._verrouiller("ops-photo:%s:%s" % (
                self.env.company.id, request_uuid))
            shipment = self._resoudre_dossier(reference)

            # Le rejeu se tranche **avant** les quotas : une reprise réseau
            # légitime ne doit pas être refusée parce que le premier envoi,
            # celui-là même qu'on rejoue, a rempli le dossier.
            rejeu = self._rejeu(
                request_uuid, "add",
                self._intention_ajout(shipment, kind, empreinte))
            if rejeu is not None:
                return {"status": "replayed",
                        "photo": self._en_dto(rejeu, shipment)}

            # La ligne du dossier est prise avant de compter : deux envois
            # simultanés compteraient sinon les mêmes dix-neuf photos et
            # écriraient chacun la vingtième.
            self._verrouiller_dossier(shipment)
            shipment.invalidate_recordset(["state"])

            if shipment.state not in ETATS_AJOUT:
                raise DallyOpsConflict(
                    _("Ce dossier n'accepte plus de photo."),
                    code="photo_state_not_allowed")

            mimetype = type_image_reel(contenu)
            if mimetype is None:
                raise DallyOpsError(
                    _("Ce type de fichier n'est pas accepté comme photo."),
                    code="photo_type_not_allowed", status=422)

            mesure = dimensions_image(contenu, mimetype)
            if mesure is None:
                raise DallyOpsError(
                    _("Les dimensions de cette image sont illisibles."),
                    code="photo_dimensions_unreadable", status=422)
            largeur, hauteur = mesure
            if largeur <= 0 or hauteur <= 0:
                raise DallyOpsError(
                    _("Les dimensions de cette image sont illisibles."),
                    code="photo_dimensions_unreadable", status=422)
            if largeur > MAX_DIMENSION or hauteur > MAX_DIMENSION:
                raise DallyOpsError(
                    _("Cette image est trop grande pour être conservée."),
                    code="photo_dimensions_too_large", status=422)
            if largeur * hauteur > MAX_PIXELS:
                raise DallyOpsError(
                    _("Cette image est trop grande pour être conservée."),
                    code="photo_dimensions_too_large", status=422)

            self._exiger_quotas(shipment, len(contenu))

            Photo = self.env["dally.ops.photo"].sudo()
            piece = self.env["ir.attachment"].sudo().create({
                "name": nom_de_stockage(filename, mimetype),
                "raw": contenu,
                "mimetype": mimetype,
                "res_model": "dally.ops.photo",
                # Renseigné juste après la création : la photo n'a pas encore
                # d'identité au moment où ses octets sont écrits.
                "res_id": 0,
                "company_id": self.env.company.id,
                # Jamais servi par l'URL publique d'Odoo. Une preuve
                # d'exploitation n'est atteignable que par la route Ops.
                "public": False,
            })
            photo = Photo.create({
                "photo_uuid": str(uuid_module.uuid4()),
                "company_id": self.env.company.id,
                "shipment_id": shipment.id,
                "attachment_id": piece.id,
                "kind": kind,
                "operator_user_id": self.env.uid,
            })
            piece.write({"res_id": photo.id})

            self._inscrire(
                request_uuid, "add", photo, empreinte,
                self._intention_ajout(shipment, kind, empreinte))
            self._journaliser("photo_added", photo, request_uuid)
            return {"status": "added", "photo": self._en_dto(photo, shipment)}

    # ------------------------------------------------------------------
    # Retrait
    # ------------------------------------------------------------------

    @api.model
    def delete_photo(self, reference, photo_uuid, request_uuid):
        """Retire une preuve de la vue, sans jamais détruire ses octets."""
        self._exiger_role_ops()
        request_uuid = self._identifiant(request_uuid)

        with self.env.cr.savepoint():
            self._verrouiller("ops-photo:%s:%s" % (
                self.env.company.id, request_uuid))
            shipment = self._resoudre_dossier(reference)
            photo = self._resoudre_photo(
                shipment, photo_uuid, actives_seules=False)

            rejeu = self._rejeu(
                request_uuid, "delete", self._intention_retrait(photo))
            if rejeu is not None:
                return {"status": "replayed",
                        "photo": self._en_dto(rejeu, shipment)}

            self._verrouiller_dossier(shipment)
            shipment.invalidate_recordset(["state"])

            if not photo.active:
                raise DallyOpsConflict(
                    _("Cette photo a déjà été retirée."),
                    code="photo_already_deleted")
            if not self._peut_retirer(photo, shipment):
                raise DallyOpsConflict(
                    _("Vous ne pouvez pas retirer cette photo."),
                    code="photo_delete_not_allowed")

            photo.write({
                "active": False,
                "deleted_at": fields.Datetime.now(),
                "deleted_by_user_id": self.env.uid,
            })
            self._inscrire(
                request_uuid, "delete", photo, False,
                self._intention_retrait(photo))
            self._journaliser("photo_deleted", photo, request_uuid)
            return {"status": "deleted", "photo": self._en_dto(photo, shipment)}

    # ------------------------------------------------------------------
    # Portée
    # ------------------------------------------------------------------

    @api.model
    def _exiger_role_ops(self):
        if not self.env["res.users"]._dally_ops_role():
            raise AccessError(_("Accès réservé aux opérateurs terrain."))

    @api.model
    def _resoudre_dossier(self, reference):
        """Le domaine Ops natif, appelé et non recopié.

        Un dossier historique ou repris du tableur n'entre pas dans ce domaine :
        il se cherche et s'affiche, mais rien ne s'y attache.
        """
        return self.env["dally.ops.intake.line.service"]._resoudre_dossier(
            reference)

    @api.model
    def _resoudre_photo(self, shipment, photo_uuid, actives_seules):
        if not isinstance(photo_uuid, str) or not photo_uuid.strip():
            raise DallyOpsNotFound(
                _("Photo introuvable."), code="photo_not_found")
        domaine = [
            ("company_id", "=", self.env.company.id),
            ("shipment_id", "=", shipment.id),
            ("photo_uuid", "=", photo_uuid.strip()),
        ]
        if actives_seules:
            domaine.append(("active", "=", True))
        photo = self.env["dally.ops.photo"].sudo().with_context(
            active_test=False).search(domaine, limit=1)
        if not photo:
            raise DallyOpsNotFound(
                _("Photo introuvable."), code="photo_not_found")
        return photo

    # ------------------------------------------------------------------
    # Droits et quotas
    # ------------------------------------------------------------------

    @api.model
    def _peut_ajouter(self, shipment):
        """Ce que l'écran a le droit de proposer.

        La même règle que celle qui refuse à l'écriture, appelée et non
        recopiée : annoncer `can_add` sur un dossier plein ferait promettre au
        terrain une action que le serveur refuse ensuite.

        Un octet suffit à poser la question du volume — « reste-t-il de la
        place pour ne serait-ce qu'un octet ? » — sans avoir à connaître le
        poids d'une photo qui n'existe pas encore.
        """
        return (
            shipment.state in ETATS_AJOUT
            and self._motif_quota(shipment, 1) is None
        )

    @api.model
    def _peut_retirer(self, photo, shipment):
        """Qui retire quoi, décidé ici et nulle part ailleurs.

        Un logisticien répare sa propre erreur tant que le dossier se prépare.
        Un responsable arbitre, y compris sur la photo d'un autre, et jusqu'à
        `ready`. Passé le départ, plus personne : le dossier ne relève plus du
        comptoir.
        """
        role = self.env["res.users"]._dally_ops_role()
        if role == "supervisor":
            return shipment.state in ETATS_RETRAIT_SUPERVISEUR
        return (
            photo.operator_user_id.id == self.env.uid
            and shipment.state in ETATS_RETRAIT_LOGISTICIEN
        )

    @api.model
    def _motif_quota(self, shipment, octets_ajoutes):
        """Ce qui empêche une photo de plus, ou `None`.

        Trois plafonds, comptés sous le verrou du dossier. Le plafond des
        actives borne ce qu'un opérateur voit ; celui des conservées empêche
        d'ajouter et de retirer en boucle pour le contourner ; celui des octets
        protège le filestore d'un dossier qui deviendrait à lui seul une
        archive.

        La règle vit ici et nulle part ailleurs : l'écriture la fait lever,
        l'affichage la fait répondre. Deux formulations divergeraient, et
        l'écran proposerait alors ce que le serveur refuse.
        """
        Photo = self.env["dally.ops.photo"].sudo().with_context(
            active_test=False)
        toutes = Photo.search([
            ("company_id", "=", self.env.company.id),
            ("shipment_id", "=", shipment.id),
        ])
        if len(toutes.filtered("active")) >= MAX_ACTIVE_PHOTOS:
            return "photo_quota_active"
        if len(toutes) >= MAX_RETAINED_PHOTOS:
            return "photo_quota_retained"
        conserves = sum(
            piece.file_size or 0
            for piece in toutes.mapped("attachment_id").sudo())
        if conserves + octets_ajoutes > MAX_RETAINED_BYTES:
            return "photo_quota_bytes"
        return None

    @api.model
    def _exiger_quotas(self, shipment, octets_ajoutes):
        motif = self._motif_quota(shipment, octets_ajoutes)
        if motif == "photo_quota_active":
            raise DallyOpsConflict(
                _("Ce dossier a atteint son nombre de photos."), code=motif)
        if motif == "photo_quota_retained":
            raise DallyOpsConflict(
                _("Ce dossier a atteint son nombre de photos conservées."),
                code=motif)
        if motif == "photo_quota_bytes":
            raise DallyOpsConflict(
                _("Ce dossier a atteint son volume de photos conservées."),
                code=motif)

    # ------------------------------------------------------------------
    # Verrous
    # ------------------------------------------------------------------

    @api.model
    def _verrouiller(self, cle):
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [cle])

    @api.model
    def _verrouiller_dossier(self, shipment):
        """Sérialise les gestes concurrents sur **ce** dossier.

        Le verrou par identifiant de demande ne protège que d'un rejeu ; deux
        opérateurs portent deux identifiants différents. C'est la ligne du
        dossier qui doit être prise, et avant de compter les quotas.
        """
        self.env.cr.execute(
            "SELECT id FROM dally_shipment WHERE id = %s FOR UPDATE",
            [shipment.id])

    # ------------------------------------------------------------------
    # Rejeu
    # ------------------------------------------------------------------

    @api.model
    def _intention_ajout(self, shipment, kind, empreinte):
        return self._empreinte_intention(
            "add", shipment.id, kind, empreinte)

    @api.model
    def _intention_retrait(self, photo):
        return self._empreinte_intention(
            "delete", photo.shipment_id.id, photo.photo_uuid, "")

    @staticmethod
    def _empreinte_intention(action, shipment_id, precision, empreinte):
        brut = "%s|%s|%s|%s" % (action, shipment_id, precision, empreinte)
        return hashlib.sha256(brut.encode("utf-8")).hexdigest()

    @api.model
    def _rejeu(self, request_uuid, action, intention):
        """Le geste déjà enregistré, ou `None`.

        L'intention est comparée en entier. Un identifiant recyclé sur une
        autre photo, une autre nature ou un autre dossier est un conflit : lui
        rendre en silence le résultat du premier ferait croire à l'opérateur
        qu'il a enregistré ce qu'il vient de faire.
        """
        precedent = self.env["dally.ops.photo.request"].sudo().search([
            ("company_id", "=", self.env.company.id),
            ("request_uuid", "=", request_uuid),
        ], limit=1)
        if not precedent:
            return None
        if precedent.action != action or precedent.intent_hash != intention:
            raise DallyOpsConflict(
                _("Cette demande a déjà été traitée pour une autre photo."),
                code="idempotency_conflict")
        return precedent.photo_id.sudo().with_context(active_test=False)

    @api.model
    def _inscrire(self, request_uuid, action, photo, empreinte, intention):
        self.env["dally.ops.photo.request"].sudo().create({
            "request_uuid": request_uuid,
            "company_id": self.env.company.id,
            "action": action,
            "photo_id": photo.id,
            "content_hash": empreinte or False,
            "intent_hash": intention,
            "operator_user_id": self.env.uid,
        })

    # ------------------------------------------------------------------
    # Traces
    # ------------------------------------------------------------------

    @api.model
    def _journaliser(self, action, photo, request_uuid):
        """Un seul événement par geste, et aucun événement de suivi client.

        `entity_res_id` désigne **la photo**, puisque `entity_model` la nomme :
        y mettre le dossier ferait pointer la trace vers un enregistrement d'un
        autre modèle, et l'identifiant retrouverait alors une photo qui n'a
        rien à voir. Le dossier, lui, a son propre champ.

        Le journal Ops consigne ce que l'équipe a fait. Le suivi client, lui,
        raconte l'avancement du dossier — une photo ne l'avance pas.
        """
        self.env["dally.ops.audit.event"].sudo().create({
            "company_id": self.env.company.id,
            "operator_user_id": self.env.uid,
            "action": action,
            "entity_model": "dally.ops.photo",
            "entity_res_id": photo.id,
            "shipment_id": photo.shipment_id.id,
            "request_uuid": request_uuid,
            "created_at": fields.Datetime.now(),
        })

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _identifiant(valeur):
        if not isinstance(valeur, str):
            raise DallyOpsError(_("Identifiant de demande invalide."))
        try:
            return str(uuid_module.UUID(valeur.strip()))
        except (ValueError, AttributeError):
            raise DallyOpsError(_("Identifiant de demande invalide."))

    # ------------------------------------------------------------------
    # Sortie
    # ------------------------------------------------------------------

    @api.model
    def _en_dto(self, photo, shipment):
        """Ce que l'écran a besoin de savoir, et rien d'autre.

        Aucune clé primaire, aucun `res_model`, aucun chemin de stockage,
        aucun nom de fichier : le nom d'origine ne dit rien à l'opérateur et
        rouvrirait une surface d'affichage pour rien.
        """
        return {
            "photo_uuid": photo.photo_uuid,
            "kind": photo.kind,
            "mime_type": photo.attachment_id.sudo().mimetype or "",
            "created_at": self._iso_utc(photo.create_date),
            "created_by": photo.operator_user_id.name or "",
            "can_delete": photo.active and self._peut_retirer(photo, shipment),
        }

    @staticmethod
    def _iso_utc(valeur):
        return fields.Datetime.to_datetime(valeur).isoformat(
            timespec="seconds") + "Z"
