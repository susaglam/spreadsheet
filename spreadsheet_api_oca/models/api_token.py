# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import ipaddress
import secrets
import socket
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.exceptions import UserError


class SpreadsheetApiToken(models.Model):
    _name = "spreadsheet.api.token"
    _description = "Spreadsheet API Token"
    _order = "create_date desc"

    name = fields.Char(
        required=True,
        help='A label to identify this token, e.g. "Power BI dashboard".',
    )
    active = fields.Boolean(default=True)
    token = fields.Char(
        required=True,
        readonly=True,
        default=lambda self: secrets.token_urlsafe(32),
        copy=False,
        help="The secret Bearer token. Send it as the HTTP header "
        '"Authorization: Bearer <token>". Treat it like a password.',
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        help="API calls use this user's access rights.",
    )
    spreadsheet_ids = fields.Many2many(
        "spreadsheet.spreadsheet",
        string="Allowed Spreadsheets",
        help="Leave empty to grant access to all spreadsheets the user can read.",
    )
    last_used = fields.Datetime(
        readonly=True,
        help="Timestamp of the most recent successful API call made with this token.",
    )
    usage_count = fields.Integer(
        readonly=True,
        default=0,
        help="Total number of successful API calls made with this token.",
    )
    expires_at = fields.Datetime(help="Optional token expiry date.")

    # Rate limiting
    rate_limit_per_minute = fields.Integer(
        string="Rate Limit (per minute)",
        default=60,
        help="Maximum API calls per minute. 0 = unlimited.",
    )
    rate_limit_exceeded_count = fields.Integer(
        readonly=True,
        default=0,
        help="Number of calls rejected for exceeding the per-minute rate limit.",
    )

    # Webhook
    webhook_url = fields.Char(
        help="If set, this URL is called (POST) when the linked spreadsheet changes.",
    )
    webhook_event_ids = fields.One2many(
        "spreadsheet.api.webhook.event",
        "token_id",
        string="Webhook Delivery Log",
    )

    _token_unique = models.Constraint(
        "unique(token)",
        "Token must be unique.",
    )

    # In-memory rate limiter (per-process) keyed by token ID
    _rate_buckets = defaultdict(list)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        icp = self.env["ir.config_parameter"].sudo()
        if "rate_limit_per_minute" in fields_list:
            # Distinguish "unset" from an explicit 0 (= unlimited). get_int()
            # returns 0 for both, so an admin who sets the default to 0 would
            # otherwise be overridden by the field's own default of 60.
            param = icp.search(
                [("key", "=", "spreadsheet_api.default_rate_limit_per_minute")],
                limit=1,
            )
            if param:
                defaults["rate_limit_per_minute"] = int(param.value or 0)
        if "expires_at" in fields_list and not defaults.get("expires_at"):
            days = icp.get_int("spreadsheet_api.default_expiry_days")
            if days > 0:
                defaults["expires_at"] = fields.Datetime.now() + timedelta(days=days)
        return defaults

    @api.constrains("webhook_url")
    def _check_webhook_url(self):
        for rec in self:
            if rec.webhook_url:
                self._validate_webhook_url(rec.webhook_url)

    @api.model
    def _validate_webhook_url(self, url):
        """Reject webhook URLs that could enable SSRF against internal hosts.

        Only public http(s) endpoints are allowed; hosts that resolve to
        loopback / private / link-local / reserved ranges are refused so a
        low-privilege user cannot make the delivery cron probe internal
        services or leak the bearer token to them.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise UserError(
                self.env._(
                    "The webhook URL must start with http:// or https:// "
                    "(got %(url)s). Point it at a public HTTPS endpoint your "
                    "integration controls.",
                    url=url,
                )
            )
        host = parsed.hostname
        if not host:
            raise UserError(
                self.env._(
                    "The webhook URL %(url)s has no host. Use a full URL such "
                    "as https://example.com/hook.",
                    url=url,
                )
            )
        try:
            addr_info = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise UserError(
                self.env._(
                    "The webhook host %(host)s could not be resolved. Check the "
                    "URL and that the host is reachable from this server.",
                    host=host,
                )
            ) from exc
        for info in addr_info:
            ip = ipaddress.ip_address(info[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                raise UserError(
                    self.env._(
                        "The webhook URL resolves to an internal/private "
                        "address (%(ip)s), which is not allowed for security "
                        "reasons. Use a public endpoint instead.",
                        ip=str(ip),
                    )
                )

    def action_regenerate_token(self):
        self.ensure_one()
        self.token = secrets.token_urlsafe(32)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Token Regenerated"),
                "message": self.env._(
                    "A new token has been generated. Update your integrations."
                ),
                "type": "success",
            },
        }

    @api.model
    def authenticate(self, token):
        if not token:
            return False
        rec = self.sudo().search(
            [
                ("token", "=", token),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not rec:
            return False
        if rec.expires_at and rec.expires_at < fields.Datetime.now():
            return False
        if not rec._check_rate_limit():
            # Atomic increment avoids read-modify-write lost updates and
            # row-lock contention under concurrent API traffic.
            self.env.cr.execute(
                "UPDATE spreadsheet_api_token "
                "SET rate_limit_exceeded_count = rate_limit_exceeded_count + 1 "
                "WHERE id = %s",
                (rec.id,),
            )
            rec.invalidate_recordset(["rate_limit_exceeded_count"])
            return "RATE_LIMITED"
        self.env.cr.execute(
            "UPDATE spreadsheet_api_token "
            "SET usage_count = usage_count + 1, last_used = %s "
            "WHERE id = %s",
            (fields.Datetime.now(), rec.id),
        )
        rec.invalidate_recordset(["usage_count", "last_used"])
        return rec

    def _check_rate_limit(self):
        """Sliding-window rate limiter. Returns True if request is allowed."""
        self.ensure_one()
        if not self.rate_limit_per_minute:
            return True
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=1)
        bucket = self._rate_buckets[self.id]
        # Purge old entries
        self._rate_buckets[self.id] = [t for t in bucket if t > window_start]
        if len(self._rate_buckets[self.id]) >= self.rate_limit_per_minute:
            return False
        self._rate_buckets[self.id].append(now)
        return True


class SpreadsheetApiWebhookEvent(models.Model):
    _name = "spreadsheet.api.webhook.event"
    _description = "API Webhook Delivery Event"
    _order = "create_date desc"

    token_id = fields.Many2one(
        "spreadsheet.api.token",
        required=True,
        ondelete="cascade",
    )
    spreadsheet_id = fields.Many2one("spreadsheet.spreadsheet")
    event_type = fields.Selection(
        [
            ("update", "Updated"),
            ("create", "Created"),
            ("delete", "Deleted"),
        ],
        required=True,
    )
    payload = fields.Text()
    response_status = fields.Integer()
    response_body = fields.Text()
    delivered = fields.Boolean(default=False)
    retry_count = fields.Integer(default=0)
