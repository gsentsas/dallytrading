"""Comptes synthétiques pour la validation E2E du portail.

Aucune donnée client réelle. Les noms sont manifestement fictifs et les
adresses utilisent le TLD réservé `.invalid` (RFC 2606), qui ne peut pas
correspondre à un domaine existant.

Deux sociétés SANS AUCUN LIEN entre elles, plus un compte interne : c'est le
minimum pour que « A ne voit pas B » et « le personnel est refusé » soient des
affirmations vérifiables plutôt que des suppositions.

Ce script s'exécute UNE FOIS, sur une base neuve — c'est ce que fait
`e2e-portal.sh up`. Le relancer sur une base déjà remplie échoue sur l'unicité du
login, et c'est préférable à un script idempotent qui masquerait le fait que
l'environnement n'était pas dans l'état attendu.
"""

import base64

env = env  # noqa: F821  (fourni par odoo shell)

def pw(name):
    with open(f"/tmp/e2e-seed/pw-{name}", encoding="utf-8") as handle:
        return handle.read().strip()

portal_group = env.ref("base.group_portal")
internal_group = env.ref("base.group_user")

def make_company(label, city):
    return env["res.partner"].create({
        "name": f"E2E {label} SARL (synthetique)",
        "is_company": True,
        "email": f"contact@e2e-{label.lower()}.invalid",
        "city": city,
        "country_id": env.ref("base.sn").id,
    })

def make_portal_user(label, company):
    profile = {
        "A": {"phone": "+221 70 000 00 01", "street": "1 rue Alpha"},
        "B": {"phone": "+221 70 000 00 02", "street": "2 rue Beta"},
    }[label]
    contact = env["res.partner"].create({
        "name": f"E2E Contact {label} (synthetique)",
        "parent_id": company.id,
        "email": f"portal.{label.lower()}@e2e-{label.lower()}.invalid",
        "city": company.city,
        "country_id": company.country_id.id,
        "phone": profile["phone"],
        "street": profile["street"],
    })
    user = env["res.users"].create({
        "name": contact.name,
        "login": contact.email,
        "password": pw(label),
        "partner_id": contact.id,
        "group_ids": [(6, 0, [portal_group.id])],
    })
    return user

company_a = make_company("Alpha", "Dakar")
company_b = make_company("Beta", "Thies")
user_a = make_portal_user("A", company_a)
user_b = make_portal_user("B", company_b)

staff_partner = env["res.partner"].create({
    "name": "E2E Staff Interne (synthetique)",
    "email": "staff@e2e-interne.invalid",
})
staff = env["res.users"].create({
    "name": staff_partner.name,
    "login": staff_partner.email,
    "password": pw("STAFF"),
    "partner_id": staff_partner.id,
    "group_ids": [(6, 0, [internal_group.id])],
})

# Une donnée metier par societe, pour que « A ne voit pas B » porte sur du
# contenu reel et pas sur deux ensembles vides.
service = env["dally.service.type"].search([], limit=1)
for label, company, city in (("A", company_a, "Dakar"), ("B", company_b, "Thies")):
    env["dally.quote.request"].create({
        "partner_id": company.child_ids[0].id,
        "service_type_id": service.id,
        "request_uuid": f"e2e-quote-{label.lower()}",
        "goods_description": f"Marchandise synthetique visible uniquement par {label}",
        "message": f"Demande synthetique de la societe {label}",
    })
env.cr.commit()

print("SEED_OK")
print(f"A_LOGIN={user_a.login}")
print(f"B_LOGIN={user_b.login}")
print(f"STAFF_LOGIN={staff.login}")
print(f"A_SHARE={user_a.share} B_SHARE={user_b.share} STAFF_SHARE={staff.share}")
print(f"A_CPARTNER={user_a.partner_id.commercial_partner_id.name}")
print(f"B_CPARTNER={user_b.partner_id.commercial_partner_id.name}")

# ═══════════════════════════════════════════════════════════════════════
# DONNÉES MÉTIER SYNTHÉTIQUES, ET CANARIS
# ═══════════════════════════════════════════════════════════════════════
#
# Chaque société reçoit un dossier de chaque type. Les champs INTERDITS au
# portail reçoivent une valeur unique et reconnaissable : DALLY_E2E_SECRET_*.
#
# Vérifier des noms de champs ne suffirait pas. Un champ peut être renommé, une
# projection peut recopier une valeur sous un autre nom, un payload RSC peut
# transporter un objet entier. Un canari, lui, se cherche par sa VALEUR : s'il
# apparaît quelque part dans le HTML, le RSC, une réponse réseau, un fichier
# téléchargé ou un journal, il y a fuite — quel que soit le chemin emprunté.

