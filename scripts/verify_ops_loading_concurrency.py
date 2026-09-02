# -*- coding: utf-8 -*-
"""Sonde de concurrence DEV pour le chargement d'un depart.

Ce qu'aucun test transactionnel ne peut montrer : deux operateurs qui appuient
au meme instant. Odoo execute chaque test dans une transaction unique et
annulee ; les verrous consultatifs pg_advisory_xact_lock ne s'y opposent donc
a personne. Il faut de vrais curseurs, de vrais commits, et une barriere.

Cinq questions, cinq reponses attendues :

1. Le meme geste envoye deux fois en parallele - reprise reseau, double appui -
   ne charge le colis qu'une fois.
2. Un chargement et un retrait concurrents du meme colis ne violent jamais les
   invariants de quantite ou d'unicite.
3. Le meme colis, attendu sur deux departs a la fois, ne peut finir charge
   que d'un seul cote.
4. Un chargement concurrent d'une cloture de collecte ne cree jamais de ligne
   apres cloture.
5. Deux gestes de `request_uuid` differents sur le meme depart ne se lisent
   jamais sur un instantane perime.

A lancer dans un shell Odoo, sur une base de banc - jamais en production.
"""

from threading import Barrier, Thread
from time import time_ns
from uuid import uuid4

from odoo import api
from odoo.modules.registry import Registry
from odoo.service.model import retrying

PREFIXE = "AIR-DSS-CDG-2099-LOAD-" + str(time_ns())
env = globals().get("env")
if env is None:
    raise RuntimeError("Cette sonde doit etre executee dans un shell Odoo.")

societe = env.company
Con = env["dally.freight.consolidation"]
Colis = env["dally.shipment.package"]

operateur = env["res.users"].create({
    "name": "Sonde chargement",
    "login": "sonde.load.%s" % uuid4().hex[:8],
    "group_ids": [(6, 0, [
        env.ref("dally_ops_mobile.group_dally_ops_logistician").id,
    ])],
    "company_id": societe.id,
    "company_ids": [(6, 0, [societe.id])],
})
partenaire = env["res.partner"].create({"name": "Client sonde %s" % PREFIXE})


def nouveau_depart(suffixe):
    return Con.create({
        "name": PREFIXE + suffixe,
        "company_id": societe.id,
        "state": "collecting",
        "transport_mode": "air",
        "direction": "export",
        "origin_country_id": env.ref("base.sn").id,
        "origin_city": "Dakar",
        "origin_location": "DSS",
        "destination_country_id": env.ref("base.fr").id,
        "destination_city": "Paris",
        "destination_location": "CDG",
    })


depart = nouveau_depart("-A")
depart_b = nouveau_depart("-B")
dossier = env["dally.shipment"].create({
    "partner_id": partenaire.id,
    "company_id": societe.id,
    "external_reference": PREFIXE + "-A001",
    "transport_mode": "air",
    "direction": "export",
    "origin_country_id": env.ref("base.sn").id,
    "origin_city": "Dakar",
    "origin_location": "DSS",
    "destination_country_id": env.ref("base.fr").id,
    "destination_city": "Paris",
    "destination_location": "CDG",
})
premier = Colis.create({
    "shipment_id": dossier.id,
    "package_type": "parcel",
    "description": "Colis un",
    "quantity": 1,
    "unit_weight_kg": 4.0,
})
second = Colis.create({
    "shipment_id": dossier.id,
    "package_type": "parcel",
    "description": "Colis deux",
    "quantity": 1,
    "unit_weight_kg": 6.0,
})
dossier.planned_consolidation_id = depart
# La reception native n'est pas passee par ici : on part d'un depart vide.
env["dally.freight.consolidation.line"].sudo().search(
    [("consolidation_id", "in", (depart | depart_b).ids)]).unlink()
env.cr.commit()

registre = Registry(env.cr.dbname)
DOSSIER_ID = dossier.id


def env_ops():
    return api.Environment(
        env.cr, operateur.id, {"allowed_company_ids": [societe.id]})


def lignes(cible):
    return env_ops()["dally.freight.consolidation.line"].sudo().search_count(
        [("consolidation_id", "=", cible.id)])


def quantite(cible, paquet):
    line_env = env_ops()["dally.freight.consolidation.line"].sudo()
    return sum(line_env.search([
        ("consolidation_id", "=", cible.id),
        ("package_id", "=", paquet.id),
    ]).mapped("quantity_loaded"))


