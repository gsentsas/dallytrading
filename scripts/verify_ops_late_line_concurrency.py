# -*- coding: utf-8 -*-
"""Sonde de concurrence DEV pour l'ajout d'un colis tardif.

Ce qu'aucun test transactionnel ne peut montrer : deux appareils qui envoient
le même geste au même instant. Odoo exécute chaque test dans une transaction
unique et annulée ; `pg_advisory_xact_lock` ne s'y oppose donc à personne, une
contrainte d'unicité ne se déclenche qu'au commit, et surtout un seul
instantané PostgreSQL est en jeu — or c'est précisément la coexistence de deux
instantanés qui fait le défaut. Il faut de vrais curseurs, de vrais commits, et
une barrière.

## Le contrat éprouvé

Ce n'est pas seulement « la base reste juste ». C'est aussi « les deux
appelants reçoivent une réponse qu'ils comprennent » :

1. **Même `request_uuid`, même charge** — reprise réseau, double appui. Un
   colis, un registre, et **les deux appelants reçoivent le même résultat** :
   le second rejoue celui du premier. Pas une erreur interne.

2. **Même `request_uuid`, charge différente** — deux gestes distincts qui
   réutilisent un identifiant. Un colis, et le perdant reçoit
   `idempotency_conflict` : sa demande n'est pas celle qui a été traitée.

3. **`request_uuid` différents, même `line_uuid`** — deux appareils qui
   décrivent le même article. Le verrou consultatif ne protège pas ce cas : il
   porte sur le `request_uuid`, qui diffère. C'est `UNIQUE(external_line_key)`
   qui tranche, et le perdant doit recevoir `line_reference_conflict` — un
   conflit métier, pas une panne.

4. Et, pour chacun, qu'aucun **complément en double** n'en découle.

À lancer dans un shell Odoo, sur une base de banc — jamais en production.
"""

from threading import Barrier, Thread
from time import time_ns
from uuid import uuid4

from odoo import api
from odoo.modules.registry import Registry
from odoo.service.model import retrying

PREFIXE = "AIR-DSS-CDG-2099-LATE-" + str(time_ns())
env = globals().get("env")
if env is None:
    raise RuntimeError("Cette sonde doit etre executee dans un shell Odoo.")

societe = env.company
registre = env.registry
base = env.cr.dbname

# Une base sans donnees de demonstration peut laisser EUR inactive. La sonde
# doit etre autonome : elle active temporairement la devise dont ses factures
# ont besoin, puis restaure l'etat initial au nettoyage.
euro = env.ref("base.EUR")
euro_etait_active = bool(euro.active)
if not euro_etait_active:
    euro.active = True
    env.cr.commit()


# ----------------------------------------------------------------------
# Le decor : un dossier facture, comptabilise
# ----------------------------------------------------------------------

