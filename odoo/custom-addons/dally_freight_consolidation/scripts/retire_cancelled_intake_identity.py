#!/usr/bin/env python3
"""Retrait d'identité de collecte annulée — simulation par défaut.

À exécuter via ``odoo shell``. Sans ``--apply``, rien n'est écrit : le script
affiche le rapport de simulation et sort.

    odoo shell -d <base> --no-http < retire_cancelled_intake_identity.py

Pour appliquer, il faut le dire, et le dire deux fois — l'option et le nom de
la base :

    DALLY_RETIRE_APPLY=1 DALLY_RETIRE_DB=dallytrading \\
        odoo shell -d dallytrading --no-http < retire_cancelled_intake_identity.py

## Pourquoi les cibles sont écrites ici, en dur

Une maintenance qui accepte des identifiants en argument accepte aussi la
faute de frappe. Les deux dossiers à réparer sont connus, audités, et leur
état attendu est décrit ligne à ligne : le script compare la base à cette
description et refuse au moindre écart. Réparer un autre dossier demande de
modifier ce fichier, donc de le relire.
"""

import json
import os
import sys

# Les cibles, et ce que l'audit du 03/09/2026 a établi de chacune. Chaque
# valeur est une assertion : le service refuse si la base en diffère.
CIBLES = {
    842: {
        "company_id": 1,
        "intake_consolidation_id": 3,
        "planned_consolidation_id": 3,
        "external_reference": "AIR-DSS-CDG-2026-002-A034",
        "collection_local_ref": "A034",
        "collection_sequence": 34,
        "sync_source_key": "ops:06f594a0-31dd-411f-a4ab-9181e85f58f0",
        # Colis 384 « Valise chaussures et vêtements », 23,000 kg.
        "loaded_line_ids": [254],
    },
    843: {
        "company_id": 1,
        "intake_consolidation_id": 3,
        "planned_consolidation_id": 3,
        "external_reference": "AIR-DSS-CDG-2026-002-A035",
        "collection_local_ref": "A035",
        "collection_sequence": 35,
        "sync_source_key": "ops:dc122b5c-aedd-420f-b3a9-664f63ee301d",
        # Colis 385 Textile 21,300 / 386 Vaisselle 9,050 / 387 Vêtements 15,350.
        "loaded_line_ids": [255, 256, 257],
    },
}

BASE_ATTENDUE = "dallytrading"
VARIABLE_CIBLES = "DALLY_RETIRE_SHIPMENTS"


def _selection_cibles(appliquer):
    brut = os.environ.get(VARIABLE_CIBLES, "").strip()
    if not brut:
        # Sans sélection, on simule tout le périmètre audité : une simulation
        # n'écrit rien, et la voir en entier est précisément ce qu'on veut
        # avant d'autoriser quoi que ce soit. Appliquer, en revanche, exige de
        # nommer les dossiers un par un.
        if appliquer:
            raise ValueError(
                "%s doit nommer explicitement les dossiers à appliquer." % VARIABLE_CIBLES)
        return sorted(CIBLES)
    ids = []
    for morceau in brut.split(","):
        valeur = morceau.strip()
        if not valeur:
            continue
        try:
            identifiant = int(valeur)
        except ValueError as exc:
            raise ValueError("%s contient un identifiant invalide : %s" % (VARIABLE_CIBLES, valeur)) from exc
        if identifiant not in CIBLES:
            raise ValueError("%s n'est pas dans l'allowlist fermée." % identifiant)
        if identifiant not in ids:
            ids.append(identifiant)
    if not ids:
        raise ValueError("%s ne sélectionne aucun dossier." % VARIABLE_CIBLES)
    return ids


def principal(env):
    service = env["dally.freight.intake.identity.recovery"]
    appliquer = os.environ.get("DALLY_RETIRE_APPLY") == "1"
    base = os.environ.get("DALLY_RETIRE_DB") or ""
    try:
        ids = _selection_cibles(appliquer)
    except ValueError as erreur:
        print(str(erreur))
        return 1
    cibles = {identifiant: CIBLES[identifiant] for identifiant in ids}

    rapport = service.simulate(ids, expected=cibles)
    print(json.dumps(rapport, indent=2, ensure_ascii=False, default=str))

    if not rapport["dry_run_pass"]:
        print("\nDRY_RUN_PASS=NO — aucune écriture. Motifs ci-dessus.")
        return 1
    print("\nDRY_RUN_PASS=YES")

    if not appliquer:
        print("Mode simulation : rien n'a été écrit. "
              "Relancer avec DALLY_RETIRE_APPLY=1 pour appliquer.")
        return 0
    if base != BASE_ATTENDUE:
        print("DALLY_RETIRE_DB doit valoir « %s » pour appliquer." % BASE_ATTENDUE)
        return 1

    resultat = service.apply(ids, expected=cibles, database=BASE_ATTENDUE)
    env.cr.commit()
    print(json.dumps(resultat, indent=2, ensure_ascii=False, default=str))
    print("\nAPPLIED=YES")
    return 0


if "env" in globals():  # noqa: F821 — `odoo shell` injecte `env`.
    sys.exit(principal(env))  # noqa: F821
