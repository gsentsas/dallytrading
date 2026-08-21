# -*- coding: utf-8 -*-
"""Helpers for the customer-facing DallyTrading Freight invoice report."""

from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

    def dally_freight_format_amount(self, amount, currency=None):
        self.ensure_one()
        currency = currency or self.currency_id

        digits = currency.decimal_places
        text = f"{amount or 0.0:,.{digits}f}"
        text = text.replace(",", " ").replace(".", ",")

        symbol = currency.symbol or currency.name

        if currency.position == "before":
            return f"{symbol} {text}"

        return f"{text} {symbol}"

    def dally_freight_format_quantity(self, quantity):
        self.ensure_one()

        text = f"{quantity or 0.0:.3f}".rstrip("0").rstrip(".")

        if "." not in text:
            text += ".00"
        elif len(text.split(".")[1]) == 1:
            text += "0"

        return text.replace(".", ",")

    def dally_freight_report_context(self):
        """Return presentation-only information for the Freight invoice PDF.

        Collections remain operational cash entries until native accounting
        registration occurs. For draft invoices, the displayed remaining
        balance is therefore explicitly indicative.
        """
        self.ensure_one()

        shipment = self.dally_freight_shipment_id

        if not shipment:
            return {}

        mode_labels = {
            "air": "Fret aérien",
            "sea": "Fret maritime",
            "road": "Fret routier",
        }

        mode_label = mode_labels.get(
            shipment.transport_mode,
            shipment.transport_mode or "Fret",
        )

        freight_lines = []

        normal_lines = self.invoice_line_ids.filtered(
            lambda line: line.display_type == "product"
        )

        for line in normal_lines:
            package = line.sale_line_ids.mapped(
                "dally_freight_package_id"
            )[:1]

            if package:
                description = (
                    package.description
                    or shipment.goods_description
                    or "Marchandises"
                )

                designation = f"{mode_label} - {description}"

                quantity = package.billable_weight_kg
                unit_label = "kg"
                unit_price = package.applied_unit_price_eur
            else:
                designation = line.name or "Frais"
                quantity = line.quantity
                unit_label = ""
                unit_price = line.price_unit

            freight_lines.append({
                "designation": designation,
                "quantity": quantity,
                "unit_label": unit_label,
                "unit_price": unit_price,
                "subtotal": line.price_subtotal,
            })

        collections = self.env[
            "dally.freight.collection"
        ].sudo().search([
            ("shipment_id", "=", shipment.id),
        ], order="payment_date,id")

        method_labels = {
            "wave": "Wave",
            "bank_transfer": "Virement bancaire",
            "cash": "Espèces",
        }

        state_labels = {
            "pending": "En attente de comptabilisation",
            "registered": "Comptabilisé",
            "error": "Erreur de comptabilisation",
        }

        collection_rows = []
        received_equivalent_raw = 0.0

        for collection in collections:
            equivalent = collection.currency_id._convert(
                collection.amount,
                self.currency_id,
                self.company_id,
                collection.payment_date,
                round=False,
            )

            received_equivalent_raw += equivalent

            collector = (
                collection.collected_by_id.name
                or collection.collected_by_name
                or ""
            )

            collection_rows.append({
                "date": collection.payment_date,
                "method_label": method_labels.get(
                    collection.source_method,
                    collection.source_method,
                ),
                "amount": collection.amount,
                "currency": collection.currency_id,
                "equivalent": self.currency_id.round(
                    equivalent
                ),
                "state_label": state_labels.get(
                    collection.state,
                    collection.state,
                ),
                "collector": collector,
            })

        received_equivalent = self.currency_id.round(
            received_equivalent_raw
        )

        if self.state == "posted":
            balance_due = self.amount_residual
            balance_label = "Solde comptable"
        else:
            balance_due = max(
                self.currency_id.round(
                    self.amount_total
                    - received_equivalent_raw
                ),
                0.0,
            )
            balance_label = (
                "Solde indicatif après encaissements"
            )

        if self.state == "draft":
            document_title = "FACTURE - BROUILLON"
        elif self.state == "cancel":
            document_title = "FACTURE - ANNULÉE"
        else:
            document_title = "FACTURE"

        return {
            "shipment": shipment,
            "document_title": document_title,
            "dossier_reference": (
                shipment.external_reference
                or shipment.reference
                or ""
            ),
            "sale_order": (
                shipment.sale_order_id.name
                if shipment.sale_order_id
                else ""
            ),
            "mode_label": mode_label,
            "freight_lines": freight_lines,
            "collections": collection_rows,
            "received_equivalent": received_equivalent,
            "balance_due": balance_due,
            "balance_label": balance_label,
        }
