"""
Restauration du périmètre groupage entre deux passages.

Même principe qu'ailleurs : on ne recrée pas la base, on remet en état ce que la
spec consomme. Le dossier B n'est pas touché — il prouve le cloisonnement et
doit rester intact.
"""

env = env  # noqa: F821

DEVIS_MUTABLES = ("e2e-groupage-sea-a", "e2e-groupage-air-a")

Quote = env["dally.quote.request"].sudo()
Booking = env["shipment.freight.booking"].sudo()
Shipment = env["freight.shipment"].sudo()
Projection = env["dally.shipment"].sudo()

problemes = []


def restaure(uuid_devis):
    devis = Quote.search([("request_uuid", "=", uuid_devis)], limit=1)
    if not devis:
        problemes.append(f"{uuid_devis} introuvable")
        return
    bookings = Booking.search([("dally_quote_request_id", "=", devis.id)])
    expeditions = Shipment.search([("booking_id", "in", bookings.ids)])
    projections = Projection.search([("tk_shipment_id", "in", expeditions.ids)])
    if projections:
        env["dally.portal.document"].sudo().search(
            [("shipment_id", "in", projections.ids)]).unlink()
        env["dally.shipment.event"].sudo().search(
            [("shipment_id", "in", projections.ids)]).unlink()
        env["dally.shipment.package"].sudo().search(
            [("shipment_id", "in", projections.ids)]).unlink()
        projections.unlink()
    if expeditions:
        env["freight.documents"].sudo().search(
            [("freight_id", "in", expeditions.ids)]).unlink()
        env["shipment.package.line"].sudo().search(
            [("shipment_id", "in", expeditions.ids)]).unlink()
        expeditions.unlink()
    bookings.unlink()
    devis.write({
        "state": "quoted", "customer_decision_at": False,
        "customer_decision_by_id": False, "customer_rejection_reason": False,
    })
    for order in devis.sale_order_ids:
        if order.state != "sent":
            order.write({"state": "sent"})


for uuid_devis in DEVIS_MUTABLES:
    restaure(uuid_devis)

env.cr.commit()

for uuid_devis, mode in (("e2e-groupage-sea-a", "sea"), ("e2e-groupage-air-a", "air")):
    devis = Quote.search([("request_uuid", "=", uuid_devis)], limit=1)
    if not devis:
        problemes.append(f"{uuid_devis} absent apres restauration")
        continue
    if devis.state != "quoted":
        problemes.append(f"{uuid_devis} : state={devis.state}, attendu quoted")
    if not any(o.state == "sent" for o in devis.sale_order_ids):
        problemes.append(f"{uuid_devis} : aucun devis natif en etat sent")
    if devis.groupage_transport_mode != mode:
        problemes.append(f"{uuid_devis} : mode={devis.groupage_transport_mode}, attendu {mode}")
    if Booking.search_count([("dally_quote_request_id", "=", devis.id)]):
        problemes.append(f"{uuid_devis} : un booking subsiste avant decision")

devis_b = Quote.search([("request_uuid", "=", "e2e-groupage-sea-b")], limit=1)
if not devis_b or devis_b.state != "quoted":
    problemes.append("dossier groupage B absent ou deja decide")

if problemes:
    for probleme in problemes:
        print(f"PRECONDITION_DETAIL {probleme}")
    print("PRECONDITION_FAIL groupage")
else:
    print("PRECONDITION_OK groupage")
