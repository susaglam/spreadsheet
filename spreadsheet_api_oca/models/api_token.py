# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import hashlib
import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.api import SUPERUSER_ID
from odoo.exceptions import AccessError, UserError, ValidationError

from ..tools.rate_limit import FAILED_AUTH_LIMITER, TOKEN_LIMITER, client_ip_bucket
from ..tools.webhook import WebhookTargetError, validate_webhook_url

_logger = logging.getLogger(__name__)

TOKEN_HINT_LENGTH = 6
DEFAULT_FAILED_AUTH_PER_MINUTE = 20
FAILED_AUTH_PARAM = "spreadsheet_api_oca.failed_auth_per_minute"
RATE_LIMITED = "RATE_LIMITED"


def hash_token(token):
    """Return the SHA-256 hex digest stored instead of the plaintext token.

    Tokens are 256-bit random strings, so a fast unsalted hash is enough:
    there is nothing to brute-force, and it allows an indexed lookup.
    """
    return hashlib.sha256((token or "").encode()).hexdigest()


class SpreadsheetApiToken(models.Model):
    _name = "spreadsheet.api.token"
    _description = "Spreadsheet API Token"
    _order = "create_date desc"

    name = fields.Char(
        required=True,
        help='A label to identify this token, e.g. "Power BI dashboard".',
    )
    active = fields.Boolean(
        default=True,
        help="Archived tokens are rejected by the API. Archive a token to "
        "suspend an integration without losing its configuration and log.",
    )
    token_hash = fields.Char(
        readonly=True,
        copy=False,
        groups="base.group_system",
        help="SHA-256 fingerprint of the secret token. Only this fingerprint "
        "is stored, so the secret itself cannot be read back from the "
        "database; incoming API calls are matched against it.",
    )
    token_hint = fields.Char(
        string="Token",
        readonly=True,
        copy=False,
        help="The first characters of the secret token, so you can recognise "
        "which secret an integration uses. The full token is shown only once, "
        "right after you click Generate Token. Lost it? Generate a new one "
        "and update the integration.",
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        domain=[("share", "=", False)],
        help="API calls run with this user's access rights, so the integration "
        "sees exactly the spreadsheets this user can read. Spreadsheet users "
        "can only create tokens for themselves; managers can pick another "
        "active internal user, and only administrators can pick an "
        "administrator. The superuser, portal/public users and archived users "
        "are not allowed.",
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
    expires_at = fields.Datetime(
        help="Optional token expiry date. After this moment the API rejects the "
        "token. Leave empty for a token that never expires.",
    )

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
        help="If set, this URL is called (POST) when a spreadsheet this token "
        "can read is created, changed or deleted. Only public http(s) "
        "endpoints are accepted; redirects are not followed. Each call carries "
        "an X-Spreadsheet-Signature header (HMAC-SHA256 of the body) so the "
        "receiver can check it really comes from this server.",
    )
    webhook_event_ids = fields.One2many(
        "spreadsheet.api.webhook.event",
        "token_id",
        string="Webhook Delivery Log",
        help="Every webhook call queued for this token, with its delivery "
        "status. Failed calls are retried by a scheduled action.",
    )

    _token_hash_unique = models.Constraint(
        "unique(token_hash)",
        "Two API tokens cannot share the same secret. Generate a new token for "
        "one of them.",
    )

    # ------------------------------------------------------------------
    # Defaults & constraints
    # ------------------------------------------------------------------
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

    @api.model
    def _is_allowed_api_user(self, user):
        """Whether API calls may run as ``user``.

        The superuser is refused because ``env(user=1)`` silently becomes a
        sudo environment (no access rules, every company). Portal/public
        (share) users and archived users are refused as well.
        """
        user = user.sudo()
        return bool(
            len(user) == 1
            and user.id != SUPERUSER_ID
            and user.active
            and not user.share
        )

    @api.model
    def _get_acting_user_rights(self):
        """Return ``(acting_user, is_manager, is_system)`` for ``env.uid``.

        ``env.uid`` is used, not ``env.su``: constraints always run in sudo,
        but the uid is still the user who triggered the change.
        """
        acting_user = self.env.user
        is_system = self.env.uid == SUPERUSER_ID or acting_user._is_system()
        is_manager = is_system or acting_user.has_group("spreadsheet_oca.group_manager")
        return acting_user, is_manager, is_system

    def _get_user_violation(self):
        """Why the acting user may not bind this token to its user.

        Returns ``None`` when allowed, otherwise ``"forbidden_user"`` (the
        superuser, a portal/public user or an archived user), ``"not_self"``
        (a non-manager choosing another user) or ``"administrator"`` (a
        non-administrator choosing an administrator).
        """
        self.ensure_one()
        acting_user, is_manager, is_system = self._get_acting_user_rights()
        user = self.user_id
        if not self._is_allowed_api_user(user):
            return "forbidden_user"
        if user == acting_user:
            return None
        if not is_manager:
            return "not_self"
        if not is_system and user._is_system():
            return "administrator"
        return None

    def _forbidden_user_message(self):
        self.ensure_one()
        return self.env._(
            'The API token "%(token)s" cannot run as %(user)s. API '
            "calls use this user's access rights, and the superuser, "
            "portal/public users and archived users would bypass or "
            "break those rights. Pick an active internal user instead.",
            token=self.name,
            user=self.user_id.display_name,
        )

    @api.constrains("user_id")
    def _check_user_id(self):
        for token in self:
            violation = token._get_user_violation()
            if violation == "forbidden_user":
                raise ValidationError(token._forbidden_user_message())
            if violation == "not_self":
                raise ValidationError(
                    self.env._(
                        "You can only create or edit API tokens that run as "
                        'yourself, but "%(token)s" is set to %(user)s. A token '
                        "grants that user's access rights, so choosing another "
                        "user requires the Spreadsheet Manager role. Set the user "
                        "back to yourself or ask a manager.",
                        token=token.name,
                        user=token.user_id.display_name,
                    )
                )
            if violation == "administrator":
                raise ValidationError(
                    self.env._(
                        'The API token "%(token)s" would run as the administrator '
                        "%(user)s, which gives the integration more rights than "
                        "you have. Only an administrator can create such a token; "
                        "otherwise pick a user without administration rights.",
                        token=token.name,
                        user=token.user_id.display_name,
                    )
                )

    def _check_administrator_token_access(self):
        """Refuse non-administrators any change to administrator tokens.

        The ``user_id`` constraint alone is not enough: a Spreadsheet manager
        could otherwise regenerate the secret of a token an administrator
        made for himself, or point its webhook at his own endpoint, and so
        act with administrator rights.
        """
        acting_user, _is_manager, is_system = self._get_acting_user_rights()
        if is_system:
            return
        for token in self.sudo():
            if token.user_id != acting_user and token.user_id._is_system():
                raise AccessError(
                    self.env._(
                        'The API token "%(token)s" runs as the administrator '
                        "%(user)s. Only an administrator can change it or "
                        "generate its secret, because whoever holds that secret "
                        "gets administrator access to the spreadsheets. Ask an "
                        "administrator, or use a token that runs as a user "
                        "without administration rights.",
                        token=token.name,
                        user=token.user_id.display_name,
                    )
                )

    def write(self, vals):
        if not self.env.su:
            self._check_administrator_token_access()
        return super().write(vals)

    @api.constrains("webhook_url")
    def _check_webhook_url(self):
        for rec in self:
            if rec.webhook_url:
                self._validate_webhook_url(rec.webhook_url)

    @api.model
    def _webhook_target_error_message(self, error, url):
        if error.reason == "scheme":
            return self.env._(
                "The webhook URL must start with http:// or https:// "
                "(got %(url)s). Point it at a public HTTPS endpoint your "
                "integration controls.",
                url=url,
            )
        if error.reason == "host":
            return self.env._(
                "The webhook URL %(url)s has no valid host or port. Use a full "
                "URL such as https://example.com/hook.",
                url=url,
            )
        if error.reason == "resolve":
            return self.env._(
                "The webhook host %(host)s could not be resolved. Check the "
                "URL and that the host is reachable from this server.",
                host=error.host,
            )
        return self.env._(
            "The webhook URL resolves to an internal/private "
            "address (%(ip)s), which is not allowed for security "
            "reasons. Use a public endpoint instead.",
            ip=error.ip,
        )

    @api.model
    def _validate_webhook_url(self, url):
        """Reject webhook URLs that could enable SSRF against internal hosts.

        Only public http(s) endpoints are allowed; hosts that resolve to
        loopback / private / link-local / reserved ranges are refused. The
        same check runs again at delivery time (DNS can change).
        """
        try:
            validate_webhook_url(url)
        except WebhookTargetError as error:
            raise UserError(self._webhook_target_error_message(error, url)) from error

    # ------------------------------------------------------------------
    # Token generation
    # ------------------------------------------------------------------
    def _generate_token(self):
        """Create a new secret, store only its hash and return the plaintext.

        The previous secret (if any) stops working immediately.
        """
        self.ensure_one()
        plaintext = secrets.token_urlsafe(32)
        self.sudo().write(
            {
                "token_hash": hash_token(plaintext),
                "token_hint": plaintext[:TOKEN_HINT_LENGTH] + "…",
            }
        )
        return plaintext

    def action_generate_token(self):
        """Generate (or regenerate) the secret and show it exactly once."""
        self.ensure_one()
        # Same rights as editing the token: raises for a user who may only
        # read it (and never leaks the new secret to them).
        self.check_access("write")
        if not self.env.su:
            self._check_administrator_token_access()
            violation = self._get_user_violation()
            if violation == "forbidden_user":
                raise UserError(self._forbidden_user_message())
            if violation == "not_self":
                raise AccessError(
                    self.env._(
                        "You can only generate secrets for API tokens that run "
                        'as yourself, but "%(token)s" runs as %(user)s. The '
                        "secret grants that user's access rights, so this "
                        "requires the Spreadsheet Manager role. Ask a manager "
                        "to generate it.",
                        token=self.name,
                        user=self.user_id.display_name,
                    )
                )
        plaintext = self._generate_token()
        return {
            "type": "ir.actions.act_window",
            "res_model": "spreadsheet.api.token.show",
            "name": self.env._("API Token Ready"),
            "views": [(False, "form")],
            "target": "new",
            "context": {
                "default_token": plaintext,
                "default_token_name": self.name,
            },
        }

    # ------------------------------------------------------------------
    # Authentication & rate limiting
    # ------------------------------------------------------------------
    @api.model
    def _get_failed_auth_limit(self):
        limit = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_int(FAILED_AUTH_PARAM, DEFAULT_FAILED_AUTH_PER_MINUTE)
        )
        return max(limit, 0)

    @api.model
    def _failed_auth_key(self, remote_addr):
        bucket = client_ip_bucket(remote_addr)
        if not bucket:
            return None
        return ("failed-auth", self.env.cr.dbname, bucket)

    @api.model
    def _register_failed_auth(self, remote_addr):
        """Count one failed authentication of the client ``remote_addr``.

        Returns ``True`` when that client already reached the per-minute
        limit; the attempt is then refused without being counted, so the
        client gets its attempts back one minute after its first failures.
        """
        key = self._failed_auth_key(remote_addr)
        limit = self._get_failed_auth_limit() if key else 0
        if not limit:
            return False
        if FAILED_AUTH_LIMITER.is_limited(key, limit):
            return True
        FAILED_AUTH_LIMITER.hit(key)
        return False

    @api.model
    def _authenticate(self, token, remote_addr=None):
        """Return the token record, ``False`` or ``"RATE_LIMITED"``.

        Private on purpose: a public method could be called over RPC by any
        logged-in user to guess tokens or to throttle someone else's address.

        The token is always evaluated first, and a valid token is only
        subject to its own rate limit, so clients sharing an address (NAT,
        cloud connectors, a reverse proxy) are not locked out by another
        client's failures. Failed lookups are throttled per client address
        (``remote_addr``, IPv6 per /64), which slows down token guessing.
        """
        rec = self._find_valid_token(token)
        if not rec:
            if self._register_failed_auth(remote_addr):
                return RATE_LIMITED
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
            return RATE_LIMITED
        self.env.cr.execute(
            "UPDATE spreadsheet_api_token "
            "SET usage_count = usage_count + 1, last_used = %s "
            "WHERE id = %s",
            (fields.Datetime.now(), rec.id),
        )
        rec.invalidate_recordset(["usage_count", "last_used"])
        return rec

    @api.model
    def _find_valid_token(self, token):
        """Look the plaintext ``token`` up by hash; return a sudo record."""
        if not token or not isinstance(token, str):
            return self.sudo().browse()
        rec = self.sudo().search(
            [("token_hash", "=", hash_token(token)), ("active", "=", True)],
            limit=1,
        )
        if not rec:
            return rec
        if rec.expires_at and rec.expires_at < fields.Datetime.now():
            return self.sudo().browse()
        if not self._is_allowed_api_user(rec.user_id):
            _logger.warning(
                "Spreadsheet API token %s rejected: its user (id %s) is the "
                "superuser, a portal/public user or archived.",
                rec.id,
                rec.user_id.id,
            )
            return self.sudo().browse()
        return rec

    def _check_rate_limit(self):
        """Sliding-window rate limiter. Returns True if request is allowed."""
        self.ensure_one()
        return TOKEN_LIMITER.allow(
            ("token", self.env.cr.dbname, self.id), self.rate_limit_per_minute
        )