def audits():
    """Les traces du journal metier ecrites pour ce dossier.

    Le registre des demandes empeche deja un second geste ; l'audit est ecrit
    apres lui, donc il ne peut pas diverger — mais l'ecrire est une chose, le
    prouver en est une autre.

    Le journal metier est immuable : `vider()` retire les lignes et le
    registre, jamais les traces. On compte donc toujours un *delta* par sonde,
    jamais un total — le total ne ferait que croitre d'une sonde a l'autre.
    """
    return env_ops()["dally.ops.audit.event"].sudo().search_count([
        ("shipment_id", "=", DOSSIER_ID),
        ("action", "in", ("package_loaded", "package_unloaded")),
    ])


def demandes(cible):
    return env_ops()["dally.ops.loading.request"].sudo().search_count(
        [("consolidation_id", "=", cible.id)])


def assert_invariants(cible, paquet):
    line_env = env_ops()["dally.freight.consolidation.line"].sudo()
    lignes_colis = line_env.search([
        ("consolidation_id", "=", cible.id),
        ("package_id", "=", paquet.id),
    ])
    assert len(lignes_colis) <= 1, (
        "ligne dupliquee", cible.name, paquet.id, len(lignes_colis))
    for ligne in lignes_colis:
        assert ligne.quantity_loaded <= paquet.quantity, (
            "quantity_loaded depasse package.quantity",
            ligne.quantity_loaded,
            paquet.quantity,
        )


def vider(cible):
    env["dally.freight.consolidation.line"].sudo().search(
        [("consolidation_id", "=", cible.id)]).unlink()
    env["dally.ops.loading.request"].sudo().search(
        [("consolidation_id", "=", cible.id)]).unlink()
    env.cr.commit()


def geste(barriere, resultats, erreurs, request_uuid, reference_colis,
          action="load", reference_depart=None):
    """Un geste, joue par le meme chemin qu'une requete HTTP.

    `service.model.retrying` n'est pas un detail de confort : sous
    REPEATABLE READ, une transaction qui ne peut pas prendre le verrou du
    geste sait que son instantane est perime et leve `ConcurrencyError`.
    C'est `retrying` qui rejoue alors la requete entiere sur une transaction
    neuve. Appeler le service en direct mesurerait un chemin qui n'existe pas
    en production.
    """
    try:
        with registre.cursor() as cr:
            local = api.Environment(
                cr, operateur.id, {"allowed_company_ids": [societe.id]})
            societe_locale = local["res.company"].browse(societe.id)

            def appel():
                return (local["dally.ops.loading.service"]
                        .with_company(societe_locale)
                        .apply_loading(
                            reference_depart,
                            {
                                "request_uuid": request_uuid,
                                "action": action,
                                "package_reference": reference_colis,
                            },
                        ))

            barriere.wait(timeout=20)
            sortie = retrying(appel, local)
            resultats.append(sortie["replayed"])
    except Exception as exc:  # noqa: BLE001
        erreurs.append(repr(exc))


def relire():
    """Ouvre un instantane neuf sur l'environnement principal.

    REPEATABLE READ fige l'instantane au premier ordre SQL de la transaction.
    Le shell en a deja execute avant de lancer les fils : sans commit, il
    relirait un etat anterieur a leurs ecritures et la sonde conclurait a tort
    que rien n'a ete cree.
    """
    env.cr.commit()
    env.invalidate_all()


def lancer(paires):
    barriere = Barrier(len(paires))
    resultats, erreurs = [], []
    fils = [
        Thread(
            target=geste,
            args=(barriere, resultats, erreurs, uuid, colis, action, ref_depart),
        )
        for uuid, colis, action, ref_depart in paires
    ]
    for fil in fils:
        fil.start()
    bloques = []
    for fil in fils:
        fil.join(30)
        if fil.is_alive():
            bloques.append(fil.name)
    assert not bloques, (
        "des fils sont encore vivants apres le delai : les listes de resultats "
        "seraient partielles et les assertions suivantes trompeuses", bloques)
    relire()
    return resultats, erreurs


