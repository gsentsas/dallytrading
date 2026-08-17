"""
Restauration du périmètre « véhicule » entre deux passages, et vérification des
préconditions.

Même principe que la restauration fret : on ne recrée pas la base, on remet en
état ce que la spec consomme. Une suite qui n'est verte que sur une base neuve
n'est pas rejouable, et c'est précisément ce qu'il faut prouver ici.

## Portée

* `e2e-vehicle-sea-a` est restauré : la spec l'accepte, ce qui le consomme.
* `e2e-vehicle-sea-b` ne l'est **pas** : il sert à prouver le cloisonnement et
  doit rester intact, décidable, jamais touché par A.
* Les devis créés par le **formulaire public** sont retirés à chaque passage.
  Sans cela, le second run trouverait deux dossiers pour la même identité
  logique et ne saurait plus lequel vérifier.

## Reconnaître les devis du formulaire public

Ils n'ont pas de `request_uuid` déterministe — le navigateur en génère un. On les
retrouve par leur **VIN de fixture**, qui est unique et n'appartient qu'à eux.
C'est la seule clé stable disponible, et elle vaut mieux qu'un « dernier devis
créé » qui casserait dès qu'une autre spec en crée un.
"""

env = env  # noqa: F821

#: Devis restauré à chaque passage.
DEVIS_MUTABLE = "e2e-vehicle-sea-a"
#: VIN utilisé par la spec du formulaire public. Sert à retrouver ses dossiers.
VIN_PUBLIC = "DALLYE2EVINPUB001"

Quote = env["dally.quote.request"].sudo()
Cargo = env["dally.freight.vehicle.cargo"].sudo()
Booking = env["shipment.freight.booking"].sudo()
Shipment = env["freight.shipment"].sudo()
Projection = env["dally.shipment"].sudo()

problemes = []


def defaire_provisionnement(devis):
    """Supprime la chaîne fret produite par l'acceptation, dépendants d'abord."""
    bookings = Booking.search([("dally_quote_request_id", "=", devis.id)])
    expeditions = Shipment.search([("booking_id", "in", bookings.ids)])
    projections = Projection.search([("tk_shipment_id", "in", expeditions.ids)])

    if projections:
        # Le véhicule pointe l'expédition : on le détache avant de la retirer,
        # sinon la clé étrangère refuse — et c'est voulu, elle protège d'un
        # effacement en cascade.
        Cargo.search([("shipment_id", "in", projections.ids)]).write(
            {"shipment_id": False}
        )
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
        env["freight.documents"].sudo().search(
            [("freight_id", "in", expeditions.ids)]
        ).unlink()
        env["shipment.package.line"].sudo().search(
            [("shipment_id", "in", expeditions.ids)]
        ).unlink()
        expeditions.unlink()
    bookings.unlink()


# ── Dossier A : défaire le provisionnement, redevenir décidable ──────────
devis_a = Quote.search([("request_uuid", "=", DEVIS_MUTABLE)], limit=1)
if not devis_a:
    problemes.append(f"{DEVIS_MUTABLE} introuvable")
else:
    defaire_provisionnement(devis_a)
    devis_a.write({
        "state": "quoted",
        "customer_decision_at": False,
        "customer_decision_by_id": False,
        "customer_rejection_reason": False,
    })
    for order in devis_a.sale_order_ids:
        if order.state != "sent":
            order.write({"state": "sent"})

# ── Dossiers créés par le formulaire public : retirés ────────────────────
publics = Cargo.search([("vin", "=", VIN_PUBLIC)])
if publics:
    devis_publics = publics.mapped("quote_request_id")
    for devis in devis_publics:
        defaire_provisionnement(devis)
    publics.unlink()
    commandes = env["sale.order"].sudo().search(
        [("dally_quote_request_id", "in", devis_publics.ids)]
    )
    # `sale` refuse la suppression d'un devis envoyé : annuler d'abord.
    commandes.filtered(lambda o: o.state != "cancel")._action_cancel()
    commandes.unlink()
    devis_publics.unlink()

env.cr.commit()

# ── Vérification réelle, et non déclarative ─────────────────────────────
devis_a = Quote.search([("request_uuid", "=", DEVIS_MUTABLE)], limit=1)
if not devis_a:
    problemes.append(f"{DEVIS_MUTABLE} : absent apres restauration")
else:
    if devis_a.state != "quoted":
        problemes.append(f"A : state={devis_a.state}, attendu quoted")
    if not any(o.state == "sent" for o in devis_a.sale_order_ids):
        problemes.append("A : aucun devis natif en etat sent")
    if Booking.search_count([("dally_quote_request_id", "=", devis_a.id)]):
        problemes.append("A : un booking subsiste avant decision")

    cargo_a = Cargo.search([("quote_request_id", "=", devis_a.id)])
    if len(cargo_a) != 1:
        problemes.append(f"A : {len(cargo_a)} vehicule(s), attendu 1")
    elif cargo_a.transport_mode != "sea":
        problemes.append(f"A : mode={cargo_a.transport_mode}, attendu sea")
    elif cargo_a.shipment_id:
        problemes.append("A : le vehicule est encore rattache a une expedition")

# Le dossier B doit être intact : c'est lui qui prouve le cloisonnement.
devis_b = Quote.search([("request_uuid", "=", "e2e-vehicle-sea-b")], limit=1)
if not devis_b:
    problemes.append("B : dossier vehicule absent")
elif not Cargo.search_count([("quote_request_id", "=", devis_b.id)]):
    problemes.append("B : vehicule absent")

# Aucun résidu du formulaire public.
if Cargo.search_count([("vin", "=", VIN_PUBLIC)]):
    problemes.append("des dossiers du formulaire public subsistent")

if problemes:
    for probleme in problemes:
        print(f"PRECONDITION_DETAIL {probleme}")
    print("PRECONDITION_FAIL vehicle")
else:
    print("PRECONDITION_OK vehicle")
