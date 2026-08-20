"""
Fixtures fret pour la pile E2E jetable. Exécuté par `odoo shell`.

S'ajoute à `e2e-seed.py` plutôt que de le remplacer : les sociétés, contacts et
comptes portail A/B viennent de là, et les redéfinir créerait deux vérités sur
« qui est le client A ».

## Ce qui est créé, et pourquoi dans cet ordre

Trois devis **décidables** par le navigateur, restaurés entre les passages :

* `SEA` et `AIR` pour le client A — deux modes, pour prouver qu'aucun repli
  maritime ne subsiste ;
* un devis pour le client B, qui ne doit jamais apparaître chez A.

Et **un dossier déjà provisionné** pour A, enrichi de colis, d'un événement de
suivi, d'un document interne et d'un document publié.

Ce dossier existe parce qu'un colis, un événement et un document n'apparaissent
qu'*après* la création de l'expédition : les faire naître au milieu du scénario
navigateur obligerait à interrompre la session pour muter Odoo, ce qui est
exactement la manœuvre qui a déjà produit de faux négatifs. Le scénario
d'acceptation valide donc la chaîne devis → expédition, et ce dossier stable
valide le contenu du détail. Il est lu, jamais modifié, donc rejouable tel quel.

## Canaris

Ils sont plantés dans des champs **réellement internes**, et un contrôle positif
vérifie qu'ils y sont. Un canari absent du portail ne prouve rien tant qu'on n'a
pas prouvé qu'il existait en amont — l'erreur a déjà été commise dans ce
chantier, sur un comptage à zéro lu comme une barrière qui tenait.
"""

import base64

env = env  # noqa: F821  (fourni par odoo shell)


def canary(kind):
    """Marqueur unique, cherché par sa VALEUR et non par un nom de champ."""
    return f"DALLY_E2E_SECRET_{kind}"


CANARIS = {
    "cost": canary("VENDOR_COST"),
    "margin": canary("MARGIN"),
    "supplier": canary("SUPPLIER"),
    "commission": canary("COMMISSION"),
    "note": canary("INTERNAL_NOTE"),
    "document": canary("INTERNAL_DOCUMENT"),
}

Partner = env["res.partner"]
company_a = Partner.search([("name", "=", "E2E Alpha SARL (synthetique)")], limit=1)
company_b = Partner.search([("name", "=", "E2E Beta SARL (synthetique)")], limit=1)
assert company_a and company_b, "societes synthetiques introuvables : lancer e2e-seed.py d'abord"

contact_a = company_a.child_ids[0]
contact_b = company_b.child_ids[0]
sn = env.ref("base.sn")

ServiceType = env["dally.service.type"]
service_sea = ServiceType.search([("code", "=", "freight_sea")], limit=1)
service_air = ServiceType.search([("code", "=", "freight_air")], limit=1)
assert service_sea and service_air, "services fret maritime/aerien introuvables"


