"""
Fixtures boutique pour la pile de développement. Exécuté par `odoo shell`.

## Ce qui est monté

* un **tarif boutique** à prix fixes, distinct du prix de liste des produits.
  Les deux valeurs sont volontairement très éloignées : si un prix affiché venait
  du prix de liste, l'écart sauterait aux yeux au lieu de se noyer dans un
  arrondi ;
* deux **catégories**, dont une non publiée, parce que la fuite d'un nom de
  catégorie en préparation est une fuite commerciale ;
* quatre **produits** couvrant les quatre situations à distinguer : publié sur
  commande, publié à stock suivi, non publié, publié mais archivé ;
* une **clé d'API** avec le seul scope `shop:read`, et une seconde sans ce scope,
  pour que le refus d'autorisation soit mesuré plutôt que supposé ;
* des **canaris** dans les champs internes du produit publié.

`env.cr.commit()` en fin de course : `odoo shell` annule sa transaction en
sortant, et un jeu d'essai qui disparaît en silence a déjà fait échouer un cycle
précédent sur une précondition introuvable.
"""

env = env  # noqa: F821

CANARI_COUT = 424242.42
CANARI_NOTE = "DALLY_SHOP_CANARY_INTERNAL_NOTE"
CANARI_FOURNISSEUR = "DALLY_SHOP_CANARY_SUPPLIER"

PRIX_TARIF = 150000.0
PRIX_LISTE = 999999.0

# ── Tarif ───────────────────────────────────────────────────────────────
tarif = env["product.pricelist"].search([("name", "=", "Boutique DallyTrading")], limit=1)
if not tarif:
    tarif = env["product.pricelist"].create({
        "name": "Boutique DallyTrading",
        "item_ids": [(0, 0, {
            "compute_price": "fixed",
            "fixed_price": PRIX_TARIF,
            "applied_on": "3_global",
        })],
    })
env["ir.config_parameter"].sudo().set_param("dally_shop.pricelist_id", str(tarif.id))

# ── Catégories ──────────────────────────────────────────────────────────
Categorie = env["dally.shop.category"]


def categorie(nom, slug, publiee):
    trouvee = Categorie.search([("slug", "=", slug)], limit=1)
    if trouvee:
        trouvee.write({"name": nom, "published": publiee})
        return trouvee
    return Categorie.create({"name": nom, "slug": slug, "published": publiee})


cat_publiee = categorie("Groupes électrogènes", "groupes-electrogenes", True)
cat_fermee = categorie("Gamme en préparation", "gamme-en-preparation", False)

# ── Fournisseur porteur de canari ───────────────────────────────────────
fournisseur = env["res.partner"].search([("name", "=", CANARI_FOURNISSEUR)], limit=1)
if not fournisseur:
    fournisseur = env["res.partner"].create({
        "name": CANARI_FOURNISSEUR, "supplier_rank": 1,
    })

# ── Produits ────────────────────────────────────────────────────────────
Produit = env["product.template"]


def produit(nom, slug, publie, politique, cat, resume, stockable=False):
    valeurs = {
        "name": nom,
        "type": "consu",
        "is_storable": stockable,
        "list_price": PRIX_LISTE,
        "dally_shop_slug": slug,
        "dally_published": publie,
        "dally_stock_policy": politique,
        "dally_shop_category_id": cat.id if cat else False,
        "dally_shop_summary": resume,
        "description_sale": f"Description commerciale de {nom}.",
    }
    trouve = Produit.with_context(active_test=False).search(
        [("dally_shop_slug", "=", slug)], limit=1
    )
    if trouve:
        trouve.write(valeurs)
        return trouve
    return Produit.create(valeurs)


p_publie = produit(
    "Groupe électrogène 5 kVA", "groupe-electrogene-5kva", True, "on_order",
    cat_publiee, "Groupe électrogène monophasé, démarrage manuel.",
)
p_stock = produit(
    "Groupe électrogène 12 kVA", "groupe-electrogene-12kva", True, "managed",
    cat_publiee, "Groupe électrogène triphasé, démarrage automatique.",
    stockable=True,
)
p_non_publie = produit(
    "Groupe électrogène 30 kVA", "groupe-electrogene-30kva", False, "on_order",
    cat_publiee, "Ne doit jamais apparaître : non publié.",
)
p_archive = produit(
    "Groupe électrogène retiré", "groupe-electrogene-retire", True, "on_order",
    cat_publiee, "Ne doit jamais apparaître : archivé.",
)
p_archive.active = False

# Produit publié dans une catégorie non publiée : le nom de la catégorie ne doit
# pas traverser.
p_cat_fermee = produit(
    "Onduleur 3 kVA", "onduleur-3kva", True, "on_order",
    cat_fermee, "Onduleur en préparation de gamme.",
)

# ── Canaris sur le produit publié ───────────────────────────────────────
p_publie.write({
    "standard_price": CANARI_COUT,
    "description": CANARI_NOTE,
})
if not p_publie.seller_ids:
    p_publie.write({
        "seller_ids": [(0, 0, {"partner_id": fournisseur.id, "price": 12000.0})],
    })

