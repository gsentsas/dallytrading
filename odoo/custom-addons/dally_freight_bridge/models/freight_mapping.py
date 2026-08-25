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
    "dally_freight_bridge.stage_request_received": "request_received",
    "dally_freight_bridge.stage_awaiting_goods": "awaiting_goods",
    "dally_freight_bridge.stage_goods_received": "goods_received",
    "dally_freight_bridge.stage_preparing": "preparing",
    "dally_freight_bridge.stage_ready": "ready",
    "dally_freight_bridge.stage_departed": "departed",
    "dally_freight_bridge.stage_in_transit": "in_transit",
    "dally_freight_bridge.stage_arrived": "arrived",
    "dally_freight_bridge.stage_customs": "customs",
    "dally_freight_bridge.stage_available": "available",
    "dally_freight_bridge.stage_out_for_delivery": "out_for_delivery",
    "dally_freight_bridge.stage_delivered": "delivered",
    "dally_freight_bridge.stage_cancelled": "cancelled",
}

STATE_TO_STAGE_XMLID = {
    state: "dally_freight_bridge.stage_%s" % state
    for state in (
        "request_received", "awaiting_goods", "goods_received", "preparing",
        "ready", "departed", "in_transit", "arrived", "customs",
        "available", "out_for_delivery", "delivered", "cancelled",
    )
}
STATE_TO_STAGE_XMLID["draft"] = "tk_freight.stage_data_1"

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

#: Code de `dally.service.type` → transport tk, pour le **provisionnement**.
#:
#: Volontairement court. N'y figure qu'un service dont le mode est déductible
#: sans interprétation : « Sea Freight » est du maritime, « Air Freight » de
#: l'aérien. Rien d'autre.
#:
#: ## Pourquoi il n'y a plus de valeur par défaut
#:
#: Une version précédente retombait sur `ocean` pour tout code non reconnu. Le
#: raisonnement — « le maritime est le flux majoritaire, et l'exploitation
#: corrigera » — était faux sur le point qui compte : personne ne sait qu'il y a
#: quelque chose à corriger. Un client demandant un transport de véhicule
#: recevait une expédition maritime, créée, référencée, projetée et visible dans
#: son espace, sans qu'aucun signal ne soit émis.
#:
#: Un code inconnu est désormais une **erreur métier** qui annule le
#: provisionnement, et avec lui l'acceptation du devis — les deux étant dans la
#: même transaction. Le devis reste en attente, ce qui est un état vrai et
#: rattrapable, plutôt qu'une expédition fausse et silencieuse.
#:
#: `freight_groupage` n'y est pas : le groupage est le plus souvent du LCL
#: maritime, mais le groupage aérien existe. « Le plus souvent » n'est pas une
#: base pour créer une expédition. Il porte donc son mode, comme le véhicule.
#:
#: `freight_vehicle` n'y est pas non plus, mais pour une raison différente et
#: durable : son mode physique est porté par la marchandise, pas par le service.
#: Voir `SERVICES_A_MODE_PORTE` juste en dessous.
SERVICE_CODE_TO_TRANSPORT = {
    "freight_sea": "ocean",
    "freight_air": "air",
}

#: Services dont le mode physique **ne se déduit pas du service**.
#:
#: `freight_vehicle` en est le cas d'école : « transport de véhicule » décrit ce
#: que le client achète, pas la façon dont la voiture voyage. Paris → Dakar part
#: par bateau, Dakar → Bamako par camion, et c'est le même service commercial.
#:
#: Ces services lisent donc leur mode sur la marchandise elle-même. Les inscrire
#: ici plutôt que dans `SERVICE_CODE_TO_TRANSPORT` est délibéré : y mettre une
#: valeur reviendrait à trancher à la place du client.
SERVICES_A_MODE_PORTE = frozenset({"freight_vehicle", "freight_groupage"})

#: Mode de groupage déclaré sur le devis → transport `tk_freight`.
#:
#: Le maritime s'accompagne de `ocean_shipment_type = "lcl"`, qui est une valeur
#: réelle du fournisseur — vérifiée dans sa sélection `fcl`/`lcl` — et non une
#: approximation posée dans une note ou une description.
#:
#: L'aérien, lui, n'a **aucun** équivalent chez le fournisseur : il n'existe pas
#: de champ de consolidation aérienne. On ne détourne pas `operation = "house"`
#: pour en tenir lieu — la LTA maison contre LTA mère décrit un rapport entre
#: transitaires, pas le caractère groupé d'un envoi commercial. Le groupage
#: aérien se lit donc sur le service du devis, et nulle part ailleurs.
GROUPAGE_MODE_TO_TRANSPORT = {
    "sea": ("ocean", "lcl"),
    "air": ("air", False),
}