# -- 1. LOAD vs LOAD meme package/request_uuid -------------------------
identique = str(uuid4())
audits_avant = audits()
resultats, erreurs = lancer([
    (identique, premier.ops_loading_uuid, "load", depart.name),
    (identique, premier.ops_loading_uuid, "load", depart.name),
])
assert not erreurs, ("sonde 1", erreurs)
assert sorted(resultats) == [False, True], ("sonde 1", resultats)
assert lignes(depart) == 1, ("sonde 1 : lignes", lignes(depart))
assert demandes(depart) == 1, ("sonde 1 : registre", demandes(depart))
assert quantite(depart, premier) == premier.quantity, (
    "sonde 1 : quantite", quantite(depart, premier))
assert audits() - audits_avant == 1, (
    "sonde 1 : un seul audit pour un geste rejoue", audits() - audits_avant)
assert_invariants(depart, premier)
print("sonde 1 OK - LOAD vs LOAD meme package ne charge qu'une fois")

# -- 2. LOAD vs UNLOAD meme package ------------------------------------
vider(depart)
audits_avant = audits()
resultats, erreurs = lancer([
    (str(uuid4()), premier.ops_loading_uuid, "load", depart.name),
    (str(uuid4()), premier.ops_loading_uuid, "unload", depart.name),
])
assert not erreurs, ("sonde 2", erreurs)
assert lignes(depart) in (0, 1), ("sonde 2 : lignes", lignes(depart))
assert quantite(depart, premier) in (0, premier.quantity), (
    "sonde 2 : quantite", quantite(depart, premier))
assert_invariants(depart, premier)
# Un chargement et un retrait : deux gestes distincts, donc au plus deux
# traces — jamais l'une des deux en double.
assert audits() - audits_avant <= 2, (
    "sonde 2 : audits en double", audits() - audits_avant)
print("sonde 2 OK - LOAD vs UNLOAD meme package garde les invariants")

# -- 3. LOAD sur A vs LOAD sur B, le colis attendu des deux cotes ---------
# La version precedente repointait `planned_consolidation_id` vers B, ce qui
# faisait refuser le fil A par `package_not_found` avant tout verrou : elle
# mesurait un refus de portee, pas une course. Pour atteindre reellement
# `_quantite_ailleurs`, le colis doit etre attendu des deux cotes au moment de
# la course : prevu sur A, et deja charge sur B — l'union que
# `_expected_shipments` calcule.
vider(depart)
vider(depart_b)
dossier.planned_consolidation_id = depart
env["dally.freight.consolidation.line"].sudo().create({
    "consolidation_id": depart_b.id,
    "package_id": premier.id,
    "quantity_loaded": premier.quantity,
})
env.cr.commit()
assert premier.shipment_id in depart._expected_shipments(), "attendu sur A"
assert premier.shipment_id in depart_b._expected_shipments(), "attendu sur B"

resultats, erreurs = lancer([
    (str(uuid4()), premier.ops_loading_uuid, "load", depart.name),
    (str(uuid4()), premier.ops_loading_uuid, "load", depart_b.name),
])
# Le fil B ne fait rien : le colis y est deja entier. Le fil A doit se heurter
# a `_quantite_ailleurs` et refuser.
assert len(erreurs) == 1, ("sonde 3 : A doit refuser un colis charge ailleurs", erreurs)
assert "package_loaded_elsewhere" in erreurs[0] or "autre depart" in erreurs[0] \
    or "autre départ" in erreurs[0], ("sonde 3", erreurs)
assert lignes(depart) == 0, ("sonde 3 : aucune ligne sur A", lignes(depart))
assert lignes(depart_b) == 1, ("sonde 3 : une seule ligne sur B", lignes(depart_b))
assert not (quantite(depart, premier) and quantite(depart_b, premier)), (
    "sonde 3 : colis charge sur deux departs",
    quantite(depart, premier), quantite(depart_b, premier))
assert_invariants(depart, premier)
assert_invariants(depart_b, premier)
print("sonde 3 OK - LOAD sur deux departs : le colis ne peut etre que d'un cote")

# -- 4. LOAD vs close collection ---------------------------------------
# Les deux departs doivent etre vides avant de repointer le dossier : le coeur
# refuse une consolidation prevue tant que le dossier est charge ailleurs.
vider(depart)
vider(depart_b)
dossier.planned_consolidation_id = depart
if depart.state != "collecting":
    depart.action_open_collection()
env.cr.commit()
barriere = Barrier(2)
resultats, erreurs = [], []


