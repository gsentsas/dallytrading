"""
Fixtures « groupage » pour la pile E2E fret. Exécuté par `odoo shell`.

S'ajoute aux graines fret et véhicule, et réutilise leurs sociétés et comptes
portail — trois définitions du « client A » vaudraient trois vérités.

## Ce qui est créé

* **GroupageSeaA** — maritime, décidable, trois colis distincts. Porte les
  canaris.
* **GroupageAirA** — aérien, décidable, colis distincts. Son existence est le
  cœur du scénario : c'est lui qui prouve que le mode aérien n'est pas ramené
  au maritime.
* **GroupageB** — appartient réellement au client B, pour que le cloisonnement
  porte sur une donnée existante.

Les trajets sont uniques dans toute la base d'essai : le discriminant d'un devis
est son trajet, et deux fixtures partageant une ville feraient échouer la spec
d'une autre — ce qui est arrivé deux fois lors du cycle véhicule.

## Canaris

`dally.quote.request.internal_notes` est réservé au personnel par `groups=`.
On y plante le marqueur textuel, et on lui adjoint un montant improbable dans
un champ interne du dossier : un `Monetary` ne peut pas porter de chaîne, et
scanner l'un sans l'autre laisserait la moitié du champ non couverte.
"""

env = env  # noqa: F821

CANARI_NOTE = "DALLY_E2E_SECRET_GROUPAGE_INTERNAL_NOTE"
#: Montant distinctif, cherché comme nombre dans les réponses navigateur.
CANARI_MONTANT = 876543.0

Partner = env["res.partner"]
company_a = Partner.search([("name", "=", "E2E Alpha SARL (synthetique)")], limit=1)
company_b = Partner.search([("name", "=", "E2E Beta SARL (synthetique)")], limit=1)
assert company_a and company_b, "societes synthetiques introuvables"

contact_a = company_a.child_ids[0]
contact_b = company_b.child_ids[0]
sn = env.ref("base.sn")

service = env["dally.service.type"].search([("code", "=", "freight_groupage")], limit=1)
assert service, "service freight_groupage introuvable"


def make_groupage_quote(contact, key, mode, origin, destination):
    quote = env["dally.quote.request"].create({
        "partner_id": contact.id,
        "service_type_id": service.id,
        "request_uuid": f"e2e-groupage-{key}",
        "goods_description": f"Marchandise groupee {key}",
        "origin_city": origin,
        "origin_country_id": sn.id,
        "destination_city": destination,
        "destination_country_id": sn.id,
        "groupage_transport_mode": mode,
        "state": "quoted",
    })
    env["sale.order"].create({
        "partner_id": contact.id,
        "dally_quote_request_id": quote.id,
        "state": "sent",
    })
    return quote


quote_sea = make_groupage_quote(contact_a, "sea-a", "sea", "Douala", "Ouagadougou")
quote_air = make_groupage_quote(contact_a, "air-a", "air", "Nairobi", "Bamako")
quote_b = make_groupage_quote(contact_b, "sea-b", "sea", "Tanger", "Niamey")

# Canaris sur le dossier maritime de A, dans un champ réservé au personnel.
quote_sea.write({
    "internal_notes": f"{CANARI_NOTE} — taux interne {CANARI_MONTANT}",
    "budget": "confidentiel",
})

interne = repr(quote_sea.sudo().read(["internal_notes"]))
assert CANARI_NOTE in interne, "le canari de note interne n'a pas ete plante"
assert "876543" in interne, "le canari de montant n'a pas ete plante"

env.cr.commit()

print(f"GROUPAGE_QUOTE_SEA_A={quote_sea.request_uuid}")
print(f"GROUPAGE_QUOTE_AIR_A={quote_air.request_uuid}")
print(f"GROUPAGE_QUOTE_B={quote_b.request_uuid}")
print("GROUPAGE_SEED_OK")
