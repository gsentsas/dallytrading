"""Remet les fixtures MUTABLES de l'environnement E2E dans leur état initial.

## Pourquoi ce fichier existe

Deux specs Playwright écrivent réellement dans Odoo : `11-quote-decision` accepte
et refuse des devis, `10-profile-write` modifie un contact. Après une exécution,
ces données ne sont plus dans l'état que les specs supposent — la suite passait
une fois, sur une base fraîche, puis échouait à chaque relance.

Une suite qui ne passe que la première fois ne prouve rien de durable : on finit
par la relancer, la voir rouge, et conclure « c'est l'environnement ».

## Ce qu'il ne fait pas

Il ne remet pas TOUT à zéro. Chaque périmètre restaure uniquement les fixtures
de la spec qui les consomme, désignées par des clés stables — `request_uuid`
pour les devis, l'adresse e-mail pour le contact. Aucun périmètre ne dépend de
l'ordre des specs, ni de « la première ligne » de quoi que ce soit.

## Précondition, pas espoir

Après restauration, l'état est RELU depuis Odoo et vérifié. Le script n'imprime
`PRECONDITION_OK` que si tout est conforme ; le harness s'arrête sinon. Sans ce
contrôle, une restauration silencieusement incomplète produirait un échec
Playwright difficile à relier à sa cause — ce qui est exactement ce qui s'est
produit avant l'ajout de cette vérification.
"""

import os

env = env  # noqa: F821  (fourni par odoo shell)

SCOPE = os.environ.get("E2E_RESET_SCOPE", "all")

QUOTE_UUID_PREFIX = "e2e-quote-decision-"
CONTACT_A_EMAIL = "portal.a@e2e-a.invalid"
#: Valeurs posées par e2e-seed.py. Elles vivent ici en double, volontairement :
#: le seed crée, ce script restaure, et les deux doivent dire la même chose.
CONTACT_A_BASELINE = {
    "phone": "+221 70 000 00 01",
    "street": "1 rue Alpha",
    "street2": False,
    "zip": False,
    "city": "Dakar",
}

failures = []


def reset_quotes():
    quotes = env["dally.quote.request"].search([
        ("request_uuid", "=like", f"{QUOTE_UUID_PREFIX}%"),
    ])
    if not quotes:
        failures.append("aucun devis de décision : la base E2E n'est pas semée")
        return
    orders = env["sale.order"].search([
        ("dally_quote_request_id", "in", quotes.ids),
    ])
    # L'ordre compte : la commande doit être « sent » pour que le devis soit
    # décidable, et le devis doit repartir sans trace de décision précédente.
    orders.write({"state": "sent"})
    quotes.write({
        "state": "quoted",
        "customer_decision_at": False,
        "customer_decision_by_id": False,
        "customer_rejection_reason": False,
    })

    quotes.invalidate_recordset()
    for quote in quotes:
        if quote.state != "quoted":
            failures.append(f"{quote.reference} état={quote.state} au lieu de quoted")
        if quote.customer_decision_at:
            failures.append(f"{quote.reference} porte encore une décision")
        linked = env["sale.order"].search([
            ("dally_quote_request_id", "=", quote.id), ("state", "=", "sent"),
        ])
        if not linked:
            failures.append(f"{quote.reference} sans commande à l'état sent")
    print(f"RESET quotes={len(quotes)} orders={len(orders)}")


def reset_profile():
    contact = env["res.partner"].search([("email", "=", CONTACT_A_EMAIL)], limit=1)
    if not contact:
        failures.append("contact portail A introuvable")
        return
    contact.write(dict(CONTACT_A_BASELINE))
    contact.invalidate_recordset()
    for field, expected in CONTACT_A_BASELINE.items():
        actual = contact[field]
        if (actual or False) != (expected or False):
            failures.append(f"contact.{field}={actual!r} au lieu de {expected!r}")
    print(f"RESET profile={contact.email}")


if SCOPE in ("quotes", "all"):
    reset_quotes()
if SCOPE in ("profile", "all"):
    reset_profile()

env.cr.commit()

if failures:
    for failure in failures:
        print(f"PRECONDITION_FAIL {failure}")
else:
    print(f"PRECONDITION_OK {SCOPE}")
