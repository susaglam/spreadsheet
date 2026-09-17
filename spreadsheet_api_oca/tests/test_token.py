# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import hashlib
from datetime import timedelta

from odoo import fields
from odoo.api import SUPERUSER_ID
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.models import get_public_method
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from ..tools.rate_limit import SlidingWindowLimiter, client_ip_bucket
from .common import SpreadsheetApiCommonMixin


@tagged("post_install", "-at_install")
class TestSpreadsheetApiToken(SpreadsheetApiCommonMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_api_data()
        cls.token = cls.Token.create(
            {"name": "Test token", "user_id": cls.sheet_user.id}
        )
        cls.secret = cls.token._generate_token()

    # ------------------------------------------------------------------
    # Hashed storage
    # ------------------------------------------------------------------
    def test_plaintext_is_not_stored(self):
        self.assertNotIn("token", self.Token._fields)
        self.assertEqual(
            self.token.token_hash, hashlib.sha256(self.secret.encode()).hexdigest()
        )
        self.assertNotEqual(self.token.token_hash, self.secret)
        self.assertTrue(self.secret.startswith(self.token.token_hint.rstrip("…")))

    def test_new_token_has_no_secret_until_generated(self):
        token = self.Token.create({"name": "Fresh", "user_id": self.sheet_user.id})
        self.assertFalse(token.token_hash)
        self.assertFalse(token.token_hint)

    def test_action_generate_token_shows_secret_once(self):
        action = self.token.with_user(self.sheet_user).action_generate_token()
        self.assertEqual(action["res_model"], "spreadsheet.api.token.show")
        new_secret = action["context"]["default_token"]
        self.assertEqual(
            self.token.token_hash, hashlib.sha256(new_secret.encode()).hexdigest()
        )
        # The previous secret stopped working, the new one works.
        self.assertFalse(self.Token._authenticate(self.secret))
        self.assertEqual(self.Token._authenticate(new_secret), self.token)

    def test_generate_token_requires_write_access(self):
        with self.assertRaises(AccessError):
            self.token.with_user(self.other_sheet_user).action_generate_token()

    def test_non_admin_manager_cannot_regenerate_administrator_token(self):
        # An administrator made a token for himself; a Spreadsheet manager
        # without administration rights must not obtain its secret.
        admin = self.env.ref("base.user_admin")
        admin_token = self.Token.create({"name": "Admin's own", "user_id": admin.id})
        admin_secret = admin_token._generate_token()
        old_hash = admin_token.token_hash
        with self.assertRaises(AccessError):
            admin_token.with_user(self.sheet_manager).action_generate_token()
        admin_token.invalidate_recordset(["token_hash"])
        self.assertEqual(admin_token.token_hash, old_hash)
        self.assertEqual(self.Token._authenticate(admin_secret), admin_token)
        # Nor redirect its webhook or change anything else on it.
        with self.assertRaises(AccessError):
            admin_token.with_user(self.sheet_manager).write({"name": "Hijacked"})
        # An administrator may.
        action = admin_token.with_user(admin).action_generate_token()
        self.assertTrue(action["context"]["default_token"])

    def test_manager_can_regenerate_non_admin_token(self):
        action = self.token.with_user(self.sheet_manager).action_generate_token()
        new_secret = action["context"]["default_token"]
        self.assertEqual(self.Token._authenticate(new_secret), self.token)

    def test_generate_token_refused_for_forbidden_user(self):
        self.env.cr.execute(
            "UPDATE spreadsheet_api_token SET user_id = %s WHERE id = %s",
            (self.portal_user.id, self.token.id),
        )
        self.token.invalidate_recordset(["user_id"])
        with self.assertRaises(UserError):
            self.token.with_user(self.sheet_manager).action_generate_token()

    def test_authenticate_not_callable_over_rpc(self):
        # /web/dataset/call_kw resolves methods with get_public_method: any
        # logged-in user could otherwise guess tokens or throttle addresses.
        self.assertFalse(hasattr(type(self.Token), "authenticate"))
        with self.assertRaises(AccessError):
            get_public_method(self.Token, "_authenticate")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def test_authenticate_hashed_lookup(self):
        result = self.Token._authenticate(self.secret)
        self.assertEqual(result, self.token)
        # usage counter incremented atomically
        self.assertEqual(self.token.usage_count, 1)
        self.assertTrue(self.token.last_used)

    def test_authenticate_rejects_the_hash_itself(self):
        self.assertFalse(self.Token._authenticate(self.token.token_hash))

    def test_authenticate_empty(self):
        self.assertFalse(self.Token._authenticate(False))
        self.assertFalse(self.Token._authenticate(""))

    def test_authenticate_unknown_token(self):
        self.assertFalse(self.Token._authenticate("does-not-exist"))

    def test_authenticate_inactive(self):
        self.token.active = False
        self.assertFalse(self.Token._authenticate(self.secret))

    def test_authenticate_expired(self):
        self.token.expires_at = fields.Datetime.now() - timedelta(days=1)
        self.assertFalse(self.Token._authenticate(self.secret))

    @mute_logger("odoo.addons.spreadsheet_api_oca.models.api_token")
    def test_authenticate_rejects_superuser_bound_token(self):
        # Simulate a legacy/tampered row that bypassed the constraint.
        self.env.cr.execute(
            "UPDATE spreadsheet_api_token SET user_id = %s WHERE id = %s",
            (SUPERUSER_ID, self.token.id),
        )
        self.token.invalidate_recordset(["user_id"])
        self.assertFalse(self.Token._authenticate(self.secret))

    @mute_logger("odoo.addons.spreadsheet_api_oca.models.api_token")
    def test_authenticate_rejects_archived_user(self):
        self.sheet_user.active = False
        self.assertFalse(self.Token._authenticate(self.secret))

    # ------------------------------------------------------------------
    # Token user restrictions (privilege escalation guard)
    # ------------------------------------------------------------------
    def test_token_targeting_superuser_rejected(self):
        with self.assertRaises(ValidationError):
            self.Token.create({"name": "Root", "user_id": SUPERUSER_ID})
        with self.assertRaises(ValidationError):
            self.token.write({"user_id": SUPERUSER_ID})

    def test_token_targeting_superuser_rejected_for_manager(self):
        with self.assertRaises((ValidationError, AccessError)):
            self.Token.with_user(self.sheet_manager).create(
                {"name": "Root", "user_id": SUPERUSER_ID}
            )

    def test_token_targeting_portal_or_archived_user_rejected(self):
        with self.assertRaises(ValidationError):
            self.Token.create({"name": "Portal", "user_id": self.portal_user.id})
        self.other_sheet_user.active = False
        with self.assertRaises(ValidationError):
            self.Token.create({"name": "Archived", "user_id": self.other_sheet_user.id})

    def test_non_manager_cannot_set_another_user(self):
        Token = self.Token.with_user(self.sheet_user)
        # Through the ORM the record rule may refuse the create first...
        with self.assertRaises((ValidationError, AccessError)):
            Token.create({"name": "Escalate", "user_id": self.other_sheet_user.id})
        # ...so check the constraint itself on such a token, the way the ORM
        # runs constraints: in sudo, with that user as env.uid.
        foreign = self.Token.create(
            {"name": "Foreign", "user_id": self.other_sheet_user.id}
        )
        with self.assertRaises(ValidationError):
            foreign.with_user(self.sheet_user).sudo()._check_user_id()
        own = Token.create({"name": "Own"})
        self.assertEqual(own.user_id, self.sheet_user)
        own.sudo()._check_user_id()  # allowed for the owner: no error
        # write() checks record rules before writing, so the constraint
        # is what refuses this.
        with self.assertRaises(ValidationError):
            own.write({"user_id": self.other_sheet_user.id})

    def test_manager_can_set_another_internal_user(self):
        token = self.Token.with_user(self.sheet_manager).create(
            {"name": "For colleague", "user_id": self.other_sheet_user.id}
        )
        self.assertEqual(token.user_id, self.other_sheet_user)

    def test_non_admin_manager_cannot_target_administrator(self):
        admin = self.env.ref("base.user_admin")
        with self.assertRaises((ValidationError, AccessError)):
            self.Token.with_user(self.sheet_manager).create(
                {"name": "Admin token", "user_id": admin.id}
            )

    def test_user_only_sees_own_tokens(self):
        other = self.Token.create(
            {"name": "Other's token", "user_id": self.other_sheet_user.id}
        )
        visible = self.Token.with_user(self.sheet_user).search([])
        self.assertIn(self.token, visible)
        self.assertNotIn(other, visible)
        with self.assertRaises(AccessError):
            other.with_user(self.sheet_user).read(["name"])

    def test_token_hash_hidden_from_non_admin(self):
        with self.assertRaises(AccessError):
            self.token.with_user(self.sheet_user).read(["token_hash"])

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    def test_rate_limit_blocks_after_limit(self):
        self.token.rate_limit_per_minute = 2
        self.assertEqual(self.Token._authenticate(self.secret), self.token)
        self.assertEqual(self.Token._authenticate(self.secret), self.token)
        self.assertEqual(self.Token._authenticate(self.secret), "RATE_LIMITED")
        self.assertEqual(self.token.rate_limit_exceeded_count, 1)

    def test_rate_limit_zero_is_unlimited(self):
        self.token.rate_limit_per_minute = 0
        for _i in range(5):
            self.assertEqual(self.Token._authenticate(self.secret), self.token)

    def test_failed_auth_limit_parameter(self):
        ICP = self.env["ir.config_parameter"].sudo()
        self.assertEqual(self.Token._get_failed_auth_limit(), 20)
        ICP.set_int("spreadsheet_api_oca.failed_auth_per_minute", 3)
        self.assertEqual(self.Token._get_failed_auth_limit(), 3)
        ICP.set_int("spreadsheet_api_oca.failed_auth_per_minute", -5)
        self.assertEqual(self.Token._get_failed_auth_limit(), 0)

    def test_failed_auth_throttled_per_ip(self):
        self.env["ir.config_parameter"].sudo().set_int(
            "spreadsheet_api_oca.failed_auth_per_minute", 3
        )
        attacker, other_ip = "203.0.113.7", "198.51.100.20"
        for _i in range(3):
            self.assertFalse(self.Token._authenticate("guess", remote_addr=attacker))
        self.assertEqual(
            self.Token._authenticate("guess", remote_addr=attacker), "RATE_LIMITED"
        )
        # Other clients' failed lookups are unaffected.
        self.assertFalse(self.Token._authenticate("guess", remote_addr=other_ip))

    def test_valid_token_not_locked_out_by_throttled_address(self):
        # Integrations sharing an egress IP (NAT, cloud connectors, a proxy)
        # must not be locked out by another client's failures there.
        self.env["ir.config_parameter"].sudo().set_int(
            "spreadsheet_api_oca.failed_auth_per_minute", 2
        )
        shared_ip = "203.0.113.50"
        for _i in range(2):
            self.Token._authenticate("stale-secret", remote_addr=shared_ip)
        self.assertEqual(
            self.Token._authenticate("stale-secret", remote_addr=shared_ip),
            "RATE_LIMITED",
        )
        self.assertEqual(
            self.Token._authenticate(self.secret, remote_addr=shared_ip), self.token
        )

    def test_failed_auth_ipv6_bucketed_per_64(self):
        self.env["ir.config_parameter"].sudo().set_int(
            "spreadsheet_api_oca.failed_auth_per_minute", 2
        )
        self.Token._authenticate("guess", remote_addr="2001:db8:1:2::1")
        self.Token._authenticate("guess", remote_addr="2001:db8:1:2::2")
        # A third address in the same /64 is throttled...
        self.assertEqual(
            self.Token._authenticate("guess", remote_addr="2001:db8:1:2:ffff::3"),
            "RATE_LIMITED",
        )
        # ...another /64 is not.
        self.assertFalse(
            self.Token._authenticate("guess", remote_addr="2001:db8:1:3::1")
        )

    def test_client_ip_bucket(self):
        self.assertEqual(client_ip_bucket("198.51.100.7"), "198.51.100.7")
        self.assertEqual(client_ip_bucket("::ffff:198.51.100.7"), "198.51.100.7")
        self.assertEqual(client_ip_bucket("2001:db8:1:2::99"), "2001:db8:1:2::/64")
        self.assertIsNone(client_ip_bucket(None))

    def test_limiter_prunes_idle_buckets(self):
        limiter = SlidingWindowLimiter(window=60, prune_interval=60)
        self.assertTrue(limiter.allow("a", 1, now=1000.0))
        self.assertFalse(limiter.allow("a", 1, now=1010.0))
        limiter.hit("b", now=1000.0)
        self.assertEqual(len(limiter), 2)
        # One window later the old hits expire and the next call prunes them.
        self.assertTrue(limiter.allow("c", 1, now=1200.0))
        self.assertEqual(len(limiter), 1)
        self.assertTrue(limiter.allow("a", 1, now=1200.0))

    # ------------------------------------------------------------------
    # Webhook URL validation (SSRF guard at save time)
    # ------------------------------------------------------------------
    def test_webhook_url_rejects_loopback(self):
        with self.assertRaises((UserError, ValidationError)):
            self.token.webhook_url = "http://127.0.0.1/hook"

    def test_webhook_url_rejects_link_local_metadata(self):
        with self.assertRaises((UserError, ValidationError)):
            self.token.webhook_url = "http://169.254.169.254/latest/meta-data"

    def test_webhook_url_rejects_ipv4_mapped_ipv6(self):
        with self.assertRaises((UserError, ValidationError)):
            self.token.webhook_url = "http://[::ffff:127.0.0.1]/hook"

    def test_webhook_url_rejects_bad_scheme(self):
        with self.assertRaises((UserError, ValidationError)):
            self.token.webhook_url = "ftp://example.com/hook"

    def test_webhook_url_accepts_public_ip(self):
        # Numeric IP avoids DNS lookups in CI; 8.8.8.8 is a public address.
        self.token.webhook_url = "https://8.8.8.8/hook"
        self.assertEqual(self.token.webhook_url, "https://8.8.8.8/hook")

    def test_response_body_restricted_to_managers(self):
        self.assertEqual(
            self.Event._fields["response_body"].groups,
            "spreadsheet_oca.group_manager",
        )
