"""
Vérification en base après le passage Playwright.

L'interface peut afficher une seule expédition tout en en cachant une seconde :
la liste est paginée, filtrée par record rule, et triée. Compter des lignes à
l'écran ne prouve donc rien sur l'absence de doublon côté booking ou côté
fournisseur. Ce contrôle regarde l'état réel.
"""

env = env  # noqa: F821

Quote = env["dally.quote.request"].sudo()
Booking = env["shipment.freight.booking"].sudo()
Shipment = env["freight.shipment"].sudo()
Projection = env["dally.shipment"].sudo()

problemes = []

# Les devis groupage sont vérifiés avec les autres : l'interface est paginée et
# filtrée, elle ne prouve rien sur l'absence de doublon côté booking ni côté
# fournisseur — ce que la course simultanée doit précisément établir.
for uuid_devis in ("e2e-freight-sea-a", "e2e-freight-air-a", "e2e-freight-conc-a",
                   "e2e-groupage-sea-a", "e2e-groupage-air-a"):
    devis = Quote.search([("request_uuid", "=", uuid_devis)], limit=1)
    if not devis:
        problemes.append(f"{uuid_devis} : introuvable")
        continue
    bookings = Booking.search([("dally_quote_request_id", "=", devis.id)])
    expeditions = Shipment.search([("booking_id", "in", bookings.ids)])
    projections = Projection.search([("tk_shipment_id", "in", expeditions.ids)])
    print(
        f"VERIFY {uuid_devis} state={devis.state} "
        f"bookings={len(bookings)} tk={len(expeditions)} dally={len(projections)}"
    )
    if devis.state != "won":
        problemes.append(f"{uuid_devis} : state={devis.state}, attendu won")
    if (len(bookings), len(expeditions), len(projections)) != (1, 1, 1):
        problemes.append(
            f"{uuid_devis} : {len(bookings)}/{len(expeditions)}/{len(projections)}, attendu 1/1/1"
        )

# Le mode physique de chaque groupage, vérifié jusqu'au fournisseur.
#
# C'est le contrôle qui compte pour ce chantier : l'aérien ne doit jamais
# retomber sur `ocean`, ni la projection sur le mode historique « groupage »,
# dont le ratio volumétrique vaut celui du maritime.
for uuid_devis, tk_attendu, ocean_attendu, dally_attendu in (
    ("e2e-groupage-sea-a", "ocean", "lcl", "sea"),
    ("e2e-groupage-air-a", "air", False, "air"),
):
    devis = Quote.search([("request_uuid", "=", uuid_devis)], limit=1)
    if not devis:
        problemes.append(f"{uuid_devis} : introuvable")
        continue
    booking = Booking.search([("dally_quote_request_id", "=", devis.id)], limit=1)
    expedition = Shipment.search([("booking_id", "=", booking.id)], limit=1)
    projection = Projection.search([("tk_shipment_id", "=", expedition.id)], limit=1)
    print(
        f"VERIFY {uuid_devis} tk={expedition.transport}/"
        f"{expedition.ocean_shipment_type or '-'} dally={projection.transport_mode}"
    )
    if expedition.transport != tk_attendu:
        problemes.append(f"{uuid_devis} : tk={expedition.transport}, attendu {tk_attendu}")
    if (expedition.ocean_shipment_type or False) != ocean_attendu:
        problemes.append(
            f"{uuid_devis} : ocean_shipment_type="
            f"{expedition.ocean_shipment_type or False}, attendu {ocean_attendu}"
        )
    if projection.transport_mode != dally_attendu:
        problemes.append(
            f"{uuid_devis} : dally={projection.transport_mode}, attendu {dally_attendu}"
        )
    if projection.transport_mode == "groupage":
        problemes.append(f"{uuid_devis} : le pont a produit le mode groupage")

if problemes:
    for probleme in problemes:
        print(f"VERIFY_DETAIL {probleme}")
    print("VERIFY_FAIL freight")
else:
    print("VERIFY_OK freight")