def preparer():
    """Un dossier scénario tardif synthétique : une facture posted, et rien d'autre en attente.

    Chaque appel tire son propre depart : deux sondes successives ne doivent
    pas se disputer le meme nom de consolidation.
    """
    nom_depart = "%s-%s" % (PREFIXE, uuid4().hex[:6])
    famille = env["dally.freight.tariff.family"].search([("code", "=", "non_food")], limit=1)
    if not famille:
        famille = env["dally.freight.tariff.family"].create(
            {"name": "Sonde non_food", "code": "non_food"})
    if not env["dally.freight.tariff.rule"].search(
            [("family_id", "=", famille.id), ("transport_mode", "=", "air")], limit=1):
        env["dally.freight.tariff.rule"].create({
            "name": "Sonde non_food air", "transport_mode": "air",
            "family_id": famille.id, "customer_segment": "all",
            "price_per_kg_eur": 5.0,
        })
    partenaire = env["res.partner"].create({"name": "Client sonde %s" % nom_depart})
    consolidation = env["dally.freight.consolidation"].create({
        "name": nom_depart, "state": "collecting", "active": True,
        "company_id": societe.id, "transport_mode": "air", "direction": "export",
        "origin_country_id": env.ref("base.sn").id,
        "origin_city": "Dakar", "origin_location": "DSS",
        "destination_country_id": env.ref("base.fr").id,
        "destination_city": "Paris", "destination_location": "CDG",
    })
    operateur = env["res.users"].create({
        "name": "Sonde tardif",
        "login": "sonde.late.%s" % uuid4().hex[:8],
        "group_ids": [(6, 0, [
            env.ref("dally_ops_mobile.group_dally_ops_logistician").id])],
        "company_id": societe.id, "company_ids": [(6, 0, [societe.id])],
        "dally_ops_cash_actor": "Gilles",
    })
    poignee = env["dally.ops.customer.handle"].sudo().create({
        "partner_id": partenaire.id, "company_id": societe.id,
    })
    resultat = (env["dally.ops.intake.service"]
                .with_user(operateur).with_company(societe).create_intake({
                    "request_uuid": str(uuid4()),
                    "consolidation_reference": consolidation.name,
                    "customer_reference": poignee.token,
                    "received_on": "2026-08-29",
                    "line": {
                        "line_uuid": str(uuid4()), "package_type": "parcel",
                        "goods_category": "Non alimentaire",
                        "description": "Pagne et parfum", "quantity": 1,
                        "announced_weight_kg": None, "exact_weight_kg": 3.55,
                        "length_cm": None, "width_cm": None, "height_cm": None,
                        "billing_method": "real",
                        "tariff_family_code": famille.code,
                        "customs_value_xof": 25000,
                    },
                }))
    reference = resultat["intake"]["reference"]
    dossier = env["dally.shipment"].sudo().search(
        [("external_reference", "=", reference)], limit=1)
    facture = dossier.action_prepare_native_freight_invoice()
    facture.action_post()
    env.cr.commit()
    return reference, dossier, operateur, famille, facture


def charge(request_uuid, line_uuid, famille, poids=1.0):
    """La demande d'ajout tardif. `poids` distingue deux charges par ailleurs
    identiques — c'est ce qui fait du cas 2 un conflit d'empreinte."""
    return {
        "request_uuid": request_uuid,
        "line": {
            "line_uuid": line_uuid, "package_type": "parcel",
            "goods_category": "Non alimentaire", "description": "Creme cheveux",
            "quantity": 1, "announced_weight_kg": None, "exact_weight_kg": poids,
            "length_cm": None, "width_cm": None, "height_cm": None,
            "billing_method": "real", "tariff_family_code": famille.code,
            "customs_value_xof": 5000,
        },
    }


#: Toute attente de la sonde est bornée.
#:
#: `barriere.wait()` vient après l'ouverture du curseur et la construction de
#: l'environnement. Si l'une des deux lève dans un seul fil — pool épuisé, base
#: indisponible — l'autre attendrait la barrière sans fin, et `join()` avec lui.
#: La sonde resterait suspendue : aucun verdict, et surtout aucun nettoyage,
#: donc un banc laissé dans l'état que le nettoyage existe pour éviter.
DELAI = 120


def en_parallele(reference, operateur, charges):
    """Deux vrais curseurs, relâchés ensemble par une barrière."""
    barriere = Barrier(len(charges), timeout=DELAI)
    issues = []

    def executer(corps):
        """Exécute un appel concurrent dans son propre curseur et sa propre transaction."""
        with Registry(base).cursor() as cr:
            local = api.Environment(cr, operateur.id, {"allowed_company_ids": [societe.id]})

            def geste():
                """Effectue l'ajout tardif sous l'utilisateur de sonde courant."""
                return (local["dally.ops.intake.line.service"]
                        .with_company(societe).add_late_line(reference, corps))

            try:
                barriere.wait()
            except Exception as attente:                    # noqa: BLE001
                issues.append(("refus", "barriere:%s" % type(attente).__name__))
                return
            try:
                issues.append(("ok", retrying(geste, local)))
                cr.commit()
            except Exception as erreur:                     # noqa: BLE001
                # Le code metier, quand il y en a un : c'est lui qui dit si le
                # refus est comprehensible par l'appelant ou s'il est une panne.
                issues.append(("refus", getattr(erreur, "code", None)
                               or type(erreur).__name__))
                cr.rollback()

    fils = [Thread(target=executer, args=(corps,)) for corps in charges]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=DELAI)
    encore_en_vie = [f for f in fils if f.is_alive()]
    if encore_en_vie:
        raise RuntimeError(
            "%s fil(s) toujours actif(s) apres %ss : la sonde ne peut pas "
            "conclure." % (len(encore_en_vie), DELAI))
    return issues


