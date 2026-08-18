# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import AccessDenied, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "dally")
class TestDallyApiKey(TransactionCase):
    """Authentication is the only thing standing between the API and the CRM."""

    def setUp(self):
        super().setUp()
        self.Key = self.env["dally.api.key"]

    def _create_key(self, **overrides):
        values = {"name": "Test Key", "scopes": "leads:write"}
        values.update(overrides)
        return self.Key.create(values)

    # ─── Generation and storage ───────────────────────────────────────

    def test_key_generated_on_create(self):
        key = self._create_key()
        self.assertTrue(key.key_hash)
        self.assertTrue(key.key_prefix)
        self.assertTrue(key.key_to_display, "The raw key must be shown once")

    def test_raw_key_is_not_stored(self):
        """Only a hash may persist. A stored key means a database dump is a breach."""
        key = self._create_key()
        raw = key.key_to_display

        key.invalidate_recordset()
        self.assertFalse(
            key.key_to_display,
            "key_to_display must not be stored — it is a non-stored field",
        )
        self.assertNotEqual(key.key_hash, raw)
        self.assertEqual(key.key_hash, self.Key._hash_key(raw))

    def test_prefix_matches_key_start(self):
        key = self._create_key()
        self.assertTrue(key.key_to_display.startswith(key.key_prefix))

    def test_keys_are_distinct(self):
        keys = {self._create_key(name="K%s" % i).key_to_display for i in range(20)}
        self.assertEqual(len(keys), 20)

    def test_regeneration_invalidates_previous_key(self):
        key = self._create_key()
        old_raw = key.key_to_display
        key.action_generate_key()
        self.assertNotEqual(key.key_to_display, old_raw)
        with self.assertRaises(AccessDenied):
            self.Key._authenticate(old_raw, source_ip="127.0.0.1")

    # ─── Authentication ───────────────────────────────────────────────

    def test_authenticates_valid_key(self):
        key = self._create_key()
        self.assertEqual(
            self.Key._authenticate(key.key_to_display, source_ip="127.0.0.1"),
            key,
        )

    def test_rejects_unknown_key(self):
        with self.assertRaises(AccessDenied):
            self.Key._authenticate("not-a-real-key-at-all", source_ip="127.0.0.1")

    def test_rejects_empty_and_non_string(self):
        for value in ("", None, 12345, [], {}):
            with self.subTest(value=value), self.assertRaises(AccessDenied):
                self.Key._authenticate(value, source_ip="127.0.0.1")

    def test_rejects_deactivated_key(self):
        """Deactivating must revoke immediately — that is the incident response."""
        key = self._create_key()
        raw = key.key_to_display
        key.active = False
        with self.assertRaises(AccessDenied):
            self.Key._authenticate(raw, source_ip="127.0.0.1")

    def test_rejects_expired_key(self):
        key = self._create_key(expires_on=date.today() - timedelta(days=1))
        with self.assertRaises(AccessDenied):
            self.Key._authenticate(key.key_to_display, source_ip="127.0.0.1")

    def test_accepts_key_expiring_in_the_future(self):
        key = self._create_key(expires_on=date.today() + timedelta(days=30))
        self.assertEqual(
            self.Key._authenticate(key.key_to_display, source_ip="127.0.0.1"),
            key,
        )

    def test_rejects_disallowed_source_ip(self):
        """A key leaked off-server is useless if pinned to localhost."""
        key = self._create_key(allowed_ips="127.0.0.1")
        with self.assertRaises(AccessDenied):
            self.Key._authenticate(key.key_to_display, source_ip="203.0.113.7")

    def test_empty_allowlist_permits_any_ip(self):
        key = self._create_key(allowed_ips="")
        self.assertEqual(
            self.Key._authenticate(key.key_to_display, source_ip="203.0.113.7"),
            key,
        )

    def test_allowlist_accepts_multiple_addresses(self):
        key = self._create_key(allowed_ips="127.0.0.1, 10.0.0.5")
        self.assertEqual(
            self.Key._authenticate(key.key_to_display, source_ip="10.0.0.5"),
            key,
        )

    # ─── Scopes ───────────────────────────────────────────────────────

    def test_has_scope(self):
        key = self._create_key(scopes="leads:write,tracking:read")
        self.assertTrue(key.has_scope("leads:write"))
        self.assertTrue(key.has_scope("tracking:read"))
        self.assertFalse(key.has_scope("customers:read"))

    def test_scope_whitespace_tolerated(self):
        key = self._create_key(scopes=" leads:write , tracking:read ")
        self.assertTrue(key.has_scope("leads:write"))
        self.assertTrue(key.has_scope("tracking:read"))

    def test_unknown_scope_rejected(self):
        """A typo must fail at write time, not silently break every request."""
        with self.assertRaises(ValidationError):
            self._create_key(scopes="lead:write")

    # ─── Acting user ──────────────────────────────────────────────────

    def test_defaults_to_integration_user(self):
        key = self._create_key()
        self.assertEqual(
            key.user_id,
            self.env.ref("dally_api.user_dally_api_integration"),
        )

    def test_integration_user_is_not_a_superuser(self):
        """The API must not run with system rights."""
        user = self.env.ref("dally_api.user_dally_api_integration")
        self.assertFalse(
            user.has_group("base.group_system"),
            "The integration user must not hold Odoo system administration rights",
        )
        self.assertTrue(user.has_group("dally_core.group_dally_commercial"))

    # ─── Lifecycle ────────────────────────────────────────────────────

    def test_cannot_delete_key_with_history(self):
        """An audit trail pointing at a deleted key is not an audit trail."""
        key = self._create_key()
        self.env["dally.api.request"].create({
            "request_uuid": "test-uuid-history",
            "endpoint": "/api/v1/leads",
            "status_code": 201,
            "api_key_id": key.id,
        })
        with self.assertRaises(UserError):
            key.unlink()

    def test_can_delete_unused_key(self):
        key = self._create_key()
        key.unlink()
        self.assertFalse(key.exists())

    def test_register_use_defers_counting_out_of_the_transaction(self):
        """L'usage n'est plus compté pendant la requête, et c'est le but.

        Ce test affirmait l'inverse : `_register_use()` puis `request_count == 1`
        dans la foulée. Cette écriture immédiate était la source de la contention
        — dix requêtes concurrentes sur la même clé produisaient cinq
        `SerializationFailure`, mesurés en production.

        Le compteur est désormais alimenté après le commit, par un événement que
        le cron replie. La propriété vérifiée ici est donc l'absence d'écriture,
        plus un contrôle positif : le callback est bien posé, sinon « rien n'est
        écrit » serait vrai d'une télémétrie devenue muette.
        """
        key = self._create_key()
        self.assertEqual(key.request_count, 0)
        avant = len(self.env.cr.postcommit)

        key._register_use()
        self.env.cr.flush()

        key.invalidate_recordset()
        self.assertEqual(key.request_count, 0)
        self.assertEqual(len(self.env.cr.postcommit), avant + 1)
