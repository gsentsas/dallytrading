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

for uuid_devis in ("e2e-freight-sea-a", "e2e-freight-air-a", "e2e-freight-conc-a"):
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

if problemes:
    for probleme in problemes:
        print(f"VERIFY_DETAIL {probleme}")
    print("VERIFY_FAIL freight")
else:
    print("VERIFY_OK freight")
