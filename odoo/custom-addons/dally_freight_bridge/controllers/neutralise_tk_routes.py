"""
Neutralisation des routes HTTP de `tk_freight`.

## Pourquoi une neutralisation explicite, et non un retrait de liens

Retirer un bouton d'un gabarit ne ferme rien : l'URL reste servie par le
routeur. Les mesures de l'évaluation (partie II) l'imposent :

* `/track/shipment` est `auth="public"` et fait `sudo().search([('name','=',q)])`
  sans jeton ni limite de débit. La référence est **séquentielle**
  (`OCEAN/2026/08/00002`, `00003`) et la réponse distingue l'existant de
  l'inexistant : tout le carnet d'expéditions est énumérable de l'extérieur.
* `/freight/shipment/booking/submit` est déclarée `csrf=False`. Un POST **sans
  aucun jeton** a créé une cotation réelle (`FQ/2026/08/00001`, attribution
  vérifiée sur `create_uid`). Une page tierce peut donc faire créer des
  enregistrements au navigateur d'un client connecté.
* `/post/comment` est `auth="user"` puis `sudo().browse(kw['book_id'])` **sans
  contrôle de propriété**, et rend la page de détail du booking visé. Elle est
  aujourd'hui inatteignable — elle plante d'abord sur `fields.datetime`, absent
  d'Odoo 19 — mais **ce n'est pas un contrôle de sécurité** : le jour où le
  fournisseur corrige la faute de frappe, l'IDOR devient vivante.

## Comment

Odoo résout les routes par la dernière classe de contrôleur chargée qui définit
la méthode. Hériter du contrôleur du fournisseur et redéclarer chaque méthode
avec les mêmes chemins remplace donc l'implémentation, sans toucher à son code.

Toutes renvoient un 404 — et non un 403 : un 403 confirmerait que la route
existe, ce qui est déjà une information. Le portail client passe exclusivement
par les projections de `dally_portal`.
"""

import logging

from odoo import http
from odoo.http import request

from odoo.addons.tk_freight.controllers.main import (
    BookingsCustom,
    FreightCustomerPortal,
)

_logger = logging.getLogger(__name__)


def _closed():
    """Ferme la route en cours. Ne retourne jamais.

    404 plutôt que 403 : un refus explicite confirmerait l'existence de la
    route, et donc du moteur derrière elle.

    On *lève* l'exception au lieu de la retourner : Odoo 19 journalise
    « returns an HTTPException instead of raising it » dans le cas contraire.
    Le comportement observable est le même, mais un avertissement récurrent
    dans les journaux de production finit par masquer les vrais signaux.
    """
    raise request.not_found()


class DallyNeutralisedFreightRoutes(BookingsCustom):
    """Ferme les 17 motifs de routes exposés par `tk_freight`.

    L'héritage porte sur la classe du fournisseur : les méthodes ci-dessous
    portent les mêmes noms et les mêmes chemins, et prennent donc la place des
    siennes dans la table de routage.
    """

    # -- Suivi public : énumérable, sans jeton, sans limite de débit ----------

    @http.route(["/shipment"], type="http", auth="public", website=True)
    def track_freight(self, **kw):
        _closed()

    @http.route(
        [
            "/track/shipment",
            "/track/shipment/<string:booking>",
            "/track/shipment/<string:shipment>",
        ],
        type="http",
        auth="public",
        website=True,
    )
    def track_shipment(self, booking=None, **kw):
        # Journalisé : une sollicitation ici après déploiement signale soit un
        # lien résiduel, soit une tentative d'énumération.
        _logger.info("Route tk_freight neutralisée sollicitée: /track/shipment")
        _closed()

    # -- Routes de mutation déclarées csrf=False -----------------------------

    @http.route(
        ["/freight/shipment/booking/create"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_bookings_create(self, **kw):
        _closed()

    @http.route(
        ["/freight/shipment/booking/submit"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_bookings_submit(self, **post):
        _logger.warning(
            "Route tk_freight neutralisée sollicitée en écriture: booking/submit"
        )
        _closed()

    # -- IDOR en lecture et en écriture --------------------------------------

    @http.route(["/post/comment"], type="http", auth="user", website=True)
    def post_comment(self, **kw):
        _logger.warning(
            "Route tk_freight neutralisée sollicitée en écriture: /post/comment"
        )
        _closed()

    # -- Listes et détails portail -------------------------------------------

    @http.route(["/freight/shipment/booking"], type="http", auth="user", website=True)
    def portal_my_bookings(self, **kw):
        _closed()

    @http.route(
        [
            "/freight/shipment/bookings",
            "/freight/shipment/bookings/page/<int:page>",
        ],
        type="http",
        auth="user",
        website=True,
    )
    def booking_details(self, page=1, **kw):
        _closed()

    @http.route(
        [
            "/freight/shipment/quotation",
            "/freight/shipment/quotation/page/<int:page>",
        ],
        type="http",
        auth="user",
        website=True,
    )
    def quotation_details(self, page=1, **kw):
        _closed()

    @http.route(
        [
            "/freight/shipment/shipment",
            "/freight/shipment/shipment/page.<int:page>",
        ],
        type="http",
        auth="user",
        website=True,
    )
    def shipment_details(self, page=1, **kw):
        _closed()

    @http.route(
        ["/freight/shipment/booking/details/<model('shipment.freight.booking'):booking>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_booking_detail(self, booking, **kw):
        _closed()

    @http.route(
        ["/freight/shipment/quotation/details/<model('shipment.quotation'):q>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_quotation_detail(self, q, **kw):
        _closed()

    @http.route(
        ["/freight/shipment/shipment/details/<model('freight.shipment'):s>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_shipment_detail(self, s, **kw):
        _closed()


class DallyNeutralisedFreightPortalHome(FreightCustomerPortal):
    """Retire les compteurs fret de la page d'accueil du portail Odoo.

    `tk_freight` y ajoute des compteurs d'expéditions, de bookings et de
    cotations. Les laisser afficherait un décompte issu de modèles auxquels le
    portail n'a plus accès — au mieux zéro, au pire une erreur — et
    proposerait des liens vers les routes fermées ci-dessus.
    """

    def _prepare_home_portal_values(self, counters):
        # Court-circuit complet : on ne rappelle pas l'implémentation du
        # fournisseur, qui interrogerait les modèles fret.
        return super(FreightCustomerPortal, self)._prepare_home_portal_values(
            counters
        )
