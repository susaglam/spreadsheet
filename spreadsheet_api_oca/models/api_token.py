# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import secrets
from collections import defaultdict
from datetime import datetime, timedelta

from odoo import api, fields, models


class SpreadsheetApiToken(models.Model):
    _name = "spreadsheet.api.token"
    _description = "Spreadsheet API Token"
    _order = "create_date desc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    token = fields.Char(
        required=True,
        readonly=True,
        default=lambda self: secrets.token_urlsafe(32),
        copy=False,
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
    last_used = fields.Datetime(readonly=True)
    usage_count = fields.Integer(readonly=True, default=0)
    expires_at = fields.Datetime(help="Optional token expiry date.")

    # Rate limiting
    rate_limit_per_minute = fields.Integer(
        string="Rate Limit (per minute)",
        default=60,
        help="Maximum API calls per minute. 0 = unlimited.",
    )
    rate_limit_exceeded_count = fields.Integer(readonly=True, default=0)

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

    def action_regenerate_token(self):
        self.ensure_one()
        self.token = secrets.token_urlsafe(32)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Token Regenerated",
                "message": "A new token has been generated. Update your integrations.",
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
            rec.sudo().write(
                {
                    "rate_limit_exceeded_count": rec.rate_limit_exceeded_count + 1,
                }
            )
            return "RATE_LIMITED"
        rec.sudo().write(
            {
                "last_used": fields.Datetime.now(),
                "usage_count": rec.usage_count + 1,
            }
        )
        return rec

    def _check_rate_limit(self):
        """Sliding-window rate limiter. Returns True if request is allowed."""
        self.ensure_one()
        if not self.rate_limit_per_minute:
            return True
        now = datetime.utcnow()
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