def canary(kind, tag):
    return f"DALLY_E2E_SECRET_{kind}_{tag}"

# Références redérivées par recherche plutôt que reprises des variables
# ci-dessus : ce bloc peut ainsi être rejoué seul sur une base déjà peuplée en
# comptes, ce qui est exactement ce dont on a besoin pour le diagnostiquer.
Partner = env["res.partner"]
company_a = Partner.search([("name", "=", "E2E Alpha SARL (synthetique)")], limit=1)
company_b = Partner.search([("name", "=", "E2E Beta SARL (synthetique)")], limit=1)
service = env["dally.service.type"].search([], limit=1)
sn = env.ref("base.sn")
assert company_a and company_b, "societes synthetiques introuvables"

def make_decidable_quote(contact, label, key):
    """Devis synthétique réellement envoyé, jamais une donnée de production."""
    quote = env["dally.quote.request"].create({
        "partner_id": contact.id,
        "service_type_id": service.id,
        "request_uuid": f"e2e-quote-decision-{key}",
        "goods_description": f"Marchandise decision {label}",
        "quantity": "1 lot synthetique",
        "origin_city": label,
        "origin_country_id": sn.id,
        "destination_city": "Destination decision",
        "destination_country_id": sn.id,
        "state": "quoted",
    })
    env["sale.order"].create({
        "partner_id": contact.id,
        "dally_quote_request_id": quote.id,
        "state": "sent",
    })
    return quote

