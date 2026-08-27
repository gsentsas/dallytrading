from odoo.exceptions import ConcurrencyError, ValidationError
from odoo.service.model import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
from odoo.tests.common import TransactionCase

from ..controllers.main import DALLY_API_RETRY_EXCEPTIONS


class TestHttpRetryExceptions(TransactionCase):
    def test_retry_classification_matches_odoo(self):
        for exception in (ConcurrencyError, *PG_CONCURRENCY_EXCEPTIONS_TO_RETRY):
            self.assertIn(exception, DALLY_API_RETRY_EXCEPTIONS)
        self.assertNotIn(RuntimeError, DALLY_API_RETRY_EXCEPTIONS)
        self.assertNotIn(ValidationError, DALLY_API_RETRY_EXCEPTIONS)
