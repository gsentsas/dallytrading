# -*- coding: utf-8 -*-
"""Internal Freight cash operations imported from Google Sheets."""

from odoo import fields, _, http

from odoo.addons.dally_api.controllers.main import DallyApiController, DallyApiError


BILLING_GROUP = "dally_freight_billing.group_dally_freight_billing_api"
VALID_SOURCES = frozenset({"legacy_xlsx", "google_sheets", "backoffice"})
STATE_MAP = {
    "review": "review",
    "to_review": "review",
    "validated": "validated",
    "cancelled": "cancelled",
}
EXPENSE_FIELDS = frozenset({
    "request_uuid", "external_expense_key", "expense_date", "category",
    "description", "beneficiary", "currency_code", "total_eur_snapshot",
    "total_xof_snapshot", "payment_method", "reference", "state", "comment",
    "source", "allocations",
})
TRANSFER_FIELDS = frozenset({
    "request_uuid", "external_transfer_key", "transfer_date", "from_actor",
    "to_actor", "amount", "currency_code", "total_eur_snapshot",
    "total_xof_snapshot", "reason", "payment_method", "state", "comment", "source",
})
ALLOCATION_FIELDS = frozenset({"actor", "amount"})


class DallyFreightCashController(DallyApiController):

    @http.route(
        "/api/v1/freight/expense", type="http", auth="none", readonly=False,
        methods=["POST"], csrf=False, save_session=False,
    )
    def sync_expense(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/freight/expense",
            required_scope="freight:cash",
            handler=self._sync_expense,
        )

    @http.route(
        "/api/v1/freight/cash-transfer", type="http", auth="none", readonly=False,
        methods=["POST"], csrf=False, save_session=False,
    )
    def sync_cash_transfer(self, **kwargs):
        return self._handle(
            endpoint="/api/v1/freight/cash-transfer",
            required_scope="freight:cash",
            handler=self._sync_transfer,
        )

    def _check_group(self, env):
        if not env.user.has_group(BILLING_GROUP):
            raise DallyApiError(
                403, "forbidden",
                _("This API user is not allowed to synchronise internal cash operations."),
            )

    def _sync_expense(self, env, payload, api_key):
        self._check_group(env)
        self._reject_unknown(payload, EXPENSE_FIELDS, "expense")
        self._require(
            payload, "external_expense_key", "expense_date", "category",
            "description", "currency_code",
        )
        currency = self._currency(env, payload.get("currency_code"))
        allocations = payload.get("allocations") or []
        if not isinstance(allocations, list):
            raise DallyApiError(422, "invalid_allocations", _("allocations must be an array."))
        clean_allocations = []
        for index, item in enumerate(allocations, start=1):
            if not isinstance(item, dict):
                raise DallyApiError(422, "invalid_allocation", _("Allocation %s must be an object.", index))
            unknown = sorted(set(item) - ALLOCATION_FIELDS)
            if unknown:
                raise DallyApiError(
                    422, "unknown_allocation_fields",
                    _("Unknown allocation field(s): %s", ", ".join(unknown)),
                )
            actor = str(item.get("actor") or "").strip()
            amount = self._positive_or_zero(item.get("amount"), "allocation.amount")
            if actor and amount > 0:
                clean_allocations.append({"actor_name": actor, "amount": amount})
        if not clean_allocations:
            raise DallyApiError(422, "missing_allocations", _("At least one positive expense allocation is required."))

        values = {
            "external_expense_key": str(payload["external_expense_key"]).strip(),
            "expense_date": self._date(payload.get("expense_date"), "expense_date"),
            "category": str(payload["category"]).strip(),
            "description": str(payload["description"]).strip(),
            "beneficiary": str(payload.get("beneficiary") or "").strip() or False,
            "currency_id": currency.id,
            "total_eur_snapshot": self._positive_or_zero(payload.get("total_eur_snapshot"), "total_eur_snapshot"),
            "total_xof_snapshot": self._positive_or_zero(payload.get("total_xof_snapshot"), "total_xof_snapshot"),
            "payment_method": str(payload.get("payment_method") or "").strip() or False,
            "reference": str(payload.get("reference") or "").strip() or False,
            "state": self._state(payload.get("state")),
            "comment": str(payload.get("comment") or "").strip() or False,
            "source": self._source(payload.get("source")),
        }
        record, created = env["dally.cash.expense"].upsert_from_sync(values, clean_allocations)
        return {
            "expense_id": record.id,
            "external_expense_key": record.external_expense_key,
            "created": created,
            "state": record.state,
            "currency": record.currency_id.name,
            "total_amount": record.total_amount,
            "total_eur_snapshot": record.total_eur_snapshot,
            "total_xof_snapshot": record.total_xof_snapshot,
            "_record": record,
        }, 201 if created else 200

    def _sync_transfer(self, env, payload, api_key):
        self._check_group(env)
        self._reject_unknown(payload, TRANSFER_FIELDS, "cash transfer")
        self._require(
            payload, "external_transfer_key", "transfer_date", "from_actor",
            "to_actor", "amount", "currency_code",
        )
        currency = self._currency(env, payload.get("currency_code"))
        amount = self._number(payload.get("amount"), "amount")
        if amount <= 0:
            raise DallyApiError(422, "invalid_amount", _("amount must be greater than zero."))
        from_actor = str(payload.get("from_actor") or "").strip()
        to_actor = str(payload.get("to_actor") or "").strip()
        if from_actor.casefold() == to_actor.casefold():
            raise DallyApiError(422, "same_actor", _("Transfer sender and recipient must differ."))
        values = {
            "external_transfer_key": str(payload["external_transfer_key"]).strip(),
            "transfer_date": self._date(payload.get("transfer_date"), "transfer_date"),
            "from_actor": from_actor,
            "to_actor": to_actor,
            "amount": amount,
            "currency_id": currency.id,
            "total_eur_snapshot": self._positive_or_zero(payload.get("total_eur_snapshot"), "total_eur_snapshot"),
            "total_xof_snapshot": self._positive_or_zero(payload.get("total_xof_snapshot"), "total_xof_snapshot"),
            "reason": str(payload.get("reason") or "").strip() or False,
            "payment_method": str(payload.get("payment_method") or "").strip() or False,
            "state": self._state(payload.get("state")),
            "comment": str(payload.get("comment") or "").strip() or False,
            "source": self._source(payload.get("source")),
        }
        record, created = env["dally.cash.transfer"].upsert_from_sync(values)
        return {
            "transfer_id": record.id,
            "external_transfer_key": record.external_transfer_key,
            "created": created,
            "state": record.state,
            "currency": record.currency_id.name,
            "amount": record.amount,
            "total_eur_snapshot": record.total_eur_snapshot,
            "total_xof_snapshot": record.total_xof_snapshot,
            "_record": record,
        }, 201 if created else 200

    @staticmethod
    def _reject_unknown(payload, allowlist, label):
        unknown = sorted(set(payload) - allowlist)
        if unknown:
            raise DallyApiError(
                422, "unknown_fields",
                _("Unknown %(label)s field(s): %(fields)s", label=label, fields=", ".join(unknown)),
            )

    @staticmethod
    def _currency(env, code):
        code = str(code or "").strip().upper()
        currency = env["res.currency"].search([("name", "=", code), ("active", "=", True)], limit=1)
        if not currency:
            raise DallyApiError(422, "unknown_currency", _("Unknown or inactive currency."))
        return currency

    @staticmethod
    def _date(value, field_name):
        try:
            result = fields.Date.to_date(value)
        except (TypeError, ValueError) as exc:
            raise DallyApiError(422, "invalid_date", _("Invalid %s.", field_name)) from exc
        if not result:
            raise DallyApiError(422, "invalid_date", _("Invalid %s.", field_name))
        return result

    @staticmethod
    def _number(value, field_name):
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise DallyApiError(422, "invalid_number", _("%s must be numeric.", field_name)) from exc

    @classmethod
    def _positive_or_zero(cls, value, field_name):
        if value in (None, "", False):
            return 0.0
        number = cls._number(value, field_name)
        if number < 0:
            raise DallyApiError(422, "invalid_number", _("%s cannot be negative.", field_name))
        return number

    @staticmethod
    def _source(value):
        source = str(value or "google_sheets").strip()
        if source not in VALID_SOURCES:
            raise DallyApiError(422, "invalid_source", _("Invalid cash operation source."))
        return source

    @staticmethod
    def _state(value):
        state = str(value or "review").strip().lower()
        state = STATE_MAP.get(state)
        if not state:
            raise DallyApiError(422, "invalid_state", _("Invalid cash operation state."))
        return state