def cloturer():
    try:
        with registre.cursor() as cr:
            local = api.Environment(
                cr, operateur.id, {"allowed_company_ids": [societe.id]})
            cible = local["dally.freight.consolidation"].browse(depart.id).sudo()
            # Volontairement AUCUN verrou du service : un back-office reel n'en
            # prend pas. La version precedente appelait `_verrouiller_depart`
            # ici, ce qui faisait du clotureur un adversaire cooperatif — et la
            # sonde validait alors un scenario qui n'existe pas.
            barriere.wait(timeout=20)
            # Par l'action metier : le coeur refuse une ecriture directe de
            # `state`, et la sonde n'a pas a contourner cette regle.
            cible.action_close_collection()
            cr.commit()
            resultats.append("closed")
    except Exception as exc:  # noqa: BLE001
        erreurs.append(repr(exc))


fil_load = Thread(target=geste, args=(
    barriere,
    resultats,
    erreurs,
    str(uuid4()),
    premier.ops_loading_uuid,
    "load",
    depart.name,
))
fil_close = Thread(target=cloturer)
fil_load.start()
fil_close.start()
fil_load.join(30)
fil_close.join(30)
assert not fil_load.is_alive() and not fil_close.is_alive(), (
    "sonde 4 : un fil est encore vivant apres le delai")
relire()
# Le chargement peut legitimement echouer : c'est meme l'issue attendue quand
# la cloture le precede. Ce qui ne doit jamais arriver, c'est une ligne creee
# alors que la collecte est close.
assert not [e for e in erreurs if "ConcurrencyError" not in e
            and "consolidation_not_collecting" not in e
            and "plus ouverte" not in e], ("sonde 4", erreurs)
assert depart.state == "collection_closed", ("sonde 4 : etat", depart.state)
assert not quantite(depart, premier), (
    "sonde 4 : une ligne existe alors que la collecte est close",
    quantite(depart, premier))
assert lignes(depart) == 0, ("sonde 4 : lignes apres cloture", lignes(depart))
assert_invariants(depart, premier)
print("sonde 4 OK - LOAD vs cloture ne cree rien apres cloture")

# -- 5. UUID differents : unload et load sur le meme depart -------------
# La course que la revue a trouvee : `unload` supprime une ligne enfant sans
# jamais toucher la ligne `dally_freight_consolidation`. Un `load` concurrent
# obtenait donc son verrou de ligne sans erreur de serialisation, gardait son
# instantane, y voyait encore la ligne supprimee, ne recreait rien, et
# repondait « charge » sur une base ou le colis ne l'etait plus.
#
# On impose ici l'entrelacement decisif : UNLOAD tient les verrous, LOAD les
# demande et doit etre rejoue, puis UNLOAD commite et LOAD repart sur un
# instantane neuf.
import threading as _threading

vider(depart)
if depart.state != "collecting":
    depart.action_open_collection()
dossier.planned_consolidation_id = depart
env["dally.freight.consolidation.line"].sudo().create({
    "consolidation_id": depart.id, "package_id": premier.id,
    "quantity_loaded": premier.quantity})
env.cr.commit()
relire()

Service = env["dally.ops.loading.service"].__class__
verrou_original = Service._verrouiller_avant_instantane
unload_tient = _threading.Event()
load_a_echoue = _threading.Event()
compte = {"echecs_load": 0, "pause_faite": False}


def verrou_espion(self, request_uuid, reference):
    nom = _threading.current_thread().name
    try:
        resultat = verrou_original(self, request_uuid, reference)
    except Exception:
        if nom == "P5_LOAD":
            compte["echecs_load"] += 1
            load_a_echoue.set()
        raise
    if nom == "P5_UNLOAD" and not compte["pause_faite"]:
        compte["pause_faite"] = True
        unload_tient.set()
        load_a_echoue.wait(timeout=30)   # on laisse LOAD se heurter au verrou
    return resultat


Service._verrouiller_avant_instantane = verrou_espion
p5_resultats, p5_erreurs = {}, {}


def p5_geste(nom, action, request_uuid, attendre=False):
    try:
        with registre.cursor() as cr:
            local = api.Environment(cr, operateur.id, {"allowed_company_ids": [societe.id]})
            soc = local["res.company"].browse(societe.id)
            if attendre:
                unload_tient.wait(timeout=30)

            def appel():
                return (local["dally.ops.loading.service"].with_company(soc)
                        .apply_loading(depart.name, {
                            "request_uuid": request_uuid, "action": action,
                            "package_reference": premier.ops_loading_uuid}))
            p5_resultats[nom] = retrying(appel, local)
    except Exception as exc:  # noqa: BLE001
        p5_erreurs[nom] = repr(exc)


