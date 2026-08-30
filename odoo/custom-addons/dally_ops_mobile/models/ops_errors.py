# -*- coding: utf-8 -*-
"""Erreurs métier stables de l'API Dally Ops."""

from odoo.exceptions import UserError


class DallyOpsError(UserError):
    code = "invalid_request"
    status = 400

    def __init__(self, message, *, code=None, status=None):
        super().__init__(message)
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status


class DallyOpsNotFound(DallyOpsError):
    status = 404


class DallyOpsConflict(DallyOpsError):
    status = 409


class DallyOpsInternal(DallyOpsError):
    code = "internal_inconsistency"
    status = 500
