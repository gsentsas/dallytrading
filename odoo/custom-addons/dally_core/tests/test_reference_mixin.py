# -*- coding: utf-8 -*-
import re
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestDallyReferenceMixin(TransactionCase):
    """References are quoted by customers in e-mails and on the phone.

    They must be unique, correctly formatted, and must never be silently
    replaced by a placeholder when something goes wrong.
    """

    #: DT-2026-000001
    REFERENCE_RE = re.compile(r"^DT-\d{4}-\d{6}$")

    def setUp(self):
        super().setUp()
        self.Mixin = self.env["dally.reference.mixin"]
        self.Sequence = self.env["ir.sequence"]

    def test_sequence_exists(self):
        sequence = self.Sequence.search([("code", "=", "dally.reference")], limit=1)
        self.assertTrue(sequence, "The dally.reference sequence must be installed")
        self.assertEqual(sequence.padding, 6)
        self.assertEqual(sequence.prefix, "DT-%(year)s-")

    def test_sequence_produces_expected_format(self):
        reference = self.Sequence.next_by_code("dally.reference")
        self.assertIsNotNone(reference)
        self.assertRegex(
            reference,
            self.REFERENCE_RE,
            "Expected the DT-YYYY-NNNNNN format required by the specification",
        )

    def test_sequence_values_are_distinct(self):
        """Concurrent website submissions must not receive the same number."""
        drawn = {self.Sequence.next_by_code("dally.reference") for _ in range(25)}
        self.assertEqual(len(drawn), 25, "The sequence handed out a duplicate")

    def test_missing_sequence_code_raises(self):
        """A model that forgets _dally_sequence_code must fail loudly.

        Falling back to a placeholder would let several records share a
        reference, which is exactly what the reference is meant to prevent.
        """
        with self.assertRaises(UserError):
            self.Mixin._dally_next_reference()

    def test_next_reference_uses_declared_sequence(self):
        with patch.object(
            type(self.Mixin), "_dally_sequence_code", "dally.reference"
        ):
            reference = self.Mixin._dally_next_reference()
        self.assertRegex(reference, self.REFERENCE_RE)

    def test_unknown_sequence_code_raises(self):
        """A typo in the code must surface, not produce an empty reference."""
        with patch.object(
            type(self.Mixin), "_dally_sequence_code", "dally.does.not.exist"
        ):
            with self.assertRaises(UserError):
                self.Mixin._dally_next_reference()

    def test_mixin_is_abstract(self):
        """The mixin must not create a table of its own."""
        self.assertTrue(
            self.Mixin._abstract,
            "dally.reference.mixin must remain an AbstractModel",
        )
