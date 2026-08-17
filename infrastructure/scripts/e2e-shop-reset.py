"""
Restaure le périmètre boutique entre deux exécutions, puis vérifie la précondition.

## Pourquoi un reset dédié

Les commandes boutique portent une contrainte d'unicité sur l'identifiant de
panier. Une seconde exécution rejouerait des paniers neufs, donc ne heurterait
rien — mais elle accumulerait des commandes et des contacts invités, et le
comptage final ne prouverait plus rien : « une seule commande pour ce panier »
resterait vrai tout en laissant passer une fuite de duplication ailleurs.

Le reset supprime donc tout ce que la boutique a produit, et **vérifie ensuite**
que la précondition est de nouveau réunie. Vérifier après plutôt que supposer :
un reset qui échoue en silence a déjà fait passer un test sur une base vide.

## L'ordre compte

Les commandes d'abord, les contacts invités ensuite : `sale.order` référence
`res.partner`, et l'inverse échouerait sur une contrainte de clé étrangère.
L'annulation avant suppression reprend le motif déjà utilisé pour les fixtures de
concurrence du portail — Odoo refuse de supprimer une commande hors brouillon.
"""

env = env  # noqa: F821

Commande = env["sale.order"]
Partenaire = env["res.partner"]

commandes = Commande.search([("dally_shop_order", "=", True)])
nb_commandes = len(commandes)
if commandes:
    commandes.filtered(lambda c: c.state not in ("draft", "cancel")).state = "cancel"
    commandes.unlink()

invites = Partenaire.search([("dally_shop_guest_cart_uuid", "!=", False)])
nb_invites = len(invites)
if invites:
    invites.unlink()

env.cr.commit()

print(f"PRECONDITION_reset commandes_supprimees={nb_commandes} invites_supprimes={nb_invites}")

# ── Vérification de la précondition ─────────────────────────────────────
#
# Contrôle positif compris : le produit publié doit exister ET être publié, sinon
# la spec échouerait sur un catalogue vide sans que la cause soit visible.
restantes = Commande.search_count([("dally_shop_order", "=", True)])
restants = Partenaire.search_count([("dally_shop_guest_cart_uuid", "!=", False)])
publie = env["product.template"].search(
    [("dally_shop_slug", "=", "e2e-groupe-5kva"), ("dally_published", "=", True)],
    limit=1,
)
cache = env["product.template"].with_context(active_test=False).search(
    [("dally_shop_slug", "=", "e2e-groupe-30kva")], limit=1
)
tarif = env["ir.config_parameter"].sudo().get_param("dally_shop.pricelist_id")

print(f"PRECONDITION_shop commandes_restantes={restantes} invites_restants={restants}")
print(f"PRECONDITION_shop produit_publie={bool(publie)} produit_cache={bool(cache)} "
      f"cache_non_publie={bool(cache) and not cache.dally_published} tarif={bool(tarif)}")

if (
    restantes == 0
    and restants == 0
    and publie
    and cache
    and not cache.dally_published
    and tarif
):
    print("PRECONDITION_OK shop")
else:
    print("PRECONDITION_FAIL shop")
