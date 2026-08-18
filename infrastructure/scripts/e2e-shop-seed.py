"""
Fixtures boutique pour la pile E2E. Exécuté par `odoo shell`.

S'ajoute aux graines fret, véhicule et groupage, et réutilise leurs sociétés et
comptes portail : trois définitions du « client A » vaudraient trois vérités.

## Ce qui est monté

* un **tarif boutique** très éloigné du prix de liste des produits. L'écart est
  volontaire : si un prix affiché venait du prix de liste, il sauterait aux yeux
  au lieu de se noyer dans un arrondi ;
* trois **produits** — un publié courant, un publié à stock suivi, un **non
  publié**. Le troisième est celui qui rend les assertions d'invisibilité
  informatives : sans produit publié à côté, un catalogue vide « réussirait » ;
* un **contact sans compte portail** portant une adresse connue, pour distinguer
  « rapprocher par e-mail » de « demander une connexion » ;
* deux **clés d'API**, une par capacité. La vitrine ne doit pas pouvoir créer de
  commande même si elle est compromise.

## Canaris

Coût d'achat et note interne sur le produit commandé. Le coût donne la marge, donc
la limite de négociation : c'est le vrai enjeu de confidentialité d'un catalogue.
Les deux sont relus après écriture — un canari qu'on croit planté et qui ne l'est
pas rend tout le balayage creux.

Les slugs portent le préfixe `e2e-` : ils doivent être uniques dans toute la base
d'essai, et une collision avec une autre fixture a déjà fait échouer un cycle.
"""

env = env  # noqa: F821

CANARI_NOTE = "DALLY_E2E_SHOP_SECRET_INTERNAL_NOTE"
CANARI_COUT = 424242.42
CANARI_FOURNISSEUR = "DALLY_E2E_SHOP_SECRET_SUPPLIER"

PRIX_TARIF = 150000.0
PRIX_LISTE = 999999.0

MOT_DE_PASSE_INVITE_CONNU = None  # aucun compte : c'est le sens de cette fixture

# ── Tarif ───────────────────────────────────────────────────────────────
tarif = env["product.pricelist"].search([("name", "=", "Boutique E2E")], limit=1)
if not tarif:
    tarif = env["product.pricelist"].create({
        "name": "Boutique E2E",
        "item_ids": [(0, 0, {
            "compute_price": "fixed",
            "fixed_price": PRIX_TARIF,
            "applied_on": "3_global",
        })],
    })
env["ir.config_parameter"].sudo().set_param("dally_shop.pricelist_id", str(tarif.id))

# ── Catégorie publiée ───────────────────────────────────────────────────
Categorie = env["dally.shop.category"]
categorie = Categorie.search([("slug", "=", "e2e-equipements")], limit=1)
if not categorie:
    categorie = Categorie.create({
        "name": "Équipements E2E",
        "slug": "e2e-equipements",
        "published": True,
    })

# ── Produits ────────────────────────────────────────────────────────────
Produit = env["product.template"]


def produit(nom, slug, publie, politique, stockable=False):
    valeurs = {
        "name": nom,
        "type": "consu",
        "is_storable": stockable,
        "list_price": PRIX_LISTE,
        "sale_ok": True,
        "dally_shop_slug": slug,
        "dally_published": publie,
        "dally_stock_policy": politique,
        "dally_shop_category_id": categorie.id,
        "dally_shop_summary": f"Résumé public de {nom}.",
        "description_sale": f"Description commerciale de {nom}.",
    }
    trouve = Produit.with_context(active_test=False).search(
        [("dally_shop_slug", "=", slug)], limit=1
    )
    if trouve:
        trouve.write(valeurs)
        return trouve
    return Produit.create(valeurs)


p_publie = produit("Groupe E2E 5 kVA", "e2e-groupe-5kva", True, "on_order")
p_stock = produit("Groupe E2E 12 kVA", "e2e-groupe-12kva", True, "managed", stockable=True)
p_cache = produit("Groupe E2E 30 kVA", "e2e-groupe-30kva", False, "on_order")

# ── Photos ──────────────────────────────────────────────────────────────
#
# Cinq PNG de 1×1 pixel, de couleurs distinctes. Les octets diffèrent réellement,
# et c'est la condition pour que la spec puisse affirmer « la photo a changé » :
# quatre images identiques porteraient la même empreinte, donc le même jeton, et
# la comparaison ne prouverait rien.
ROUGE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
VERT = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC"
BLEU = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC"
JAUNE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4/58BAAT/Af9dfQKHAAAAAElFTkSuQmCC"
CYAN = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+P8fAAMBAf+2EqLVAAAAAElFTkSuQmCC"

Photo = env["dally.shop.product.image"]


def galerie(produit, photos):
    """Remonte la galerie du produit à l'identique, quel que soit l'état d'avant.

    La graine est rejouée entre les specs : ajouter sans nettoyer accumulerait
    les photos d'une exécution à l'autre, et « la fiche montre quatre photos »
    deviendrait faux au deuxième passage sans que le code ait changé.
    """
    produit.dally_shop_image_ids.unlink()
    for rang, (nom, image) in enumerate(photos, start=1):
        Photo.create({
            "name": nom,
            "sequence": rang * 10,
            "product_tmpl_id": produit.id,
            "image_1920": image,
        })


