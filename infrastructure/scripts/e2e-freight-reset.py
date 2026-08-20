"""
Restauration du périmètre fret entre deux passages Playwright, et vérification
que les préconditions sont **réellement** réunies.

## Pourquoi restaurer plutôt que recréer

Recréer la base entre deux passages masquerait exactement ce qu'on cherche à
prouver : qu'une suite peut se rejouer sur un état déjà consommé. Une spec qui
n'est verte que sur une base neuve est une spec qui ne sera jamais rejouable en
intégration continue.

## Portée strictement limitée

Seuls les deux devis décidables du client A sont restaurés, retrouvés par leur
`request_uuid` — jamais par « le premier devis » ni par un ordre de tri, qui
changeraient dès qu'un enregistrement s'ajoute.

Le dossier enrichi (`e2e-freight-detail-a`) et le devis du client B ne sont
**pas** touchés : le premier est lu sans être modifié, le second sert à prouver
le cloisonnement et doit rester intact.

## Pourquoi la vérification est séparée de la restauration

Restaurer sans vérifier laisserait passer un état à moitié remis en place, et la
spec échouerait plus loin sur un symptôme sans rapport. La vérification affiche
`PRECONDITION_OK` ou `PRECONDITION_FAIL`, et l'appelant s'arrête sur le second.
"""

env = env  # noqa: F821  (fourni par odoo shell)

#: Devis restaurés à chaque passage. Le dossier enrichi et le devis B en sont
#: volontairement absents.
DEVIS_MUTABLES = ("e2e-freight-sea-a", "e2e-freight-air-a", "e2e-freight-conc-a")

Quote = env["dally.quote.request"].sudo()
Booking = env["shipment.freight.booking"].sudo()
Shipment = env["freight.shipment"].sudo()
Projection = env["dally.shipment"].sudo()
Document = env["freight.documents"].sudo()

problemes = []


def restaure(uuid_devis):
    """Défait le provisionnement d'un devis et le remet en état décidable."""
    devis = Quote.search([("request_uuid", "=", uuid_devis)], limit=1)
    if not devis:
        problemes.append(f"devis {uuid_devis} introuvable")
        return

    bookings = Booking.search([("dally_quote_request_id", "=", devis.id)])
    expeditions = Shipment.search([("booking_id", "in", bookings.ids)])
    projections = Projection.search([("tk_shipment_id", "in", expeditions.ids)])

    # L'ordre compte : les dépendants d'abord, sinon les clés étrangères
    # refusent la suppression — et c'est voulu, elles protègent la production
    # d'un effacement en cascade.
    if projections:
        env["dally.portal.document"].sudo().search(
            [("shipment_id", "in", projections.ids)]
        ).unlink()
        env["dally.shipment.event"].sudo().search(
            [("shipment_id", "in", projections.ids)]
        ).unlink()
        env["dally.shipment.package"].sudo().search(
            [("shipment_id", "in", projections.ids)]
        ).unlink()
        projections.unlink()
    if expeditions:
        Document.search([("freight_id", "in", expeditions.ids)]).unlink()
        env["shipment.package.line"].sudo().search(
            [("shipment_id", "in", expeditions.ids)]
        ).unlink()
        expeditions.unlink()
    bookings.unlink()

    # Remise en état décidable : `quoted` + un devis natif réellement `sent`.
    devis.write({
        "state": "quoted",
        "customer_decision_at": False,
        "customer_decision_by_id": False,
        "customer_rejection_reason": False,
    })
    for order in devis.sale_order_ids:
        if order.state != "sent":
            order.write({"state": "sent"})


for uuid_devis in DEVIS_MUTABLES:
    restaure(uuid_devis)

env.cr.commit()

# ── Vérification réelle, et non déclarative ──────────────────────────────
for uuid_devis in DEVIS_MUTABLES:
    devis = Quote.search([("request_uuid", "=", uuid_devis)], limit=1)
    if not devis:
        problemes.append(f"{uuid_devis} : absent apres restauration")
        continue
    if devis.state != "quoted":
        problemes.append(f"{uuid_devis} : state={devis.state}, attendu quoted")
    if not any(order.state == "sent" for order in devis.sale_order_ids):
        problemes.append(f"{uuid_devis} : aucun devis natif en etat sent")
    if Booking.search_count([("dally_quote_request_id", "=", devis.id)]):
        problemes.append(f"{uuid_devis} : un booking subsiste avant decision")

# Le dossier enrichi doit être intact : c'est lui qui porte colis, événement et
# documents, et la spec le lit sans le modifier.
detail = Quote.search([("request_uuid", "=", "e2e-freight-detail-a")], limit=1)
if not detail or detail.state != "won":
    problemes.append("dossier enrichi absent ou non provisionne")
else:
    booking_detail = Booking.search([("dally_quote_request_id", "=", detail.id)], limit=1)
    expedition_detail = Shipment.search([("booking_id", "=", booking_detail.id)], limit=1)
    projection_detail = Projection.search(
        [("tk_shipment_id", "=", expedition_detail.id)], limit=1
    )
    if not projection_detail:
        problemes.append("dossier enrichi : projection absente")
    else:
        # Le dossier stable doit représenter un état réellement publiable. Depuis
        # Freight Pro, une règle globale masque aux externes les projections dont
        # la politique d'état n'autorise pas le portail. Tester seulement colis /
        # événements / documents laisserait donc passer une fixture complète mais
        # volontairement invisible — exactement le faux positif rencontré ici.
        if projection_detail.state != "in_transit":
            problemes.append(
                f"dossier enrichi : state={projection_detail.state}, attendu in_transit"
            )
        if "dally_portal_visible" in Projection._fields and not projection_detail.dally_portal_visible:
            problemes.append("dossier enrichi : politique portail non visible")
        if (
            projection_detail.partner_id.commercial_partner_id
            != detail.partner_id.commercial_partner_id
        ):
            problemes.append("dossier enrichi : proprietaire portail incoherent")
        if not env["dally.shipment.package"].sudo().search_count(
            [("shipment_id", "=", projection_detail.id)]
        ):
            problemes.append("dossier enrichi : aucun colis")
        if not env["dally.shipment.event"].sudo().search_count(
            [("shipment_id", "=", projection_detail.id), ("visible_to_customer", "=", True)]
        ):
            problemes.append("dossier enrichi : aucun evenement publie")
        if not env["dally.portal.document"].sudo().search_count(
            [("shipment_id", "=", projection_detail.id), ("published_to_portal", "=", True)]
        ):
            problemes.append("dossier enrichi : aucun document publie")

# Le devis du client B doit rester décidable et intact.
devis_b = Quote.search([("request_uuid", "=", "e2e-freight-sea-b")], limit=1)
if not devis_b or devis_b.state != "quoted":
    problemes.append("devis du client B absent ou deja decide")

if problemes:
    for probleme in problemes:
        print(f"PRECONDITION_DETAIL {probleme}")
    print("PRECONDITION_FAIL freight")
else:
    print("PRECONDITION_OK freight")
