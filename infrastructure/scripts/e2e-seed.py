"""
Comptes synthétiques pour la validation E2E du portail.

Aucune donnée client réelle. Les noms sont manifestement fictifs et les
adresses utilisent le TLD réservé `.invalid` (RFC 2606), qui ne peut pas
correspondre à un domaine existant.

Deux sociétés SANS AUCUN LIEN entre elles, plus un compte interne : c'est le
minimum pour que « A ne voit pas B » et « le personnel est refusé » soient des
affirmations vérifiables plutôt que des suppositions.
"""

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
    contact = env["res.partner"].create({
        "name": f"E2E Contact {label} (synthetique)",
        "parent_id": company.id,
        "email": f"portal.{label.lower()}@e2e-{label.lower()}.invalid",
        "city": company.city,
        "country_id": company.country_id.id,
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