# Le produit publié : une photo principale et trois photos de galerie.
p_publie.write({"image_1920": ROUGE})
galerie(p_publie, [
    ("Vue avant E2E", VERT),
    ("Vue arrière E2E", BLEU),
    ("Intérieur E2E", JAUNE),
])

# Le produit NON publié en porte aussi : c'est ce qui rend informatives les
# assertions de refus. Sans photos, « son image répond 404 » serait vrai d'un
# produit qui n'a jamais eu d'image.
p_cache.write({"image_1920": CYAN})
galerie(p_cache, [("Photo cachée E2E", ROUGE)])

# Le troisième produit reste volontairement sans photo : la vitrine doit
# afficher un substitut propre, et c'est le cas le plus fréquent au démarrage
# d'un catalogue.
p_stock.write({"image_1920": False})
p_stock.dally_shop_image_ids.unlink()

assert p_publie.image_1920, "photo principale non plantee"
assert len(p_publie.dally_shop_image_ids) == 3, "galerie incomplete"
assert p_cache.image_1920, "photo du produit cache non plantee"
assert not p_stock.image_1920, "le produit sans photo en a une"

# ── Canaris ─────────────────────────────────────────────────────────────
fournisseur = env["res.partner"].search([("name", "=", CANARI_FOURNISSEUR)], limit=1)
if not fournisseur:
    fournisseur = env["res.partner"].create({
        "name": CANARI_FOURNISSEUR, "supplier_rank": 1,
    })

p_publie.write({"standard_price": CANARI_COUT, "description": CANARI_NOTE})
if not p_publie.seller_ids:
    p_publie.write({
        "seller_ids": [(0, 0, {"partner_id": fournisseur.id, "price": 12000.0})],
    })

interne = p_publie.sudo().read(["standard_price", "description"])[0]
assert interne["standard_price"] == CANARI_COUT, "canari de cout non plante"
assert CANARI_NOTE in (interne["description"] or ""), "canari de note non plante"
assert p_publie.seller_ids.partner_id.name == CANARI_FOURNISSEUR, "canari fournisseur"

# ── Contact connu SANS compte portail ───────────────────────────────────
#
# Une adresse qu'un contact possède déjà, mais qui n'appartient à aucun compte.
# Commander en invité avec cette adresse doit créer un NOUVEAU contact : sinon la
# seule connaissance d'une adresse suffirait à faire atterrir une commande dans le
# dossier de quelqu'un d'autre.
COURRIEL_CONNU = "connu.sans.compte@e2e-shop.invalid"
connu = env["res.partner"].search([("email", "=", COURRIEL_CONNU)], limit=1)
if not connu:
    connu = env["res.partner"].create({
        "name": "Contact Connu Sans Compte E2E",
        "email": COURRIEL_CONNU,
    })
assert not connu.user_ids, "ce contact ne doit avoir aucun compte"

# ── Clés d'API, une par capacité ────────────────────────────────────────
Cle = env["dally.api.key"]


def cle(nom, scopes):
    """Crée la clé et rend son secret dans la foulée.

    Le secret vit dans `key_to_display`, non stocké : il n'existe que dans le
    cache de la transaction. Deux choses l'effacent — le commit, et la création de
    la clé suivante, qui invalide le cache du modèle entier. D'où la lecture
    immédiate.
    """
    existante = Cle.search([("name", "=", nom)], limit=1)
    if existante:
        existante.unlink()
    creee = Cle.create({"name": nom, "scopes": scopes})
    creee.action_generate_key()
    secret = creee.key_to_display
    assert secret, f"secret non genere pour {nom}"
    return secret


secret_lecture = cle(
    "Boutique E2E (shop:read)", "shop:read,services:read,leads:write,quotes:write,tracking:read"
)
secret_commande = cle("Boutique E2E (shop:checkout)", "shop:checkout")

env.cr.commit()

print(f"SHOP_PRICE={PRIX_TARIF}")
print(f"SHOP_LIST_PRICE={PRIX_LISTE}")
print(f"SHOP_PUBLISHED_REF={p_publie.dally_shop_slug}")
print(f"SHOP_STOCK_REF={p_stock.dally_shop_slug}")
print(f"SHOP_UNPUBLISHED_REF={p_cache.dally_shop_slug}")
print(f"SHOP_UNPUBLISHED_ID={p_cache.id}")
print(f"SHOP_NO_IMAGE_REF={p_stock.dally_shop_slug}")
print(f"SHOP_GALLERY_COUNT={len(p_publie.dally_shop_image_ids)}")
print(f"SHOP_KNOWN_EMAIL={COURRIEL_CONNU}")
print(f"SHOP_CANARY_NOTE={CANARI_NOTE}")
print(f"SHOP_CANARY_SUPPLIER={CANARI_FOURNISSEUR}")
print(f"SHOP_API_KEY_READ={secret_lecture}")
print(f"SHOP_API_KEY_CHECKOUT={secret_commande}")
print("SHOP_SEED_OK")