def make_freight_quote(contact, key, label, service, origin, destination):
    """Devis fret réellement décidable : un `sale.order` en état `sent`.

    `request_uuid` est l'identifiant stable qui permet de retrouver et de
    restaurer ce devis entre deux passages, sans jamais dépendre d'un « premier
    enregistrement » ou d'un ordre de tri.
    """
    quote = env["dally.quote.request"].create({
        "partner_id": contact.id,
        "service_type_id": service.id,
        "request_uuid": f"e2e-freight-{key}",
        "goods_description": f"Marchandise fret {label}",
        "quantity": "1 lot synthetique",
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


# ── Devis décidables par le navigateur ────────────────────────────────────
quote_sea = make_freight_quote(
    contact_a, "sea-a", "Freight A SEA", service_sea, "Dakar", "Abidjan"
)
quote_air = make_freight_quote(
    contact_a, "air-a", "Freight A AIR", service_air, "Paris", "Dakar"
)
quote_b = make_freight_quote(
    contact_b, "sea-b", "Freight B SEA", service_sea, "Lome", "Cotonou"
)

# Devis dédié à la concurrence : il ne peut pas partager celui du scénario SEA,
# qui l'a déjà consommé quand ce test s'exécute.
quote_conc = make_freight_quote(
    contact_a, "conc-a", "Freight A CONC", service_sea, "Dakar", "Banjul"
)

# ── Dossier déjà provisionné et enrichi, pour le contenu du détail ────────
quote_detail = make_freight_quote(
    contact_a, "detail-a", "Freight A DETAIL", service_sea, "Dakar", "Casablanca"
)
quote_detail.write({"state": "won"})

booking = env["shipment.freight.booking"].sudo().search(
    [("dally_quote_request_id", "=", quote_detail.id)], limit=1
)
assert booking, "le devis enrichi n'a pas provisionne de booking"
expedition = env["freight.shipment"].sudo().search(
    [("booking_id", "=", booking.id)], limit=1
)
projection = env["dally.shipment"].sudo().search(
    [("tk_shipment_id", "=", expedition.id)], limit=1
)
assert expedition and projection, "chaine fret incomplete pour le dossier enrichi"

# Le lot Freight Pro installe ensuite une politique globale qui masque aux
# utilisateurs externes les états non publiables. Une projection laissée en
# `draft` serait donc correctement cachée, ce qui rendrait cette fixture de
# détail illisible au portail malgré ses colis, événements et documents.
#
# On fait passer la fixture par l'action canonique vers un jalon réellement
# client (`in_transit`) AVANT l'installation du module de politique. Au moment
# où son champ stocké `dally_portal_visible` sera créé/recalculé, la fixture
# sera donc visible pour la bonne raison métier — jamais par contournement de
# règle d'accès.
projection.action_set_state("in_transit")
assert projection.state == "in_transit", "le dossier enrichi n'est pas passe en transit"

# Canaris dans les champs internes du dossier opérationnel du fournisseur.
valeurs_internes = {}
for champ in ("notes", "dangerous_goods_notes"):
    if champ in expedition._fields:
        valeurs_internes[champ] = (
            f"{CANARIS['cost']} {CANARIS['margin']} {CANARIS['supplier']} "
            f"{CANARIS['commission']} {CANARIS['note']}"
        )
expedition.sudo().write(valeurs_internes)

# Et dans les champs internes de la projection Dally, qui existent sur le
# modèle et ne doivent jamais sortir.
projection.sudo().write({
    "internal_notes": f"{CANARIS['note']} {CANARIS['margin']}",
    "supplier_cost": 4242.0,
    "margin": 1337.0,
})

# ── Colis, réellement visible côté client ────────────────────────────────
env["shipment.package.line"].sudo().create({
    "shipment_id": expedition.id,
    "qty": 3,
    "net_weight": 18.5,
    "length": 120.0,
    "width": 80.0,
    "height": 90.0,
    # Montant interne du fournisseur : il ne doit apparaître dans aucune
    # projection client.
    "charges": 999.0,
})

# Le colis vient d'être créé côté opérationnel, donc APRÈS la synchronisation
# déclenchée par le provisionnement : sans ce rappel, il n'existerait jamais
# côté client. C'est l'ordre réel en exploitation — l'expédition naît d'abord,
# les colis sont saisis ensuite.
projection._dally_freight_sync_from_tk()

# ── Événement de suivi, publié explicitement ─────────────────────────────
#
# La synchronisation crée les événements fermés par défaut. Ici on publie
# volontairement, parce que le scénario doit prouver qu'un événement publié
# *apparaît* — sans quoi son absence ne prouverait rien.
env["dally.shipment.event"].sudo().create({
    "shipment_id": projection.id,
    "event_date": "2026-08-16 09:00:00",
    "status": "in_transit",
    "location": "Port de Dakar",
    "description": "Chargement effectue",
    "internal_note": CANARIS["note"],
    "visible_to_customer": True,
})
env["dally.shipment.event"].sudo().create({
    "shipment_id": projection.id,
    "event_date": "2026-08-16 11:00:00",
    "status": "in_transit",
    "location": "Arbitrage interne",
    "description": f"Evenement interne {CANARIS['note']}",
    "visible_to_customer": False,
})

# ── Documents : un interne, un publié ────────────────────────────────────
document_interne = env["freight.documents"].sudo().create({
    "freight_id": expedition.id,
    "file_name": f"{CANARIS['document']}-arbitrage.pdf",
    "document": base64.b64encode(CANARIS["document"].encode()).decode(),
})
document_publie = env["freight.documents"].sudo().create({
    "freight_id": expedition.id,
    "file_name": "connaissement-e2e.pdf",
    "document": base64.b64encode(b"DALLY_E2E_PUBLISHED_DOCUMENT_BODY").decode(),
})
publication = document_publie.dally_publish_to_portal()
assert publication, "la publication du document n'a rien produit"

# ── Contrôle positif : les canaris existent réellement ───────────────────
#
# Sans ce bloc, l'absence de canari côté portail signifierait peut-être
# seulement qu'aucun canari n'a jamais été planté.
interne = repr(expedition.sudo().read()) + repr(projection.sudo().read([
    "internal_notes", "supplier_cost", "margin",
]))
manquants = [
    nom for nom, valeur in CANARIS.items()
    if valeur not in interne and nom != "document"
]
assert not manquants, f"canaris absents cote interne : {manquants}"
assert CANARIS["document"] in repr(document_interne.sudo().read(["file_name"])), (
    "le canari document n'a pas ete plante"
)

# `odoo shell` annule la transaction en sortie : sans ce commit, la graine
# s'exécuterait sans erreur et ne laisserait rien derrière elle — c'est
# exactement ce qui s'est produit au premier essai, la précondition ne trouvant
# aucun des devis pourtant « créés ».
env.cr.commit()

print(f"FREIGHT_QUOTE_SEA={quote_sea.request_uuid}")
print(f"FREIGHT_QUOTE_AIR={quote_air.request_uuid}")
print(f"FREIGHT_QUOTE_B={quote_b.request_uuid}")
print(f"FREIGHT_QUOTE_CONC={quote_conc.request_uuid}")
print(f"FREIGHT_DETAIL_REFERENCE={projection.reference}")
print(f"FREIGHT_DETAIL_TOKEN={projection.public_tracking_token}")
print(f"FREIGHT_PUBLISHED_DOCUMENT=DOC-{publication.id}")
print("FREIGHT_SEED_OK")
