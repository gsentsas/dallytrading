"""French UI overlay for translatable tk_freight view architectures."""

from odoo import models


#: Les trois vues dont la source anglaise est réellement abîmée, constatées en
#: production. La liste est fermée : la réparation ne touche rien d'autre.
#:
#: Une première mesure en annonçait cinq. Elle cherchait « Maritime » dans la
#: valeur anglaise — mot qui est aussi de l'anglais chez le fournisseur, dans
#: « International Maritime Dangerous Goods code ». Deux vues n'avaient jamais
#: été abîmées.
TK_REPAIRABLE_VIEWS = (
    "tk_freight.freight_shipment_form_view",
    "tk_freight.package_form_view",
    "tk_freight.package_tree_view",
)

#: Les marqueurs qui prouvent la corruption. Tous sont du français sans
#: équivalent anglais : leur présence dans la langue source ne s'explique que
#: par une écriture fautive. « Maritime » en est volontairement absent.
TK_CORRUPTION_MARKERS = ("Cotationss", "Cotations", "Colis", "Expéditeur")

#: Les vues du fournisseur que le pont francise. La réparation vise les mêmes :
#: ce sont exactement celles que l'ancien overlay pouvait abîmer.
TK_OVERLAID_VIEWS = (
    "tk_freight.freight_shipment_form_view",
    "tk_freight.freight_booking_form_view",
    "tk_freight.shipment_quot_form_view",
    "tk_freight.shipment_package_line_view_form",
    "tk_freight.package_form_view", "tk_freight.package_tree_view",
    "tk_freight.freight_success", "tk_freight.portal_booking_create",
    "tk_freight.freight_quotation_inherit",
    "tk_freight.res_partner_form_inherit_view",
    "tk_freight.policy_risk_tree_view",
    "tk_freight.shipment_tracking_view_form",
    "tk_freight.shipment_tracking_template_view_form",
    "tk_freight.shipment_tracking_template_view_tree",
    "tk_freight.freight_shipment_kanban_view",
    "tk_freight.freight_shipment_search_view",
)


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    def dally_apply_tk_freight_fr_overlay(self):
        """Correct reviewed vendor wording without changing en_US or behaviour."""
        language = self.env["res.lang"].search(
            [("code", "=", "fr_FR"), ("active", "=", True)], limit=1
        )
        # A new Odoo database does not necessarily enable French before module
        # installation. The next bridge update after language activation will
        # apply this idempotent overlay; a translated ORM write now would fail.
        if not language:
            return True

        menu_labels = (
            ("tk_freight.freight_root", "Gestion du fret"),
            ("tk_freight.dasboard_id", "Tableau de bord"),
            ("tk_freight.menu_shipment_quot", "Cotations"),
            ("tk_freight.freight_house_freight_booking", "Réservations"),
            ("tk_freight.menu_freight_shipment", "Expéditions"),
            ("tk_freight.freight_all_operation", "Toutes les expéditions"),
            ("tk_freight.freight_air_operation", "Aérien"),
            ("tk_freight.freight_ocean_operation", "Maritime"),
            ("tk_freight.freight_land_operation", "Terrestre"),
            ("tk_freight.menu_freight_package_id", "Colis"),
            ("tk_freight.menu_freight_invoicing", "Facturation"),
            ("tk_freight.menu_policy_company", "Compagnie d’assurance"),
            ("tk_freight.menu_freight_archive", "Archives"),
            ("tk_freight.menu_consignee_customer", "Clients"),
            ("tk_freight.menu_shipper", "Expéditeurs"),
            ("tk_freight.menu_consignee", "Destinataires"),
            ("tk_freight.menu_vendors", "Fournisseurs"),
            ("tk_freight.menu_agent", "Agents"),
            ("tk_freight.menu_partner_vendors", "Fournisseurs"),
            ("tk_freight.menu_partner_notify", "Parties à notifier"),
            ("tk_freight.menu_fleet", "Flotte"),
            ("tk_freight.menu_land", "Terrestre"),
            ("tk_freight.menu_fleet_details", "Véhicules"),
            ("tk_freight.menu_ocean", "Maritime"),
            ("tk_freight.menu_freight_vessel_id", "Navires"),
            ("tk_freight.menu_air", "Aérien"),
            ("tk_freight.menu_freight_airline_id", "Compagnies aériennes"),
            ("tk_freight.menu_services", "Services"),
            ("tk_freight.freight_configuration", "Configuration"),
            ("tk_freight.menu_port_locations", "Ports / emplacements"),
            ("tk_freight.menu_freight_port_id", "Ports / emplacements"),
            ("tk_freight.menu_freight_frequent_route", "Itinéraires fréquents"),
            ("tk_freight.menu_other_details", "Autres paramètres"),
            ("tk_freight.menu_freight_move_type_id", "Types de mouvement"),
            ("tk_freight.menu_freight_document_type_id", "Types de documents"),
            ("tk_freight.menu_freight_incoterms_id", "Incoterms"),
            ("tk_freight.menu_stages_details", "Étapes"),
            ("tk_freight.menu_stages", "Étapes"),
            ("tk_freight.menu_policy_details", "Assurance"),
            ("tk_freight.menu_policy_risk", "Risques assurés"),
            ("tk_freight.menu_shipment_tracking", "Suivi des expéditions"),
            ("tk_freight.menu_shipment_tracking_location", "Lieux de suivi"),
            ("tk_freight.menu_shipment_tracking_activity", "Activités de suivi"),
            ("tk_freight.menu_shipment_tracking_template", "Modèles de suivi"),
            ("tk_freight.menu_freight_statement", "Relevés de règlement"),
            ("tk_freight.menu_freight_invoice_receivable", "Factures clients"),
            ("tk_freight.menu_freight_invoice_payable", "Factures fournisseurs"),
        )
        for xmlid, label in menu_labels:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                menu.with_context(lang="fr_FR").write({"name": label})

        replacements = (
            ("Cliente", "Client"), ("Clientes", "Clients"),
            ("Emballer", "Colis"), ("Paquets", "Colis"),
            ("Suivie", "Suivi"),
            ("Citations", "Cotations"), ("Citation", "Cotation"),
            ("Atterrir", "Terrestre"), ("Océan", "Maritime"),
            ("Notifier", "Partie à notifier"),
            ("Société politique", "Compagnie d’assurance"),
            ("Risques politiques", "Risques assurés"),
            ("Expéditrices", "Expéditeurs"), ("Vendeuses", "Fournisseurs"),
        )
        xmlids = TK_OVERLAID_VIEWS
        # ------------------------------------------------------------------
        # L'écran Expéditions
        # ------------------------------------------------------------------
        #
        # Le fournisseur livre bien un catalogue français — 786 paires, dont une
        # seule vide — et il couvre l'architecture des vues (97 références pour
        # le seul formulaire d'expédition). L'écran n'était donc pas « non
        # traduit » : il l'était à moitié, et parfois de travers.
        #
        # Deux causes, une seule table. Sur les 186 chaînes du formulaire, 74
        # étaient absentes du catalogue et restaient en anglais ; d'autres
        # étaient traduites faux — « Create Date » arrivait en « créer un
        # rendez-vous » sur un champ date, ce qui coûte plus cher qu'un mot resté
        # en anglais, parce que c'est une phrase plausible qui décrit autre chose.
        #
        # La table est indexée sur la **source anglaise** : `xml_translate`
        # découpe l'architecture en termes et la clé d'une traduction est
        # toujours le texte anglais, y compris quand le fournisseur en a déjà
        # posé une version fautive.
        view_terms = {
            "Add to Service": "Ajouter au service",
            "Address To": "Adresse de destination",
            "Address Type": "Type d’adresse",
            "Agent Details": "Informations agent",
            "Air Carriage": "Transport aérien",
            "BL Document Type": "Type de connaissement",
            "BL Number": "N° de connaissement",
            "Bill of Landing": "Connaissement",
            "Chargeable Weight": "Poids taxable",
            "Confirm": "Confirmer",
            "Contact Place of Delivery": "Contact du lieu de livraison",
            "Contact Place of Receipt": "Contact du lieu de réception",
            "Container Charges": "Frais de conteneur",
            "Container Items": "Contenu du conteneur",
            "Copy as Draft": "Copier en brouillon",
            "Create Delivery Order": "Créer le bon de livraison",
            "Dangerous Goods Notes": "Détail marchandises dangereuses",
            "Delivery Address": "Adresse de livraison",
            "Destination Warehouse": "Entrepôt de destination",
            "Download Reports": "Télécharger les rapports",
            "Environmental Conditions": "Conditions de conservation",
            "Estimate Arrival": "Arrivée estimée",
            "Estimate Pickup": "Enlèvement estimé",
            "Fee State": "État des frais",
            "First Notify Party": "1re partie à notifier",
            "Freight Collect/Prepaid": "Fret payable / prépayé",
            "Freight Insurance": "Assurance fret",
            "Freight Payable": "Fret payable à",
            "Frequent Location": "Itinéraire fréquent",
            "Generate Statement": "Générer le relevé",
            "Gross Weight(KG)": "Poids brut (kg)",
            "Inland Shipment": "Expédition terrestre",
            "Invoice Date": "Date de facture",
            "Invoice Number": "N° de facture",
            "Issue By": "Émis par",
            "Land Carriage": "Transport routier",
            "Location Place of Delivery": "Lieu de livraison",
            "Location Place of Receipt": "Lieu de réception",
            "Logistics and Compliance": "Logistique et conformité",
            "MAWB No.": "N° LTA mère (MAWB)",
            "Net Weight(KG)": "Poids net (kg)",
            "Ocean Carriage": "Transport maritime",
            "Order": "Commande",
            "Policy No": "N° de police",
            "Qty & Charges": "Quantité et frais",
            "Qty & Type": "Quantité et type",
            "Receive From": "Reçu de",
            "Regulatory Classification": "Classification réglementaire",
            "Report Fields": "Champs du rapport",
            "SI Issue Date": "Date d’émission des instructions",
            "Safety and Handling": "Sécurité et manutention",
            "Second Notify Party": "2e partie à notifier",
            "Settlement Date": "Date de règlement",
            "Ship Owner": "Compagnie maritime",
            "Shipment Label": "Étiquette d’expédition",
            "Shipment Verification": "Vérification de l’expédition",
            "Source Warehouse": "Entrepôt d’origine",
            "Statement Number": "N° de relevé",
            "Statements": "Relevés de règlement",
            "Storage": "Stockage",
            "Street 2": "Rue (complément)",
            "Street": "Rue",
            "Transport Type": "Type de transport",
            "Truck Owner": "Propriétaire du camion",
            "Truck Ref": "Réf. CMR / RWB",
            "Trucker Number": "N° transporteur routier",
            "Unconfirm": "Annuler la confirmation",
            "Valid Date": "Valable jusqu’au",
            "Volume(CBM)": "Volume (m³)",
            "Voyage No.": "N° de voyage",
            "Warehouse": "Entrepôt",
            "Waybill-Land": "Lettre de voiture",
            "Weight & Volume": "Poids et volume",
            "Create Date": "Date de création",
            "Shipment Details": "Détails de l’expédition",
            "Move Type": "Type d’acheminement",
            "Estimate Pickup Time": "Enlèvement estimé",
            "Estimate Arrival Time": "Arrivée estimée",
            "Shipper": "Expéditeur",
            "Consignee": "Destinataire",
            "Packages": "Colis",
            "Quotations": "Cotations",
        }

        # La traduction se pose terme par terme, et jamais en réécrivant
        # `arch_db`.
        #
        # L'écriture directe — `view.with_context(lang="fr_FR").write({"arch_db":
        # …})` — écrasait aussi la valeur `en_US`. Mesuré sur banc : l'arch
        # anglaise du formulaire d'expédition avait perdu « Address Type » et
        # portait « Cotationss ». Le fournisseur ne retrouvait plus son écran, et
        # la mise à jour suivante de son module aurait diffusé notre français
        # comme source. `update_field_translations` n'écrit que la langue
        # demandée.
        for xmlid in xmlids:
            view = self.env.ref(xmlid, raise_if_not_found=False)
            if not view:
                continue
            traductions, _ = view.get_field_translations("arch_db", ["fr_FR"])
            maj = {}
            for entree in traductions:
                source = entree["source"]
                courant = entree["value"] or source
                cible = view_terms.get(source)
                if cible is None:
                    # Aucun terme explicite : on corrige les mots que le
                    # catalogue du fournisseur rend mal, dans la valeur reçue.
                    cible = courant
                    for mauvais, bon in replacements:
                        cible = cible.replace(mauvais, bon)
                if cible != courant:
                    maj[source] = cible
            if maj:
                view.update_field_translations("arch_db", {"fr_FR": maj})

        # Les libellés de champs, corrigés dans le contexte français : `en_US`
        # n'est jamais touché, et une seconde passe réécrit la même valeur.
        field_labels = (
            ("freight.shipment", "create_datetime", "Date de création"),
            ("freight.shipment", "shipper_id", "Expéditeur"),
            ("freight.shipment", "consignee_id", "Destinataire"),
            ("freight.shipment", "pickup_datetime", "Enlèvement estimé"),
            ("freight.shipment", "arrival_datetime", "Arrivée estimée"),
            ("freight.shipment", "move_type", "Type d’acheminement"),
            ("freight.shipment", "address_to", "Type d’adresse"),
            ("freight.shipment", "is_freight_insurance", "Assurance fret"),
            ("freight.shipment", "statement_ids", "Relevés de règlement"),
            ("freight.shipment", "freight_packages", "Colis"),
            ("freight.shipment", "tracking_number", "Numéro de suivi"),
            ("freight.shipment", "dangerous_goods_notes", "Détail marchandises dangereuses"),
            ("freight.shipment", "agent_id", "Agent"),
            ("freight.shipment", "mawb_no", "N° LTA mère (MAWB)"),
            ("freight.shipment", "flight_no", "N° de vol"),
            ("freight.shipment", "bl_number", "N° de connaissement (B/L)"),
            ("freight.shipment", "obl", "Connaissement original (OBL)"),
            ("freight.shipment", "voyage_no", "N° de voyage"),
            ("freight.shipment", "truck_ref", "Réf. CMR / RWB"),
            ("freight.shipment", "trucker_number", "N° transporteur routier"),
            ("freight.shipment", "ship_owner_id", "Compagnie maritime"),
            ("freight.shipment", "source_location_id", "Lieu de départ"),
            ("freight.shipment", "destination_location_id", "Lieu de destination"),
            ("freight.shipment", "transport", "Mode de transport"),
            ("freight.shipment", "direction", "Sens"),
            ("freight.shipment", "operation", "Type d’opération"),
            ("shipment.package.line", "name", "N° de conteneur"),
            ("shipment.package.line", "qty", "Quantité"),
            ("shipment.package.line", "gross_weight", "Poids brut (kg)"),
            ("shipment.package.line", "net_weight", "Poids net (kg)"),
            ("shipment.package.line", "volume", "Volume (m³)"),
        )
        Field = self.env["ir.model.fields"].sudo()
        for model_name, field_name, label in field_labels:
            champ = Field.search(
                [("model", "=", model_name), ("name", "=", field_name)], limit=1
            )
            if champ:
                champ.with_context(lang="fr_FR").write({"field_description": label})

        return True

    def _dally_repair_tk_freight_source_arch(self):
        """Rend au fournisseur son architecture anglaise, une fois.

        Méthode **privée** : le souligné la rend inappelable par RPC. Ce n'est
        pas un geste d'interface, c'est une opération d'exploitation, à jouer
        depuis `odoo shell`, une fois, après décision — sur une base fraîchement
        sauvegardée.

        ## Ce qu'on répare

        L'overlay écrivait `arch_db` dans le contexte français, ce qui écrivait
        les deux langues. La correction empêche que cela recommence ; elle ne
        défait pas ce qui a déjà été écrit. Mesuré en production : **trois** vues
        du fournisseur portent du français dans leur langue source —
        « Cotationss » sur le formulaire d'expédition, « Colis » sur les deux
        vues de colisage.

        ## Pourquoi c'est fermé des deux côtés

        La liste des vues est close, et chacune doit en plus porter un marqueur
        de corruption pour être touchée. Les deux conditions comptent :

        - `reset_arch(mode="hard")` réécrit l'architecture depuis le fichier du
          module. Toute divergence entre la base et le fichier serait donc
          effacée — y compris une divergence légitime, qu'on n'a pas à trancher
          ici. Sans précondition, cette méthode deviendrait un « remets tout
          comme à l'installation », ce qu'elle ne doit pas être.
        - Une vue saine n'est pas touchée, donc la relancer ne fait rien.

        ## Pourquoi depuis le fichier et non depuis une table inverse

        On pourrait remplacer les mots français par leur anglais d'origine. Ce
        serait deviner, et une erreur écrirait notre approximation dans la
        langue source du fournisseur. `reset_arch(mode="hard")` relit le fichier
        XML du module licencié : la seule source qui fasse foi, et c'est la
        sienne.

        :return: les xmlid des vues effectivement réparées.
        """
        reparees = []
        for xmlid in TK_REPAIRABLE_VIEWS:
            view = self.env.ref(xmlid, raise_if_not_found=False)
            if not view or not view.arch_fs:
                continue

            # La précondition : sans marqueur, on ne touche pas. Une vue qui
            # diverge du fichier pour une autre raison n'est pas notre affaire.
            anglais = view.with_context(lang="en_US").arch_db or ""
            if not any(marqueur in anglais for marqueur in TK_CORRUPTION_MARKERS):
                continue

            source = view.with_context(read_arch_from_file=True, lang=None).arch
            if not source or source == anglais:
                continue

            view.reset_arch(mode="hard")
            reparees.append(xmlid)

        if reparees:
            # La remise à zéro efface les traductions des termes qui ont bougé :
            # on repose le français dans la foulée, sinon la réparation rendrait
            # un écran anglais.
            self.dally_apply_tk_freight_fr_overlay()
        return reparees
