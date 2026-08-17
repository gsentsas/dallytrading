"""
Fixtures « transport de véhicule » pour la pile E2E fret. Exécuté par `odoo shell`.

S'ajoute à `e2e-freight-seed.py` et réutilise ses sociétés et ses comptes portail :
les redéfinir créerait deux vérités sur « qui est le client A ».

## Ce qui est créé, et pourquoi

* **VehicleSeaA** — un devis véhicule maritime, décidable par le navigateur. Il
  porte les canaris. C'est le dossier central du scénario.
* **VehicleB** — un dossier véhicule appartenant réellement au client B. Il
  existe pour que le test de cloisonnement porte sur une donnée réelle : une
  référence inventée ne prouverait que l'absence de cette référence, pas
  l'existence d'une barrière.

Le formulaire public, lui, ne reçoit **aucune** fixture ici : la spec le remplit
elle-même dans le navigateur, ce qui est précisément ce qu'elle doit prouver.

## Le VIN de test

Unique et reconnaissable — il sert aussi de sonde. On le cherche ensuite dans
les journaux et dans le suivi public, où il ne doit jamais apparaître. Un VIN
banal rendrait ce balayage impossible à interpréter.
"""

import uuid as _uuid

env = env  # noqa: F821  (fourni par odoo shell)

#: VIN synthétique du dossier A. Sert de sonde de fuite.
VIN_A = "DALLYE2EVIN000001"
#: VIN synthétique du dossier B, distinct.
VIN_B = "DALLYE2EVIN000002"

CANARI_NOTE = "DALLY_E2E_SECRET_VEHICLE_INTERNAL_NOTE"
CANARI_PRIX = "DALLY_E2E_SECRET_VEHICLE_PURCHASE_PRICE"

#: Valeur numérique distinctive du prix d'achat.
#:
#: `purchase_price` est un `Monetary` : il ne peut pas porter un marqueur
#: textuel. On combine donc les deux — un montant improbable, cherché comme
#: nombre, et un marqueur textuel dans les notes internes, cherché comme chaîne.
#: Scanner l'un sans l'autre laisserait une moitié du champ non couverte.
PRIX_CANARI = 987654.0

Partner = env["res.partner"]
company_a = Partner.search([("name", "=", "E2E Alpha SARL (synthetique)")], limit=1)
company_b = Partner.search([("name", "=", "E2E Beta SARL (synthetique)")], limit=1)
assert company_a and company_b, "societes synthetiques introuvables : lancer e2e-seed.py d'abord"

contact_a = company_a.child_ids[0]
contact_b = company_b.child_ids[0]
sn = env.ref("base.sn")

service = env["dally.service.type"].search([("code", "=", "freight_vehicle")], limit=1)
assert service, "service freight_vehicle introuvable"


def make_vehicle_quote(contact, key, label, origin, destination):
    """Devis véhicule réellement décidable : un `sale.order` en état `sent`."""
    quote = env["dally.quote.request"].create({
        "partner_id": contact.id,
        "service_type_id": service.id,
        "request_uuid": f"e2e-vehicle-{key}",
        "goods_description": f"Vehicule {label}",
        "origin_city": origin,
        "origin_country_id": sn.id,
        "destination_city": destination,
        "destination_country_id": sn.id,
        "state": "quoted",
    })
    env["sale.order"].create({
        "partner_id": contact.id,
        "dally_quote_request_id": quote.id,
        "state": "sent",
    })
    return quote


# ── Dossier A : maritime, décidable, porteur des canaris ─────────────────
quote_a = make_vehicle_quote(contact_a, "sea-a", "SEA A", "Bordeaux", "Conakry")
cargo_a = env["dally.freight.vehicle.cargo"].sudo().create({
    "quote_request_id": quote_a.id,
    "make": "Toyota",
    "model": "Land Cruiser",
    "year": "2018",
    "vin": VIN_A,
    "registration": "E2E-AA-001",
    "color": "Blanc",
    "category": "suv",
    "condition": "running",
    "fuel": "diesel",
    "key_count": 2,
    "transport_mode": "sea",
    "pickup_requested": True,
    "pickup_address": "1 rue Alpha, Bordeaux",
    "delivery_requested": False,
    "internal_notes": f"{CANARI_NOTE} — arbitrage interne",
    "purchase_price": PRIX_CANARI,
})

# ── Dossier B : appartient réellement au client B ────────────────────────
#
# Nécessaire pour que le cloisonnement soit prouvé sur une donnée existante.
quote_b = make_vehicle_quote(contact_b, "sea-b", "SEA B", "Lome", "Cotonou")
cargo_b = env["dally.freight.vehicle.cargo"].sudo().create({
    "quote_request_id": quote_b.id,
    "make": "Renault",
    "model": "Duster",
    "year": "2020",
    "vin": VIN_B,
    "registration": "E2E-BB-002",
    "color": "Gris",
    "category": "suv",
    "condition": "running",
    "transport_mode": "sea",
})

# ── Contrôle positif : les canaris existent réellement ───────────────────
#
# Sans ce bloc, leur absence côté client signifierait peut-être seulement
# qu'aucun canari n'a jamais été planté.
interne = repr(cargo_a.sudo().read(["internal_notes", "purchase_price", "vin"]))
assert CANARI_NOTE in interne, "le canari de note interne n'a pas ete plante"
assert "987654" in interne, "le canari de prix d'achat n'a pas ete plante"
assert VIN_A in interne, "le VIN de fixture n'a pas ete plante"

# ── Clé d'API pour le formulaire PUBLIC ──────────────────────────────────
#
# Le harness fret a été bâti pour le portail, qui s'authentifie par session.
# Le formulaire public, lui, passe par une clé d'API serveur — et la pile n'en
# avait qu'un placeholder explicitement marqué « unused ». Résultat mesuré : la
# page /devis affichait « Formulaire momentanément indisponible », faute de
# pouvoir charger le catalogue de services.
#
# On en provisionne donc une vraie, portée par l'utilisateur d'intégration déjà
# livré par `dally_api`. Elle est éphémère et propre à cette base jetable.
integration = env.ref("dally_api.user_dally_api_integration")
cle = env["dally.api.key"].sudo().create({
    "name": "E2E vehicle public form",
    "user_id": integration.id,
    "scopes": "services:read,leads:write,quotes:write,tracking:read",
})
cle.action_generate_key()
cle_brute = cle.key_to_display
assert cle_brute, "la generation de cle n'a rien produit"

env.cr.commit()

print(f"VEHICLE_API_KEY={cle_brute}")
print(f"VEHICLE_QUOTE_SEA_A={quote_a.request_uuid}")
print(f"VEHICLE_QUOTE_B={quote_b.request_uuid}")
print(f"VEHICLE_VIN_A={VIN_A}")
print(f"VEHICLE_VIN_B={VIN_B}")
print(f"VEHICLE_REGISTRATION_A={cargo_a.registration}")
print("VEHICLE_SEED_OK")