def compter(dossier):
    # Odoo travaille en REPEATABLE READ : le snapshot PostgreSQL est fige au
    # premier acces de la transaction, et `invalidate_all()` ne le renouvelle
    # pas - il ne vide que le cache ORM. Sans ce rollback, on relirait la base
    # telle qu'elle etait AVANT les commits des deux fils, et la sonde
    # conclurait que rien ne s'est passe.
    """Relit les compteurs métier après commit avec un instantané PostgreSQL neuf."""
    env.cr.rollback()
    env.invalidate_all()
    frais = dossier.sudo().package_ids
    return {
        "colis": len(frais),
        "tardifs": len(frais) - 1,          # le dossier nait avec un colis
        "registres_tardifs": env["dally.ops.intake.line.request"].sudo()
        .search_count([("shipment_id", "=", dossier.id),
                       ("operation", "=", "add_late")]),
        "registres": env["dally.ops.intake.line.request"].sudo().search_count(
            [("shipment_id", "=", dossier.id)]),
        "so_complement": len(dossier.sudo()._supplement_orders()),
        "factures_complement": len(dossier.sudo()._supplement_invoices()),
    }


# ----------------------------------------------------------------------
# Le verdict, cas par cas
# ----------------------------------------------------------------------

resume = {}


#: Les pièces comptabilisées par la sonde, à défaire avant de rendre la main.
PIECES = []


def sonde(nom, etiquette, charges, refus_attendu, reussites_attendues):
    """Joue un cas, rend son verdict, et vérifie le contrat plutôt que le hasard."""
    reference, dossier, operateur, famille, facture = preparer()
    PIECES.append(facture)
    issues = en_parallele(reference, operateur, charges(famille))
    etat = compter(dossier)
    reussites = [i for i in issues if i[0] == "ok"]
    refus = [i[1] for i in issues if i[0] == "refus"]

    print("%s : tardifs=%s registres=%s reussites=%s refus=%s"
          % (etiquette, etat["tardifs"], etat["registres_tardifs"],
             len(reussites), refus))
    resume[nom] = (etat, len(reussites), refus)

    # Un seul article, quoi qu'il arrive : c'est l'invariant de base.
    assert etat["tardifs"] == 1, (etiquette, etat)
    assert etat["registres_tardifs"] == 1, (etiquette, etat)
    # Et le contrat de reponse : ni erreur interne, ni panne deguisee.
    assert len(reussites) == reussites_attendues, (etiquette, issues)
    assert refus == refus_attendu, (etiquette, refus)
    assert "DallyOpsInternal" not in refus, (etiquette, refus)
    return dossier


# 1. Meme geste, meme charge : les DEUX appelants doivent reussir, le second
#    en rejouant le resultat du premier.
uuid1, ligne1 = str(uuid4()), str(uuid4())
dossier1 = sonde(
    "same_request_same_payload", "cas 1 - meme uuid, meme charge",
    lambda f: [charge(uuid1, ligne1, f), charge(uuid1, ligne1, f)],
    refus_attendu=[], reussites_attendues=2)

