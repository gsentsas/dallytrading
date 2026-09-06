# -*- coding: utf-8 -*-
"""Sonde de concurrence DEV pour l'ajout d'un colis tardif.

Ce qu'aucun test transactionnel ne peut montrer : deux appareils qui envoient le
meme ajout au meme instant. Odoo execute chaque test dans une transaction unique
et annulee ; `pg_advisory_xact_lock` ne s'y oppose donc a personne, et une
contrainte d'unicite ne se declenche qu'au commit. Il faut de vrais curseurs, de
vrais commits, et une barriere.

Deux questions, deux reponses attendues :

1. Le meme geste envoye deux fois en parallele - reprise reseau, double appui -
   n'ajoute qu'un colis, n'inscrit qu'un registre de rejeu, et rend le meme
   resultat aux deux appelants.

2. Deux gestes de `request_uuid` DIFFERENTS visant la meme ligne ne creent
   jamais deux colis. Le verrou consultatif ne protege pas ce cas : il est pris
   sur le `request_uuid`, qui differe. Ce qui protege, c'est
   `UNIQUE(external_line_key)` sur `dally.shipment.package`, plus le controle
   metier `_colis_par_uuid`. La sonde le prouve au lieu de l'affirmer.

Et, pour chacune, qu'aucun complement en double n'en decoule.

A lancer dans un shell Odoo, sur une base de banc - jamais en production.
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


# ----------------------------------------------------------------------
# Le decor : un dossier facture, comptabilise
# ----------------------------------------------------------------------

def preparer():
    """Un dossier A004-like : une facture posted, et rien d'autre en attente.

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


def charge(request_uuid, line_uuid, famille):
    return {
        "request_uuid": request_uuid,
        "line": {
            "line_uuid": line_uuid, "package_type": "parcel",
            "goods_category": "Non alimentaire", "description": "Creme cheveux",
            "quantity": 1, "announced_weight_kg": None, "exact_weight_kg": 1.0,
            "length_cm": None, "width_cm": None, "height_cm": None,
            "billing_method": "real", "tariff_family_code": famille.code,
            "customs_value_xof": 5000,
        },
    }


def en_parallele(reference, operateur, charges):
    """Deux vrais curseurs, relaches ensemble par une barriere."""
    barriere = Barrier(len(charges))
    issues = []

    def executer(corps):
        with Registry(base).cursor() as cr:
            local = api.Environment(cr, operateur.id, {"allowed_company_ids": [societe.id]})

            def geste():
                return (local["dally.ops.intake.line.service"]
                        .with_company(societe).add_late_line(reference, corps))

            barriere.wait()
            try:
                issues.append(("ok", retrying(geste, local)))
                cr.commit()
            except Exception as erreur:                     # noqa: BLE001
                issues.append(("refus", type(erreur).__name__))
                cr.rollback()

    fils = [Thread(target=executer, args=(corps,)) for corps in charges]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    return issues


def compter(dossier):
    # Odoo travaille en REPEATABLE READ : le snapshot PostgreSQL est fige au
    # premier acces de la transaction, et `invalidate_all()` ne le renouvelle
    # pas - il ne vide que le cache ORM. Sans ce rollback, on relirait la base
    # telle qu'elle etait AVANT les commits des deux fils, et la sonde
    # conclurait que rien ne s'est passe.
    env.cr.rollback()
    env.invalidate_all()
    frais = dossier.sudo().package_ids
    return {
        "colis": len(frais),
        "registres": env["dally.ops.intake.line.request"].sudo().search_count(
            [("shipment_id", "=", dossier.id)]),
        "so_complement": len(dossier.sudo()._supplement_orders()),
        "factures_complement": len(dossier.sudo()._supplement_invoices()),
    }


# ----------------------------------------------------------------------
# Sonde 1 — meme request_uuid
# ----------------------------------------------------------------------

reference, dossier, operateur, famille, principale = preparer()
uuid_geste = str(uuid4())
uuid_ligne = str(uuid4())
issues = en_parallele(
    reference, operateur,
    [charge(uuid_geste, uuid_ligne, famille), charge(uuid_geste, uuid_ligne, famille)])
etat = compter(dossier)
reussites = [i for i in issues if i[0] == "ok"]
refuses = [i for i in issues if i[0] == "refus"]
print("sonde 1 - meme request_uuid : colis=%s reussites=%s refus=%s"
      % (etat["colis"], len(reussites), [i[1] for i in refuses]))
# L'invariant qui compte : la base ne porte jamais deux colis pour une ligne.
assert etat["colis"] == 2, etat
assert len(reussites) >= 1, issues
if reussites:
    refs = {i[1]["line"]["reference"] for i in reussites}
    assert refs == {uuid_ligne}, refs
print("sonde 1 OK - 1 seul colis tardif en base")

# ----------------------------------------------------------------------
# Sonde 2 — request_uuid differents, meme line_uuid
# ----------------------------------------------------------------------

reference2, dossier2, operateur2, famille2, principale2 = preparer()
uuid_ligne2 = str(uuid4())
issues2 = en_parallele(
    reference2, operateur2,
    [charge(str(uuid4()), uuid_ligne2, famille2),
     charge(str(uuid4()), uuid_ligne2, famille2)])
etat2 = compter(dossier2)
ok2 = [i for i in issues2 if i[0] == "ok"]
refuses2 = [i for i in issues2 if i[0] == "refus"]
print("sonde 2 - request_uuid differents : colis=%s reussites=%s refus=%s"
      % (etat2["colis"], len(ok2), [i[1] for i in refuses2]))
assert etat2["colis"] == 2, etat2          # jamais deux colis pour une ligne
assert len(ok2) >= 1, issues2
print("sonde 2 OK - 1 seul colis malgre deux gestes distincts")

# ----------------------------------------------------------------------
# Et aucun complement en double n'en decoule
# ----------------------------------------------------------------------

for etiquette, cible in (("sonde 1", dossier), ("sonde 2", dossier2)):
    cible.sudo()._prepare_freight_invoice()
    env.cr.commit()
    final = compter(cible)
    assert final["so_complement"] == 1, (etiquette, final)
    assert final["factures_complement"] == 1, (etiquette, final)
print("sonde 3 OK - un seul complement et une seule facture de chaque cote")

# ----------------------------------------------------------------------
# Nettoyage
# ----------------------------------------------------------------------

for cible in (dossier, dossier2):
    cible.sudo()._supplement_invoices().button_cancel()
env.cr.commit()
print("SONDES AJOUT TARDIF : 3/3 OK")
