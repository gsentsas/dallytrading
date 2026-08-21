# -*- coding: utf-8 -*-
"""Internal cash operations imported from the Freight workbook.

These records are operational cash tracking, not customer accounting entries.
They deliberately remain separate from ``account.move`` / ``account.payment``.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


VALID_SOURCES = frozenset({"legacy_xlsx", "google_sheets", "backoffice"})
VALID_STATES = frozenset({"review", "validated", "cancelled"})


class DallyCashExpense(models.Model):
    _name = "dally.cash.expense"
    _description = "DallyTrading Internal Cash Expense"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "expense_date desc, id desc"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True, ondelete="cascade",
    )
    external_expense_key = fields.Char(required=True, index=True, copy=False, tracking=True)
    expense_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    category = fields.Char(required=True, tracking=True)
    description = fields.Char(required=True, tracking=True)
    beneficiary = fields.Char(tracking=True)
    currency_id = fields.Many2one("res.currency", required=True, tracking=True)
    allocation_ids = fields.One2many(
        "dally.cash.expense.allocation", "expense_id", string="Paid by",
        copy=True,
    )
    total_amount = fields.Monetary(
        currency_field="currency_id", compute="_compute_total_amount", store=True,
    )
    total_eur_snapshot = fields.Monetary(
        currency_field="eur_currency_id", string="Workbook total EUR",
    )
    total_xof_snapshot = fields.Monetary(
        currency_field="xof_currency_id", string="Workbook total XOF",
    )
    eur_currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.ref("base.EUR"), required=True,
    )
    xof_currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.ref("base.XOF"), required=True,
    )
    payment_method = fields.Char(tracking=True)
    reference = fields.Char(tracking=True)
    state = fields.Selection(
        [("review", "To review"), ("validated", "Validated"), ("cancelled", "Cancelled")],
        default="review", required=True, tracking=True,
    )
    source = fields.Selection(
        [("legacy_xlsx", "Legacy XLSX"), ("google_sheets", "Google Sheets"), ("backoffice", "Back-office")],
        default="google_sheets", required=True, tracking=True,
    )
    comment = fields.Text()
    last_sync_at = fields.Datetime(copy=False, readonly=True)

    _external_expense_key_unique = models.Constraint(
        "UNIQUE(company_id, external_expense_key)",
        "The external expense key must be unique per company.",
    )

    @api.depends("allocation_ids.amount")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.allocation_ids.mapped("amount"))

    @api.constrains("total_eur_snapshot", "total_xof_snapshot")
    def _check_snapshots_non_negative(self):
        for rec in self:
            if rec.total_eur_snapshot < 0 or rec.total_xof_snapshot < 0:
                raise ValidationError(_("Expense snapshot totals cannot be negative."))

    @api.model
    def upsert_from_sync(self, values, allocations):
        key = str(values.get("external_expense_key") or "").strip()
        if not key:
            raise ValidationError(_("external_expense_key is required."))
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ["dally-cash-expense:%s:%s" % (self.env.company.id, key)],
        )
        rec = self.search([
            ("company_id", "=", self.env.company.id),
            ("external_expense_key", "=", key),
        ], limit=1)
        created = not bool(rec)
        values = dict(values, company_id=self.env.company.id, last_sync_at=fields.Datetime.now())
        if rec:
            rec.write(values)
        else:
            rec = self.create(values)
        # Replace the operational allocation snapshot atomically.  This model is
        # not a posted accounting journal, so corrected Sheet rows may update it.
        rec.allocation_ids.unlink()
        if allocations:
            self.env["dally.cash.expense.allocation"].create([
                {"expense_id": rec.id, **vals} for vals in allocations
            ])
        return rec, created


class DallyCashExpenseAllocation(models.Model):
    _name = "dally.cash.expense.allocation"
    _description = "DallyTrading Cash Expense Allocation"
    _order = "id"

    expense_id = fields.Many2one(
        "dally.cash.expense", required=True, ondelete="cascade", index=True,
    )
    actor_name = fields.Char(required=True)
    amount = fields.Monetary(currency_field="currency_id", required=True)
    currency_id = fields.Many2one(related="expense_id.currency_id", store=True, readonly=True)

    @api.constrains("amount")
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_("Expense allocation amount cannot be negative."))


class DallyCashTransfer(models.Model):
    _name = "dally.cash.transfer"
    _description = "DallyTrading Internal Cash Transfer"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "transfer_date desc, id desc"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True, ondelete="cascade",
    )
    external_transfer_key = fields.Char(required=True, index=True, copy=False, tracking=True)
    transfer_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    from_actor = fields.Char(required=True, tracking=True)
    to_actor = fields.Char(required=True, tracking=True)
    amount = fields.Monetary(currency_field="currency_id", required=True, tracking=True)
    currency_id = fields.Many2one("res.currency", required=True, tracking=True)
    total_eur_snapshot = fields.Monetary(currency_field="eur_currency_id", string="Workbook EUR")
    total_xof_snapshot = fields.Monetary(currency_field="xof_currency_id", string="Workbook XOF")
    eur_currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.ref("base.EUR"), required=True,
    )
    xof_currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.ref("base.XOF"), required=True,
    )
    reason = fields.Char()
    payment_method = fields.Char()
    state = fields.Selection(
        [("review", "To review"), ("validated", "Validated"), ("cancelled", "Cancelled")],
        default="review", required=True, tracking=True,
    )
    source = fields.Selection(
        [("legacy_xlsx", "Legacy XLSX"), ("google_sheets", "Google Sheets"), ("backoffice", "Back-office")],
        default="google_sheets", required=True, tracking=True,
    )
    comment = fields.Text()
    last_sync_at = fields.Datetime(copy=False, readonly=True)

    _external_transfer_key_unique = models.Constraint(
        "UNIQUE(company_id, external_transfer_key)",
        "The external transfer key must be unique per company.",
    )

    @api.constrains("amount", "total_eur_snapshot", "total_xof_snapshot")
    def _check_non_negative(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("Cash transfer amount must be greater than zero."))
            if rec.total_eur_snapshot < 0 or rec.total_xof_snapshot < 0:
                raise ValidationError(_("Transfer snapshot totals cannot be negative."))

    @api.model
    def upsert_from_sync(self, values):
        key = str(values.get("external_transfer_key") or "").strip()
        if not key:
            raise ValidationError(_("external_transfer_key is required."))
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ["dally-cash-transfer:%s:%s" % (self.env.company.id, key)],
        )
        rec = self.search([
            ("company_id", "=", self.env.company.id),
            ("external_transfer_key", "=", key),
        ], limit=1)
        created = not bool(rec)
        values = dict(values, company_id=self.env.company.id, last_sync_at=fields.Datetime.now())
        if rec:
            rec.write(values)
        else:
            rec = self.create(values)
        return rec, created