# 2. Meme geste, charge differente : le perdant doit savoir POURQUOI.
uuid2, ligne2 = str(uuid4()), str(uuid4())
dossier2 = sonde(
    "same_request_different_payload", "cas 2 - meme uuid, charge differente",
    lambda f: [charge(uuid2, ligne2, f, poids=1.0),
               charge(uuid2, ligne2, f, poids=2.5)],
    refus_attendu=["idempotency_conflict"], reussites_attendues=1)

# 3. Gestes distincts, meme article : conflit metier, pas erreur interne.
ligne3 = str(uuid4())
dossier3 = sonde(
    "different_request_same_line", "cas 3 - uuid differents, meme article",
    lambda f: [charge(str(uuid4()), ligne3, f), charge(str(uuid4()), ligne3, f)],
    refus_attendu=["line_reference_conflict"], reussites_attendues=1)

# 4. Et aucun complement en double n'en decoule, dans les trois cas.
for etiquette, cible in (("cas 1", dossier1), ("cas 2", dossier2),
                         ("cas 3", dossier3)):
    cible.sudo()._prepare_freight_invoice()
    env.cr.commit()
    final = compter(cible)
    print("%s - complements : SO=%s facture=%s"
          % (etiquette, final["so_complement"], final["factures_complement"]))
    assert final["so_complement"] == 1, (etiquette, final)
    assert final["factures_complement"] == 1, (etiquette, final)

# ----------------------------------------------------------------------
# Nettoyage
# ----------------------------------------------------------------------

# La sonde commite : ce qu'elle laisse derrière elle vit sur le banc. Une
# facture comptabilisée en euros suffit à rendre la devise « déjà utilisée en
# comptabilité », ce qui fait échouer un test d'identité sans rapport, joué
# plus tard. Défaire les pièces n'est donc pas de la politesse : c'est éviter
# de fabriquer un rouge que la campagne suivante mettrait sur le dos du code.
# La devise se restaure dans un `finally`. Défaire les pièces peut échouer —
# une séquence comptable ou un verrou de facturation peut refuser la
# suppression — et le script s'arrêterait alors avant de rendre l'euro à son
# état d'origine. Il laisserait exactement le rouge sans rapport que ce
# nettoyage existe pour éviter, et sur un test qui n'a rien à voir avec lui.
try:
    pieces = env["account.move"].sudo().browse([])
    for cible in (dossier1, dossier2, dossier3):
        pieces |= cible.sudo()._supplement_invoices()
    for facture in PIECES:
        pieces |= facture
    pieces.filtered(lambda piece: piece.state == "posted").button_draft()
    pieces.filtered(lambda piece: piece.state != "cancel").button_cancel()
    pieces.unlink()
    env.cr.commit()
finally:
    if not euro_etait_active:
        euro.active = False
        env.cr.commit()

restantes = env["account.move.line"].sudo().search_count(
    [("currency_id.name", "=", "EUR")])
print("nettoyage : %s ligne(s) comptable(s) en EUR restantes" % restantes)

print()
print("SAME_REQUEST_SAME_PAYLOAD=%s reussites, refus=%s, colis tardifs=%s"
      % (resume["same_request_same_payload"][1],
         resume["same_request_same_payload"][2] or "aucun",
         resume["same_request_same_payload"][0]["tardifs"]))
print("SAME_REQUEST_DIFFERENT_PAYLOAD=%s reussite, refus=%s, colis tardifs=%s"
      % (resume["same_request_different_payload"][1],
         resume["same_request_different_payload"][2],
         resume["same_request_different_payload"][0]["tardifs"]))
print("DIFFERENT_REQUEST_SAME_LINE=%s reussite, refus=%s, colis tardifs=%s"
      % (resume["different_request_same_line"][1],
         resume["different_request_same_line"][2],
         resume["different_request_same_line"][0]["tardifs"]))
print("SUPPLEMENTS=SO 1, facture 1 pour les trois")
print("SONDES AJOUT TARDIF : 4/4 OK")
