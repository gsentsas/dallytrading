"""
Compte en base ce que la boutique a réellement produit.

L'interface est paginée, filtrée et triée : compter des lignes à l'écran ne prouve
rien sur l'absence de doublon. Ce script interroge la base, et il est le seul juge.

## Ce qu'il vérifie

* **une commande par identifiant de panier** — aucun doublon ;
* **une ligne par référence** dans chaque commande — un rejeu qui accumulerait des
  lignes est une duplication de facturation, et le nombre de commandes seul ne
  l'attraperait pas ;
* **un contact invité par panier** ;
* **aucune facture, aucun transfert** ;
* **toutes les commandes en brouillon** ;
* **les prix viennent du tarif boutique**, et jamais du prix de liste.

Un contrôle positif ouvre la série : sans commande produite, tous les comptages
« corrects » seraient ceux d'une base vide.
"""

env = env  # noqa: F821

PRIX_TARIF = 150000.0
PRIX_LISTE = 999999.0

Commande = env["sale.order"]
commandes = Commande.search([("dally_shop_order", "=", True)])

print(f"VERIFY shop commandes={len(commandes)}")

# ── Contrôle positif ────────────────────────────────────────────────────
if not commandes:
    print("VERIFY_FAIL shop : aucune commande boutique — le comptage ne prouverait rien")
    raise SystemExit

echecs = []

# ── Une commande par panier ─────────────────────────────────────────────
paniers = {}
for commande in commandes:
    paniers.setdefault(commande.dally_shop_cart_uuid, []).append(commande)
doublons = {c: len(v) for c, v in paniers.items() if len(v) > 1}
print(f"VERIFY shop paniers_distincts={len(paniers)} paniers_dupliques={len(doublons)}")
if doublons:
    echecs.append(f"paniers dupliques : {doublons}")

# ── Une ligne par référence ─────────────────────────────────────────────
for commande in commandes:
    references = commande.order_line.mapped(
        lambda l: l.product_id.product_tmpl_id.dally_shop_slug
    )
    if len(references) != len(set(references)):
        echecs.append(f"{commande.name} : references dupliquees {references}")

# ── Un contact invité par panier ────────────────────────────────────────
invites = env["res.partner"].search([("dally_shop_guest_cart_uuid", "!=", False)])
par_panier = {}
for invite in invites:
    par_panier.setdefault(invite.dally_shop_guest_cart_uuid, []).append(invite)
invites_dupliques = {c: len(v) for c, v in par_panier.items() if len(v) > 1}
print(f"VERIFY shop contacts_invites={len(invites)} paniers_avec_doublon="
      f"{len(invites_dupliques)}")
if invites_dupliques:
    echecs.append(f"contacts invites dupliques : {invites_dupliques}")

# ── Aucune facture, aucun transfert, tout en brouillon ───────────────────
factures = len(commandes.invoice_ids)
transferts = len(commandes.picking_ids)
etats = sorted(set(commandes.mapped("state")))
print(f"VERIFY shop factures={factures} transferts={transferts} etats={etats}")
if factures:
    echecs.append(f"{factures} facture(s) creee(s)")
if transferts:
    echecs.append(f"{transferts} transfert(s) cree(s)")
if etats != ["draft"]:
    echecs.append(f"etats inattendus : {etats}")

# ── Les prix viennent du tarif ──────────────────────────────────────────
prix_hors_tarif = commandes.order_line.filtered(
    lambda l: abs(l.price_unit - PRIX_TARIF) > 0.01
)
remises = commandes.order_line.filtered(lambda l: l.discount)
print(f"VERIFY shop lignes={len(commandes.order_line)} "
      f"hors_tarif={len(prix_hors_tarif)} avec_remise={len(remises)}")
if prix_hors_tarif:
    echecs.append(
        "prix hors tarif : "
        + ", ".join(f"{l.product_id.display_name}={l.price_unit}" for l in prix_hors_tarif)
    )
if remises:
    echecs.append(f"{len(remises)} ligne(s) avec remise")

# Le prix de liste ne doit apparaître nulle part : c'est le contrôle négatif du
# précédent, et il rendrait visible un repli silencieux sur `list_price`.
au_prix_de_liste = commandes.order_line.filtered(
    lambda l: abs(l.price_unit - PRIX_LISTE) < 0.01
)
if au_prix_de_liste:
    echecs.append(f"{len(au_prix_de_liste)} ligne(s) au prix de liste")

# ── Aucune commande boutique sans clé ni mode ───────────────────────────
incompletes = commandes.filtered(
    lambda c: not c.dally_shop_cart_uuid or not c.dally_shop_delivery_mode
)
if incompletes:
    echecs.append(f"{len(incompletes)} commande(s) sans cle ou sans mode de remise")

# ── Aucun contact invité ne porte de compte ────────────────────────────
avec_compte = invites.filtered(lambda p: p.user_ids)
print(f"VERIFY shop invites_avec_compte={len(avec_compte)}")
if avec_compte:
    echecs.append(f"{len(avec_compte)} contact(s) invite(s) portent un compte")

if echecs:
    for echec in echecs:
        print(f"VERIFY_FAIL shop : {echec}")
else:
    print("VERIFY_OK shop")