for tag, company in (("A", company_a), ("B", company_b)):
    contact = company.child_ids[0]

    # ── Devis ──
    env["dally.quote.request"].create({
        "partner_id": contact.id,
        "service_type_id": service.id,
        "request_uuid": f"e2e-quote-detail-{tag.lower()}",
        "goods_description": f"Marchandise synthetique {tag}",
        "quantity": f"12 cartons {tag}",
        "origin_city": f"Ville origine {tag}",
        "origin_country_id": sn.id,
        "destination_city": f"Ville destination {tag}",
        "destination_country_id": sn.id,
        "internal_notes": canary("INTERNAL_NOTE", tag),
    })

    if tag == "A":
        make_decidable_quote(contact, "Quote A Accept", "a-accept")
        make_decidable_quote(contact, "Quote A Reject", "a-reject")
        make_decidable_quote(contact, "Quote A Concurrent", "a-concurrent")
        make_decidable_quote(contact, "Quote A Security", "a-security")
    else:
        make_decidable_quote(contact, "Quote B Sent", "b-sent")

    # ── Sourcing + proposition envoyée ──
    sourcing = env["dally.sourcing.request"].create({
        "customer_id": contact.id,
        "product_name": f"Produit sourcing {tag}",
        "product_reference": f"REF-{tag}-001",
        "quantity": 250.0,
        "internal_notes": canary("SUPPLIER", tag),
    })
    # `customer_id` DOIT être posé explicitement.
    #
    # La record rule portail des propositions filtre sur
    # `customer_id.commercial_partner_id`. Le flux métier normal
    # (`_dally_draft_from_offer`) le recopie depuis la demande ; une création
    # directe comme celle-ci ne le fait pas, et la proposition devient invisible
    # de TOUS les clients — sans erreur. Constaté en E2E : le détail sourcing
    # renvoyait `"proposals": []` alors que la proposition existait bien en
    # état `sent`.
    #
    # Le défaut échoue fermé, donc il n'expose rien. Mais il vaut d'être connu :
    # tout import ou script qui créerait des propositions sans ce champ les
    # rendrait muettes côté client.
    proposal = env["dally.sourcing.proposal"].create({
        "request_id": sourcing.id,
        "customer_id": contact.id,
        "product_name": f"Produit sourcing {tag}",
        "quantity": 250.0,
        "selling_unit_price": 42.0,
        "commercial_terms": f"Conditions synthetiques {tag}",
        "cost_basis": 30.0,
    })
    # `state` est un workflow : on l'écrit directement, le but est d'obtenir une
    # proposition VISIBLE du portail (record rule : sent/accepted/rejected/expired).
    proposal.write({"state": "sent"})

    # Une seconde proposition laissée en BROUILLON : elle ne doit jamais
    # apparaître côté client, et son prix est un canari.
    env["dally.sourcing.proposal"].create({
        "request_id": sourcing.id,
        "customer_id": contact.id,
        "product_name": canary("DRAFT_PROPOSAL", tag),
        "quantity": 10.0,
        "selling_unit_price": 999.0,
        "commercial_terms": canary("DRAFT_TERMS", tag),
    })

    # ── Trading ──
    env["dally.trade.opportunity"].create({
        "name": f"Operation synthetique {tag}",
        "customer_id": contact.id,
        "operation_type": "purchase_resale",
        "internal_notes": canary("MARGIN", tag),
    })

    # ── Expédition, colis et événements ──
    shipment = env["dally.shipment"].create({
        "partner_id": contact.id,
        "transport_mode": "sea",
        "origin_city": f"Port origine {tag}",
        "origin_country_id": sn.id,
        "destination_city": f"Port destination {tag}",
        "destination_country_id": sn.id,
        "goods_description": f"Fret synthetique {tag}",
        "internal_notes": canary("SHIPMENT_NOTE", tag),
        "supplier_cost": 1234.0,
    })
    env["dally.shipment.package"].create({
        "shipment_id": shipment.id,
        "package_type": "crate",
        "description": f"Colis synthetique {tag}",
        "quantity": 4,
        "unit_weight_kg": 12.5,
    })
    env["dally.shipment.event"].create({
        "shipment_id": shipment.id,
        "status": "in_transit",
        "location": f"Escale {tag}",
        "description": f"Evenement public {tag}",
        "visible_to_customer": True,
    })
    # Événement INTERNE : jamais visible du client, description canarisée.
    env["dally.shipment.event"].create({
        "shipment_id": shipment.id,
        "status": "in_transit",
        "location": f"Escale interne {tag}",
        "description": canary("INTERNAL_EVENT", tag),
        "internal_note": canary("EVENT_NOTE", tag),
        "visible_to_customer": False,
    })

    # ── Documents : un publié, un non publié ──
    published_attachment = env["ir.attachment"].create({
        "name": f"document-{tag.lower()}.txt",
        "datas": base64.b64encode(
            f"CONTENU DOCUMENT {tag} — societe {company.name}".encode()
        ),
    })
    published = env["dally.portal.document"].create({
        "name": f"Document publie {tag}",
        "attachment_id": published_attachment.id,
        "document_type": "other",
        "shipment_id": shipment.id,
    })
    published.action_publish()

    hidden_attachment = env["ir.attachment"].create({
        "name": f"non-publie-{tag.lower()}.txt",
        "datas": base64.b64encode(canary("UNPUBLISHED_DOC", tag).encode()),
    })
    env["dally.portal.document"].create({
        "name": canary("UNPUBLISHED_NAME", tag),
        "attachment_id": hidden_attachment.id,
        "document_type": "other",
        "shipment_id": shipment.id,
    })

env.cr.commit()

print("BUSINESS_SEED_OK")
for tag in ("A", "B"):
    print(f"CANARIES_{tag}=" + ",".join(
        canary(kind, tag) for kind in (
            "INTERNAL_NOTE", "SUPPLIER", "MARGIN", "SHIPMENT_NOTE",
            "INTERNAL_EVENT", "EVENT_NOTE", "DRAFT_PROPOSAL", "DRAFT_TERMS",
            "UNPUBLISHED_DOC", "UNPUBLISHED_NAME",
        )
    ))
for tag, company in (("A", company_a), ("B", company_b)):
    contact = company.child_ids[0]
    for model, field in (
        ("dally.quote.request", "partner_id"),
        ("dally.sourcing.request", "customer_id"),
        ("dally.trade.opportunity", "customer_id"),
        ("dally.shipment", "partner_id"),
    ):
        rec = env[model].search([(field, "=", contact.id)], limit=1, order="id desc")
        print(f"REF_{tag}_{model.split('.')[-1]}={rec.reference}")
    doc = env["dally.portal.document"].search(
        [("commercial_partner_id", "=", company.id),
         ("published_to_portal", "=", True)], limit=1)
    print(f"REF_{tag}_document=DOC-{doc.id}")
