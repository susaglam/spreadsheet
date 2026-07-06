# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSpreadsheetApiToken(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Token = cls.env["spreadsheet.api.token"]
        cls.Event = cls.env["spreadsheet.api.webhook.event"]
        cls.Spreadsheet = cls.env["spreadsheet.spreadsheet"]
        cls.token = cls.Token.create({"name": "Test token"})

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def test_authenticate_valid(self):
        result = self.Token.authenticate(self.token.token)
        self.assertEqual(result, self.token)
        # usage counter incremented atomically
        self.assertEqual(self.token.usage_count, 1)
        self.assertTrue(self.token.last_used)

    def test_authenticate_empty(self):
        self.assertFalse(self.Token.authenticate(False))
        self.assertFalse(self.Token.authenticate(""))

    def test_authenticate_unknown_token(self):
        self.assertFalse(self.Token.authenticate("does-not-exist"))

    def test_authenticate_inactive(self):
        self.token.active = False
        self.assertFalse(self.Token.authenticate(self.token.token))

    def test_authenticate_expired(self):
        self.token.expires_at = fields.Datetime.now() - timedelta(days=1)
        self.assertFalse(self.Token.authenticate(self.token.token))

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    def test_rate_limit_blocks_after_limit(self):
        self.token.rate_limit_per_minute = 2
        # Fresh in-memory bucket for this token id.
        self.Token._rate_buckets.pop(self.token.id, None)
        self.assertEqual(self.Token.authenticate(self.token.token), self.token)
        self.assertEqual(self.Token.authenticate(self.token.token), self.token)
        self.assertEqual(self.Token.authenticate(self.token.token), "RATE_LIMITED")
        self.assertEqual(self.token.rate_limit_exceeded_count, 1)

    def test_rate_limit_zero_is_unlimited(self):
        self.token.rate_limit_per_minute = 0
        self.Token._rate_buckets.pop(self.token.id, None)
        for _i in range(5):
            self.assertEqual(self.Token.authenticate(self.token.token), self.token)

    # ------------------------------------------------------------------
    # Webhook URL validation (SSRF guard)
    # ------------------------------------------------------------------
    def test_webhook_url_rejects_loopback(self):
        with self.assertRaises((UserError, ValidationError)):
            self.token.webhook_url = "http://127.0.0.1/hook"

    def test_webhook_url_rejects_link_local_metadata(self):
        with self.assertRaises((UserError, ValidationError)):
            self.token.webhook_url = "http://169.254.169.254/latest/meta-data"

    def test_webhook_url_rejects_bad_scheme(self):
        with self.assertRaises((UserError, ValidationError)):
            self.token.webhook_url = "ftp://example.com/hook"

    def test_webhook_url_accepts_public_ip(self):
        # Numeric IP avoids DNS lookups in CI; 8.8.8.8 is a public address.
        self.token.webhook_url = "https://8.8.8.8/hook"
        self.assertEqual(self.token.webhook_url, "https://8.8.8.8/hook")

    # ------------------------------------------------------------------
    # Webhook event triggering / coalescing
    # ------------------------------------------------------------------
    def test_create_spreadsheet_enqueues_create_event(self):
        self.token.webhook_url = "https://8.8.8.8/hook"
        sheet = self.Spreadsheet.create({"name": "WH sheet"})
        events = self.Event.search(
            [
                ("token_id", "=", self.token.id),
                ("spreadsheet_id", "=", sheet.id),
                ("event_type", "=", "create"),
            ]
        )
        self.assertEqual(len(events), 1)

    def test_update_events_are_coalesced(self):
        self.token.webhook_url = "https://8.8.8.8/hook"
        sheet = self.Spreadsheet.create({"name": "Coalesce sheet"})
        sheet._trigger_webhooks("update")
        sheet._trigger_webhooks("update")
        pending = self.Event.search(
            [
                ("token_id", "=", self.token.id),
                ("spreadsheet_id", "=", sheet.id),
                ("event_type", "=", "update"),
                ("delivered", "=", False),
            ]
        )
        self.assertEqual(len(pending), 1)

    def test_scoped_token_skips_unrelated_spreadsheet(self):
        other = self.Spreadsheet.create({"name": "Scoped-only"})
        scoped = self.Token.create(
            {
                "name": "Scoped token",
                "webhook_url": "https://8.8.8.8/hook",
                "spreadsheet_ids": [(6, 0, other.ids)],
            }
        )
        unrelated = self.Spreadsheet.create({"name": "Unrelated"})
        events = self.Event.search(
            [
                ("token_id", "=", scoped.id),
                ("spreadsheet_id", "=", unrelated.id),
            ]
        )
        self.assertFalse(events)