#: Mode physique déclaré sur le véhicule → transport `tk_freight`.
#:
#: Le maritime devient `ocean` et non `land` : une voiture sur un roulier est
#: une expédition maritime, quoi qu'en dise l'intitulé du service.
VEHICLE_MODE_TO_TRANSPORT = {
    "sea": "ocean",
    "road": "land",
}


#: Préfixe des services qui relèvent du moteur fret.
#:
#: ## Pourquoi cette distinction existe
#:
#: Le refus d'un mode indéterminable ne doit pas déborder sur les devis qui
#: n'ont rien à voir avec le fret. DallyTrading vend aussi du sourcing, du
#: trading, de l'e-commerce : accepter un de ces devis ne doit créer aucune
#: expédition, et surtout ne doit pas échouer parce que le moteur fret n'a pas
#: su en déduire un mode de transport.
#:
#: Mesuré en le cassant : la première version du fail-closed refusait *tout*
#: devis dont le service n'était ni maritime ni aérien. Un devis de sourcing
#: devenait inacceptable, et la suite de tests du portail se bloquait sur son
#: test de concurrence.
#:
#: La règle tient donc en deux temps :
#:
#: 1. le service relève-t-il du fret ? sinon, **aucun provisionnement**, et
#:    l'acceptation suit son cours normal ;
#: 2. s'il en relève, son mode doit être supporté — sinon **refus explicite**.
PREFIXE_SERVICE_FRET = "freight_"


class TransportIndeterminable(Exception):
    """Un service **fret** ne désigne aucun mode de transport supporté.

    Portée par le module de mapping plutôt que par le provisionnement : c'est
    la traduction qui échoue, et l'appelant décide de ce qu'il en fait.
    """

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def is_freight_service(service_type):
    """Le service demandé relève-t-il du moteur fret ?

    Le test porte sur le préfixe du code, et non sur une liste close : un
    `freight_rail` ajouté demain doit entrer dans le périmètre du fret — donc
    être refusé faute de mapping — plutôt que d'être ignoré en silence.
    """
    code = (service_type.code or "") if service_type else ""
    return code.startswith(PREFIXE_SERVICE_FRET)


def carries_own_mode(service_type):
    """Le mode physique de ce service est-il porté par la marchandise ?"""
    code = (service_type.code or "") if service_type else ""
    return code in SERVICES_A_MODE_PORTE


def transport_from_groupage_mode(mode):
    """Mode de groupage → `(transport tk, type d'expédition maritime)`.

    Lève `TransportIndeterminable` si le mode est absent ou inconnu. Aucun
    repli : un envoi groupé dont on ignore s'il part par bateau ou par avion
    serait facturé au mauvais ratio volumétrique.
    """
    couple = GROUPAGE_MODE_TO_TRANSPORT.get(mode or "")
    if couple:
        return couple
    _logger.warning(
        "Mode de groupage %r non supporte : provisionnement refuse.",
        mode or "(aucun)",
    )
    raise TransportIndeterminable(mode or "")


def transport_from_vehicle_mode(mode):
    """Mode physique déclaré sur le véhicule → transport tk.

    Lève `TransportIndeterminable` si le mode est absent ou inconnu. Aucun
    repli : un véhicule dont on ignore s'il part par bateau ou par camion est
    un dossier qu'on ne provisionne pas.
    """
    transport = VEHICLE_MODE_TO_TRANSPORT.get(mode or "")
    if transport:
        return transport
    _logger.warning(
        "Mode de transport vehicule %r non supporte : provisionnement refuse.",
        mode or "(aucun)",
    )
    raise TransportIndeterminable(mode or "")


def transport_from_service(service_type):
    """Transport tk déduit du service demandé.

    Lève `TransportIndeterminable` si le service relève du fret sans mode
    supporté, **ou** s'il porte son mode sur la marchandise : dans ce dernier
    cas l'appelant doit passer par `transport_from_vehicle_mode`, et se tromper
    de chemin doit échouer bruyamment plutôt que retomber sur un défaut.
    """
    code = (service_type.code or "") if service_type else ""
    if code in SERVICES_A_MODE_PORTE:
        _logger.warning(
            "Service %r porte son mode sur la marchandise : "
            "transport_from_service n'est pas le bon chemin.", code,
        )
        raise TransportIndeterminable(code)
    transport = SERVICE_CODE_TO_TRANSPORT.get(code)
    if transport:
        return transport
    _logger.warning(
        "Service fret %r sans mode de transport supporte : provisionnement "
        "refuse. Completer SERVICE_CODE_TO_TRANSPORT apres decision metier.",
        code or "(aucun)",
    )
    raise TransportIndeterminable(code)


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


def stage_from_state(env, state):
    """Resolve the Dally-owned operational stage for a Dally state."""
    xmlid = STATE_TO_STAGE_XMLID.get(state)
    return env.ref(xmlid, raise_if_not_found=False) if xmlid else None


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