class SpreadsheetApiTokenShow(models.AbstractModel):
    """Dialog showing a freshly generated secret. Nothing is stored."""

    _name = "spreadsheet.api.token.show"
    _description = "Show Spreadsheet API Token"

    # the field 'id' is necessary for the onchange that returns the defaults
    id = fields.Id()
    token = fields.Char(
        readonly=True,
        help="The secret Bearer token. Send it as the HTTP header "
        '"Authorization: Bearer <token>". Treat it like a password: it is '
        "shown only this once.",
    )
    token_name = fields.Char(
        readonly=True,
        help="The label of the API token this secret belongs to.",
    )


class SpreadsheetApiWebhookEvent(models.Model):
    _name = "spreadsheet.api.webhook.event"
    _description = "API Webhook Delivery Event"
    _order = "create_date desc"

    token_id = fields.Many2one(
        "spreadsheet.api.token",
        required=True,
        ondelete="cascade",
        help="The API token whose webhook URL receives this event.",
    )
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        help="The spreadsheet the event is about. Empty once the spreadsheet "
        "has been deleted.",
    )
    event_type = fields.Selection(
        [
            ("update", "Updated"),
            ("create", "Created"),
            ("delete", "Deleted"),
        ],
        required=True,
        help="What happened to the spreadsheet: created, updated (content "
        "changed) or deleted.",
    )
    payload = fields.Text(
        help="The JSON body sent to the webhook URL.",
    )
    response_status = fields.Integer(
        help="HTTP status code returned by the webhook endpoint on the last "
        "attempt. 0 means no answer (network error, timeout or blocked "
        "address).",
    )
    response_body = fields.Text(
        groups="spreadsheet_oca.group_manager",
        help="The first 500 characters returned by the endpoint, or the error "
        "message of the last attempt. Visible to Spreadsheet managers only.",
    )
    delivered = fields.Boolean(
        default=False,
        help="Set once the endpoint answered with a 2xx status code.",
    )
    retry_count = fields.Integer(
        default=0,
        help="Number of delivery attempts so far. Delivery stops after the "
        "maximum number of webhook retries configured in the settings.",
    )
