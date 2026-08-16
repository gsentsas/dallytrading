"""
Traduction du vocabulaire `tk_freight` vers celui de DallyTrading.

Un seul endroit, pour une raison précise : un mapping dispersé se met à diverger
dès la première correction locale, et personne ne sait plus quelle version fait
foi. Tout ce qui traduit du tk vers du Dally passe ici.

## Pourquoi les xmlid et non les libellés

Les étapes de `tk_freight` sont des **enregistrements**, pas une sélection :
`freight.shipment.stages` ne porte que `name`, `sequence` et `is_last_stage`. Le
`name` est un libellé d'interface — traduisible, renommable par n'importe quel
administrateur, et sans garantie de stabilité entre deux versions du
fournisseur. S'appuyer dessus reviendrait à faire dépendre l'état vu par le
client d'un champ que l'exploitation peut éditer par mégarde.

Les xmlid, eux, sont stables : `tk_freight.stage_data_1` à `stage_data_5`,
vérifiés en base. C'est la seule clé technique disponible, donc c'est la clé.

## Pourquoi l'échec est fermé

Une étape inconnue — parce que le fournisseur en a ajouté une, ou parce que
l'exploitation en a créé une — ne doit **jamais** être traduite en un état
final. Annoncer « Livré » sur une expédition qui ne l'est pas est la pire sortie
possible : le client cesse de suivre, et personne ne s'aperçoit de rien.

L'inconnu est donc traduit par `None`, et l'appelant conserve l'état précédent
plutôt que d'en inventer un.
"""

import logging

_logger = logging.getLogger(__name__)

#: Étape tk (xmlid) → état `dally.shipment`.
#:
#: Le fournisseur n'expose que cinq étapes, plus grossières que nos quatorze
#: états. La correspondance est donc volontairement conservatrice : on ne
#: déduit jamais un état plus avancé que ce que l'étape garantit.
STAGE_XMLID_TO_STATE = {
    "tk_freight.stage_data_1": "draft",       # Draft
    "tk_freight.stage_data_2": "ready",       # Ready
    "tk_freight.stage_data_3": "preparing",   # In Progress
    "tk_freight.stage_data_4": "in_transit",  # In Transit
    "tk_freight.stage_data_5": "delivered",   # Delivered
}

#: Transport tk → mode `dally.shipment`.
#:
#: `vehicle`, `groupage` et `other` existent côté Dally mais n'ont pas
#: d'équivalent tk : ils restent réservés aux expéditions saisies hors du moteur
#: fret. La traduction est donc à sens unique et non surjective, ce qui est
#: normal — le pont ne réécrit jamais tk depuis Dally.
TRANSPORT_TO_MODE = {
    "ocean": "sea",
    "air": "air",
    "land": "road",
}

#: Direction tk → direction `dally.shipment`. `domestic` n'existe pas côté tk.
DIRECTION_TO_DIRECTION = {
    "import": "import",
    "export": "export",
}

#: Code de `dally.service.type` → transport tk.
#:
#: C'est le devis qui porte l'information, via le service demandé par le client.
#: La déduire d'ailleurs — ou la fixer en dur — reviendrait à décider à sa place.
#:
#: `freight_groupage` est rattaché au maritime : le groupage de DallyTrading est
#: du LCL. Si un groupage aérien apparaît un jour, il lui faudra son propre code
#: de service, pas une exception ici.
SERVICE_CODE_TO_TRANSPORT = {
    "freight_sea": "ocean",
    "freight_air": "air",
    "freight_vehicle": "land",
    "freight_groupage": "ocean",
}

#: Transport retenu quand le service ne désigne pas de mode — `import_export`,
#: `logistics`, `other`…
#:
#: Le maritime est le flux très majoritaire. Ce n'est pas un « fail-closed »
#: comme pour les états, et la nuance est délibérée : un mode erroné est visible
#: et corrigeable au back-office, et la correction redescend au client puisque la
#: projection est à sens unique. Un état final erroné, lui, fait cesser le suivi
#: sans que personne ne s'en aperçoive.
TRANSPORT_PAR_DEFAUT = "ocean"


def transport_from_service(service_type):
    """Transport tk déduit du service demandé, ou le défaut documenté."""
    code = (service_type.code or "") if service_type else ""
    transport = SERVICE_CODE_TO_TRANSPORT.get(code)
    if transport:
        return transport
    _logger.info(
        "Service %r sans mode de transport explicite : %s retenu par defaut.",
        code or "(aucun)",
        TRANSPORT_PAR_DEFAUT,
    )
    return TRANSPORT_PAR_DEFAUT


def state_from_stage(env, stage):
    """Traduit une étape tk en état Dally, ou `None` si elle est inconnue.

    `None` n'est pas une erreur : c'est le signal que l'appelant doit conserver
    l'état courant. Voir l'en-tête sur l'échec fermé.
    """
    if not stage:
        return None

    # `_xmlid_lookup` n'existe que dans un sens ; on résout donc l'inverse via
    # ir.model.data, en sudo car un utilisateur métier n'a pas à lire cette
    # table pour que la traduction fonctionne.
    donnee = env["ir.model.data"].sudo().search(
        [
            ("model", "=", "freight.shipment.stages"),
            ("res_id", "=", stage.id),
        ],
        limit=1,
    )
    if not donnee:
        _logger.warning(
            "Etape tk_freight sans xmlid (id=%s, name=%r) : etat Dally inchange.",
            stage.id,
            stage.name,
        )
        return None

    xmlid = f"{donnee.module}.{donnee.name}"
    etat = STAGE_XMLID_TO_STATE.get(xmlid)
    if etat is None:
        _logger.warning(
            "Etape tk_freight inconnue du mapping (%s, name=%r) : etat Dally "
            "inchange. Completer STAGE_XMLID_TO_STATE apres verification.",
            xmlid,
            stage.name,
        )
    return etat


def mode_from_transport(transport):
    """Traduit un transport tk en mode Dally, ou `None` si inconnu."""
    if not transport:
        return None
    mode = TRANSPORT_TO_MODE.get(transport)
    if mode is None:
        _logger.warning(
            "Transport tk_freight inconnu du mapping (%r) : mode Dally inchange.",
            transport,
        )
    return mode
