# Portail client natif de `sale` — surface mesurée et fermeture retenue

Odoo installe avec `sale` un portail client complet. `dally_portal` ne le
neutralisait pas : jusqu'à ce cycle, il n'y avait pas de `sale.order` client à
protéger. La boutique en crée, d'où cet audit.

## Surface mesurée

Mesuré sur la pile de développement, connecté comme client portail réel.

| Route | Avant fermeture | Après |
|---|---|---|
| `/my`, `/my/home`, `/my/account`, `/my/addresses`, `/my/security` | accessibles | **inchangées** — module `portal`, sans rapport avec la boutique |
| `/my/orders`, `/my/quotes` | 200, **vides** pour nos commandes | 200, commandes boutique exclues du domaine |
| `/my/orders/<id>` (sa commande boutique) | **200, 44 899 octets** — référence, article, montants | 36 293 octets = identique à un id inexistant |
| `/my/orders/<id>` (commande d'un autre) | refusée par la record rule | inchangée |
| `/my/orders/<id>` (**devis ordinaire**) | 200, 42 399 octets | **42 399 octets, inchangé** |
| `/my/orders/<id>/accept` | **a confirmé la commande** : `draft` → `sale`, signature enregistrée, **1 transfert de stock créé** | `{"error": "Invalid order."}`, état inchangé, aucun transfert |
| `/my/orders/<id>/accept` (**devis ordinaire**) | signe | **signe toujours** |
| `/my/orders/<id>/download_edi` | 200, 3 097 octets d'EDI | redirection, identique à un id inexistant |
| `/my/orders/<id>/decline`, `/document/<id>`, `/transaction` | ouvertes | fermées par le même point d'étranglement |

Les listes étaient vides par **accident** : leurs domaines natifs filtrent
`state = 'sale'` et `state = 'sent'`, et une commande boutique reste en `draft`.
Cette protection tombait au premier flux qui confirmerait.

## Décision

Fermeture **restreinte aux enregistrements portant `dally_shop_order`**.

Fermer les routes en bloc aurait cassé un usage commercial réel : le personnel
envoie ses offres par courriel, et le lien de l'offre est précisément
`/my/orders/<id>?access_token=…`. Le devis ordinaire doit continuer d'y passer, et
de pouvoir être signé.

## Mise en œuvre

`odoo/custom-addons/dally_shop/controllers/neutralise_sale_portal.py` surcharge
**une seule méthode**, `_document_check_access`, par laquelle passent les six
routes de détail et d'action, plus les deux domaines de liste.

Six surcharges séparées auraient le même effet aujourd'hui et divergeraient
demain : il suffirait qu'une montée de version ajoute une septième route. Ici, une
route nouvelle suivant la convention d'Odoo est fermée sans qu'on y pense.

Le refus prend la forme d'un `MissingError` — celle qu'Odoo produit déjà pour un
enregistrement inexistant. Une commande boutique est donc, vue du portail natif,
indiscernable d'une commande qui n'existe pas.

## Ce qui n'a pas été touché

Aucune ACL, aucune record rule. L'audit a montré qu'elles suffisent déjà :

* ACL `sale.order.portal` — le groupe portail a **read seul**. Mesuré : `write`,
  `create`, `unlink` lèvent `AccessError` ;
* record rule `Portal Personal Quotations/Sales Orders` —
  `partner_id child_of user.commercial_partner_id.id`.

Les réduire aurait retiré des droits dont Odoo interne a besoin, sans rien
gagner.

## Vérification continue

* `dally_shop/tests/test_portal_orders.py::TestPortailNatifNeutralise` — six tests
  `HttpCase` frappant les vraies URL, dont deux contrôles négatifs sur le devis
  ordinaire ;
* `apps/web/e2e/15-shop-checkout.spec.ts` — un test navigateur vérifiant qu'aucune
  commande boutique n'apparaît dans `/my/orders` ni `/my/quotes`, **et** que les
  devis ordinaires y restent visibles.