interne = p_publie.sudo().read(["standard_price", "description"])[0]
assert interne["standard_price"] == CANARI_COUT, "canari de cout non plante"
assert CANARI_NOTE in (interne["description"] or ""), "canari de note non plante"
assert p_publie.seller_ids.partner_id.name == CANARI_FOURNISSEUR, "canari fournisseur"

# ── Clés d'API ──────────────────────────────────────────────────────────
# Deux clés : l'une porte le scope, l'autre non. Le refus d'autorisation se
# mesure alors sur une clé réelle et valide, et non sur une clé inventée — ce
# qui confondrait « scope absent » et « clé inconnue ».
Cle = env["dally.api.key"]


def cle(nom, scopes):
    """Crée la clé et rend son secret dans la foulée.

    Le secret vit dans `key_to_display`, qui n'est pas stocké : il n'existe que
    dans le cache de la transaction. Deux choses l'effacent, et les deux ont été
    mesurées ici plutôt que déduites :

    * `env.cr.commit()`, qui vide le cache ;
    * la **création de la clé suivante**, qui invalide le cache du modèle entier
      — donc le secret de la clé précédente.

    D'où la lecture immédiate, dans la même fonction que la génération. Lire les
    deux secrets à la fin donnait `False` pour le premier.
    """
    existante = Cle.search([("name", "=", nom)], limit=1)
    if existante:
        existante.unlink()
    creee = Cle.create({"name": nom, "scopes": scopes})
    creee.action_generate_key()
    secret = creee.key_to_display
    assert secret, f"secret non genere pour {nom}"
    return creee, secret


# Trois clés, une par capacité, plus une sans le scope. Les capacités sont
# séparées parce que lire un catalogue public et créer une `sale.order` sont deux
# pouvoirs différents ; la clé sans scope existe pour que le refus d'autorisation
# soit mesuré sur une clé réelle et valide, et non confondu avec « clé inconnue ».
cle_boutique, secret_boutique = cle("Boutique dev (shop:read)", "shop:read,services:read")
cle_checkout, secret_checkout = cle("Boutique dev (shop:checkout)", "shop:checkout")
cle_sans_scope, secret_sans_scope = cle("Boutique dev (sans shop:read)", "services:read")

# ── Client portail, pour la commande connectée ───────────────────────────
#
# La commande d'un client connecté passe par sa session portail, jamais par une
# clé d'API : c'est la seule construction dans laquelle `request.env.user` est le
# client. Il faut donc un vrai compte, avec un vrai mot de passe.
MOT_DE_PASSE_CLIENT = "essai-boutique-client-2026"
COURRIEL_CLIENT = "client.boutique@essai.invalid"

partenaire_client = env["res.partner"].search([("email", "=", COURRIEL_CLIENT)], limit=1)
if not partenaire_client:
    partenaire_client = env["res.partner"].create({
        "name": "Client Boutique (synthetique)",
        "email": COURRIEL_CLIENT,
        "phone": "+221 77 111 22 33",
        "street": "12 avenue de la Boutique",
        "city": "Dakar",
        "zip": "11000",
    })

utilisateur_client = env["res.users"].with_context(active_test=False).search(
    [("login", "=", COURRIEL_CLIENT)], limit=1
)
if not utilisateur_client:
    utilisateur_client = env["res.users"].create({
        "name": partenaire_client.name,
        "login": COURRIEL_CLIENT,
        "partner_id": partenaire_client.id,
        "group_ids": [(6, 0, [env.ref("base.group_portal").id])],
    })
utilisateur_client.write({"password": MOT_DE_PASSE_CLIENT, "active": True})

# ── Contact sans compte, portant une adresse connue ──────────────────────
#
# Le cas qui distingue « rapprocher par e-mail » de « demander une connexion ».
COURRIEL_SANS_COMPTE = "connu.sans.compte@essai.invalid"
sans_compte = env["res.partner"].search([("email", "=", COURRIEL_SANS_COMPTE)], limit=1)
if not sans_compte:
    sans_compte = env["res.partner"].create({
        "name": "Contact Connu Sans Compte",
        "email": COURRIEL_SANS_COMPTE,
    })

env.cr.commit()

print(f"SHOP_PRICELIST_ID={tarif.id}")
print(f"SHOP_PRICE={PRIX_TARIF}")
print(f"SHOP_LIST_PRICE={PRIX_LISTE}")
print(f"SHOP_KEY={secret_boutique}")
print(f"SHOP_KEY_CHECKOUT={secret_checkout}")
print(f"SHOP_KEY_NO_SCOPE={secret_sans_scope}")
print(f"SHOP_PORTAL_LOGIN={COURRIEL_CLIENT}")
print(f"SHOP_PORTAL_PASSWORD={MOT_DE_PASSE_CLIENT}")
print(f"SHOP_KNOWN_EMAIL_NO_ACCOUNT={COURRIEL_SANS_COMPTE}")
print(f"SHOP_UNPUBLISHED_ID={p_non_publie.id}")
print("SHOP_SEED_OK")