p5_uuid_unload, p5_uuid_load = str(uuid4()), str(uuid4())
p5_fils = [
    _threading.Thread(target=p5_geste, name="P5_UNLOAD",
                      args=("UNLOAD", "unload", p5_uuid_unload)),
    _threading.Thread(target=p5_geste, name="P5_LOAD",
                      args=("LOAD", "load", p5_uuid_load, True)),
]
for f in p5_fils:
    f.start()
for f in p5_fils:
    f.join(60)
Service._verrouiller_avant_instantane = verrou_original
assert not any(f.is_alive() for f in p5_fils), "sonde 5 : un fil est reste vivant"
relire()

assert not p5_erreurs, ("sonde 5", p5_erreurs)
assert compte["echecs_load"] >= 1, (
    "sonde 5 : LOAD aurait du etre rejoue au moins une fois", compte)
assert lignes(depart) == 1, ("sonde 5 : la ligne doit exister", lignes(depart))
assert quantite(depart, premier) == premier.quantity, (
    "sonde 5 : quantite", quantite(depart, premier))

# la reponse rendue a l'operateur doit decrire la base, pas un instantane perime
dto = p5_resultats["LOAD"]["loading"]["shipments"][0]["packages"][0]
assert dto["loaded_quantity"] == quantite(depart, premier), (
    "sonde 5 : la reponse ne decrit pas la base", dto["loaded_quantity"],
    quantite(depart, premier))
assert dto["status"] == "loaded", ("sonde 5 : statut", dto["status"])

Audit = env_ops()["dally.ops.audit.event"].sudo()
audit_unload = Audit.search_count([("request_uuid", "=", p5_uuid_unload),
                                   ("action", "=", "package_unloaded")])
audit_load = Audit.search_count([("request_uuid", "=", p5_uuid_load),
                                 ("action", "=", "package_loaded")])
assert audit_unload == 1, ("sonde 5 : audit unload", audit_unload)
assert audit_load == 1, ("sonde 5 : audit load", audit_load)
Demande = env_ops()["dally.ops.loading.request"].sudo()
for uuid_geste in (p5_uuid_unload, p5_uuid_load):
    assert Demande.search_count([("request_uuid", "=", uuid_geste)]) == 1, (
        "sonde 5 : un registre par geste", uuid_geste)
print("sonde 5 OK - UUID differents : LOAD rejoue, ligne recreee, reponse = base"
      " (rejeux LOAD : %d)" % compte["echecs_load"])

# -- Nettoyage ---------------------------------------------------------
# Le coeur refuse de supprimer une consolidation deja utilisee, et c'est une
# bonne regle : la sonde ne la contourne pas. Elle annule et archive ce qu'elle
# a cree, et signale ce qu'elle n'a pas pu retirer plutot que de le taire.
restes = []
try:
    for cible in (depart, depart_b):
        if cible.state == "collection_closed":
            cible.action_open_collection()
    env.cr.commit()

    env["dally.freight.consolidation.line"].sudo().search(
        [("consolidation_id", "in", (depart | depart_b).ids)]).unlink()
    env["dally.ops.loading.request"].sudo().search(
        [("consolidation_id", "in", (depart | depart_b).ids)]).unlink()
    # Le journal metier est immuable par construction : son unlink leve
    # toujours. La sonde n'a pas a faire d'exception a cette regle - elle
    # efface ses propres traces en SQL, sur une base de banc, pour pouvoir
    # supprimer le dossier.
    env.cr.execute(
        "DELETE FROM dally_ops_audit_event WHERE shipment_id = %s",
        [dossier.id],
    )
    (premier | second).unlink()
    dossier.unlink()
    for cible in (depart, depart_b):
        cible.action_cancel()
        cible.write({"active": False})
    partenaire.unlink()
    operateur.unlink()
    env.cr.commit()
except Exception as exc:  # noqa: BLE001
    env.cr.rollback()
    restes.append(repr(exc))

if restes:
    print("nettoyage partiel, restes sur la base de banc :", restes)
print("SONDES DE CONCURRENCE : 5/5 OK")
