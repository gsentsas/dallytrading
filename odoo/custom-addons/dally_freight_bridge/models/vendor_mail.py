"""
Suppression du courriel envoyé par le fournisseur à la conversion d'un booking.

## Le problème

`convert_to_operation()` se termine par :

```python
mail_template = self.env.ref('tk_freight.booking_shipment_mail_template')
if mail_template:
    mail_template.send_mail(self.id, force_send=True)
```

`force_send=True` envoie **immédiatement**, dans la transaction. Mesuré : deux
appels, deux courriels « Your Booking BOOKING/2026/08/00002 ».

Ce courriel part vers le client, au nom de DallyTrading, avec la mise en page et
la formulation du fournisseur. La communication client est un actif de la
marque : elle ne doit pas être émise par un composant technique interne, dans
une langue et un gabarit que nous ne contrôlons pas.

Effet secondaire tout aussi gênant : un jeu de tests ou une reprise de données
enverrait de vrais courriels à de vrais clients.

## Pourquoi ce contournement plutôt qu'un fork

Modifier `tk_freight` obligerait à reporter la modification à chaque mise à jour
du fournisseur. Étendre `mail.template` est un point d'extension normal d'Odoo,
et la surcharge est inerte tant que le drapeau de contexte n'est pas posé : rien
d'autre dans l'instance n'en est affecté.

Le drapeau est posé au seul endroit qui appelle `convert_to_operation()`, et
vise le seul gabarit du fournisseur. Un courriel Odoo normal — confirmation de
commande, notification de suivi — continue de partir.
"""

import logging

from odoo import models

_logger = logging.getLogger(__name__)

#: Doit rester identique à `quote_provisioning.CTX_SANS_MAIL_VENDEUR`.
CTX_SANS_MAIL_VENDEUR = "dally_freight_suppress_vendor_mail"

#: Gabarit du fournisseur, et lui seul.
XMLID_GABARIT_VENDEUR = "tk_freight.booking_shipment_mail_template"


class MailTemplate(models.Model):
    _name = "mail.template"
    _inherit = "mail.template"

    def send_mail(self, res_id, **kwargs):
        """Court-circuite le gabarit du fournisseur quand le pont le demande.

        La condition est doublement fermée : il faut *à la fois* le drapeau de
        contexte et le gabarit du fournisseur. Un drapeau oublié dans un
        contexte propagé ne peut donc pas éteindre un autre courriel.
        """
        if self.env.context.get(CTX_SANS_MAIL_VENDEUR):
            gabarit_vendeur = self.env.ref(
                XMLID_GABARIT_VENDEUR, raise_if_not_found=False
            )
            if gabarit_vendeur and self.id == gabarit_vendeur.id:
                _logger.info(
                    "Courriel du fournisseur tk_freight supprime pour le "
                    "booking %s : la communication client passe par DallyTrading.",
                    res_id,
                )
                return False
        return super().send_mail(res_id, **kwargs)
