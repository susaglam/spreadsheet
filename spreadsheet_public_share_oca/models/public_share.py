# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import hmac as hmac_tool

# _col_letter / _parse_ref / _resolve_display are re-exported for callers that
# imported them from this module before the preview helpers moved out.
from .sheet_preview import (  # noqa: F401
    _col_letter,
    _parse_ref,
    _resolve_display,
    render_sheets,
)

_logger = logging.getLogger(__name__)

# Scope of the HMAC that proves, in a visitor's session, that the password of a
# share was already entered (see _get_access_grant).
ACCESS_GRANT_SCOPE = "spreadsheet_public_share.access_grant"
# passlib refuses secrets above 4096 bytes; a share password never needs this
# much, and a bounded size keeps the key-derivation cost predictable.
MAX_PASSWORD_LENGTH = 1024


class SpreadsheetPublicShare(models.Model):
    _name = "spreadsheet.public.share"
    _description = "Public Spreadsheet Share Link"

    name = fields.Char(
        required=True,
        help="Internal label for this link, e.g. 'Q3 board deck - external'.",
    )
    active = fields.Boolean(
        default=True,
        help="Untick to instantly revoke the link; the public URL then "
        "shows 'Invalid or Expired Link'.",
    )
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        required=True,
        ondelete="cascade",
        help="Spreadsheet whose read-only preview is exposed at the public URL. "
        "You can only share a spreadsheet you are allowed to edit (its owner, a "
        "contributor or a Spreadsheet manager), because the link publishes it "
        "to anyone who has the URL.",
    )
    token = fields.Char(
        required=True,
        readonly=True,
        default=lambda self: secrets.token_urlsafe(32),
        copy=False,
        help="Random secret embedded in the share URL; regenerate it to "
        "invalidate every previously distributed link.",
    )
    expires_at = fields.Datetime(
        default=lambda self: self._default_expires_at(),
        help="Optional expiry date for the share link. Defaults come from "
        "Settings > Spreadsheet > Default Share Link Expiry.",
    )
    view_count = fields.Integer(
        readonly=True,
        default=0,
        copy=False,
        help="How many times the public link has been opened so far.",
    )
    last_viewed = fields.Datetime(
        readonly=True,
        copy=False,
        help="Timestamp of the most recent time the public link was opened.",
    )
    password = fields.Char(
        compute="_compute_password",
        inverse="_inverse_password",
        copy=False,
        help="Type a password to protect the link: visitors must enter it before "
        "they see the spreadsheet. The password is stored hashed, so it can never "
        "be displayed again; leave this empty to keep the current password, or "
        "use 'Remove Password' to make the link open without one.",
    )
    password_hash = fields.Char(
        readonly=True,
        copy=False,
        groups=fields.NO_ACCESS,
        help="Salted PBKDF2 hash of the link password (never the password "
        "itself). Only readable by the server.",
    )
    has_password = fields.Boolean(
        string="Password Protected",
        compute="_compute_has_password",
        compute_sudo=True,
        help="Ticked when visitors must enter a password before the spreadsheet "
        "is shown.",
    )
    allow_download = fields.Boolean(
        default=lambda self: (
            self.env["ir.config_parameter"]
            .sudo()
            .get_bool("spreadsheet_public_share.allow_download_default")
        ),
        help="Allow downloading the spreadsheet data as a JSON file from the "
        "public page. The file is the complete workbook so it re-imports without "
        "losing anything: it also contains what the preview does not show (hidden "
        "sheets, hidden rows and columns, and helper sheets such as 'Data'), "
        "because formulas on the visible cells read from them. Only enable it "
        "when the whole workbook may be published. The default comes from "
        "Settings > Spreadsheet.",
    )
    created_by_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
        copy=False,
        help="User who created this share link. The link only opens while this user "
        "is still allowed to edit the spreadsheet. Spreadsheet users only see and "
        "manage their own links; Spreadsheet managers see every link and can hand "
        "a link over to another user.",
    )
    share_url = fields.Char(
        compute="_compute_share_url",
        string="Share URL",
        help="Public address of the read-only preview. Anyone with this URL (and "
        "the password, if one is set) can open it without logging in.",
    )

    _token_unique = models.Constraint(
        "unique(token)",
        "Token must be unique.",
    )

    @api.model
    def _default_expires_at(self):
        days = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_int("spreadsheet_public_share.default_expiry_days")
        )
        if days and days > 0:
            return fields.Datetime.now() + timedelta(days=days)
        return False

    @api.depends("token")
    def _compute_share_url(self):
        # get_param removed; use get_str
        base_url = self.env["ir.config_parameter"].sudo().get_str("web.base.url")
        for rec in self:
            rec.share_url = (
                f"{base_url}/spreadsheet/public/{rec.token}" if rec.token else ""
            )

    def _compute_password(self):
        # Write-only field: the stored value is a hash and is never shown.
        for share in self:
            share.password = ""

    def _inverse_password(self):
        crypt = self.env["res.users"]._crypt_context()
        for share in self:
            if not share.password:
                # The web client sends False for untouched fields: keep the
                # current password instead of silently removing it.
                continue
            if len(share.password) > MAX_PASSWORD_LENGTH:
                raise ValidationError(
                    self.env._(
                        "The password of the share link '%(name)s' is too long "
                        "(%(length)s characters). Very long passwords make every "
                        "access check slow for the server. Choose a password of "
                        "at most %(max)s characters.",
                        name=share.name,
                        length=len(share.password),
                        max=MAX_PASSWORD_LENGTH,
                    )
                )
            share.sudo().password_hash = crypt.hash(share.password)

    @api.depends("password_hash")
    def _compute_has_password(self):
        for share in self:
            share.has_password = bool(share.password_hash)

    # ------------------------------------------------------------------
    # CRUD guards
    # ------------------------------------------------------------------
    # These checks cannot be @api.constrains: in saas-19.4 _validate_fields()
    # runs every constraint on self.sudo(), where has_access() is always True.

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_share_manager():
            for vals in vals_list:
                if vals.get("token"):
                    raise AccessError(self._token_change_error())
        shares = super().create(vals_list)
        # After super(): spreadsheet_id may come from a default_* context key.
        shares._check_spreadsheet_write_access()
        return shares

    def write(self, vals):
        if not self._is_share_manager():
            if "token" in vals and any(
                share.sudo().token != vals["token"] for share in self
            ):
                raise AccessError(self._token_change_error())
            if "created_by_id" in vals:
                creator = vals["created_by_id"]
                creator_id = (
                    creator.id if isinstance(creator, models.BaseModel) else creator
                ) or False
                if any(share.sudo().created_by_id.id != creator_id for share in self):
                    raise AccessError(
                        self.env._(
                            "Only a Spreadsheet manager can change who created a "
                            "public share link. Besides the managers, the creator is "
                            "the only user who can see and manage the link, and the "
                            "link only opens while the creator may edit the "
                            "spreadsheet. Ask a Spreadsheet manager to hand the link "
                            "over to another user."
                        )
                    )
        result = super().write(vals)
        if "spreadsheet_id" in vals:
            self._check_spreadsheet_write_access()
        return result

    def copy(self, default=None):
        new_shares = super().copy(default=default)
        if default and ("password" in default or "password_hash" in default):
            return new_shares
        # password_hash is copy=False (users cannot write it): carry it over as
        # superuser so a duplicate of a protected link stays protected.
        for share, new_share in zip(self, new_shares, strict=True):
            password_hash = share.sudo().password_hash
            if password_hash:
                new_share.sudo().password_hash = password_hash
        return new_shares

    def _is_share_manager(self):
        return self.env.su or self.env.user.has_group("spreadsheet_oca.group_manager")

    def _token_change_error(self):
        return self.env._(
            "Only a Spreadsheet manager can set the secret token of a public share "
            "link by hand. A token that is typed in instead of generated can be "
            "guessed, which would publish the spreadsheet to strangers. Use "
            "'Regenerate Link' to get a new random token."
        )

    def _check_spreadsheet_write_access(self):
        """Only people allowed to edit a spreadsheet may publish it.

        The public controller serves the spreadsheet with sudo, so without this
        check a user could share (and download) a spreadsheet they cannot even
        read. Evaluated in the caller's environment; superuser code is trusted.
        """
        if self.env.su:
            return
        Spreadsheet = self.env["spreadsheet.spreadsheet"]
        for spreadsheet_id in self.sudo().spreadsheet_id.ids:
            spreadsheet = Spreadsheet.browse(spreadsheet_id)
            if spreadsheet.has_access("write"):
                continue
            label = (
                spreadsheet.display_name
                if spreadsheet.has_access("read")
                else f"#{spreadsheet.id}"
            )
            raise ValidationError(
                self.env._(
                    "You cannot publish the spreadsheet '%(spreadsheet)s' through a "
                    "public share link because you are not allowed to edit it. A "
                    "public link shows the spreadsheet to anyone who has the URL, "
                    "so only its owner, its contributors or a Spreadsheet manager "
                    "may create a link for it or move a link to it. Ask the owner "
                    "to share it, or to add you as a contributor.",
                    spreadsheet=label,
                )
            )

    def action_regenerate_token(self):
        self.ensure_one()
        # Users may not write the token themselves (see write()): check the
        # access on the record, then store a fresh random token as superuser.
        self.check_access("write")
        self.sudo().token = secrets.token_urlsafe(32)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Token Regenerated"),
                "message": self.env._(
                    "The share link has been updated. Old links no longer work."
                ),
                "type": "warning",
            },
        }

    def action_remove_password(self):
        self.ensure_one()
        # password_hash is not readable/writable by users: check the access on
        # the record itself, then clear the hash as superuser.
        self.check_access("write")
        self.sudo().password_hash = False
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Password Removed"),
                "message": self.env._(
                    "Anyone with the link can now open the spreadsheet without a "
                    "password."
                ),
                "type": "warning",
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_copy_link(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Share Link"),
                "message": self.share_url,
                "type": "info",
                "sticky": True,
            },
        }

    # ------------------------------------------------------------------
    # Public access helpers (used by the controller, never RPC-callable)
    # ------------------------------------------------------------------

    @api.model
    def _get_live_share(self, token):
        """Return the active, non-expired share for ``token`` (sudo) or empty."""
        Share = self.sudo()
        if not token or not isinstance(token, str):
            return Share.browse()
        share = Share.search([("token", "=", token), ("active", "=", True)], limit=1)
        if share.expires_at and share.expires_at < fields.Datetime.now():
            return Share.browse()
        if share and not share._creator_can_publish():
            _logger.warning(
                "Public share %s refused: its creator (user %s) is no longer allowed "
                "to edit spreadsheet %s.",
                share.id,
                share.created_by_id.id,
                share.spreadsheet_id.id,
            )
            return Share.browse()
        return share

    def _creator_can_publish(self):
        """Whether the creator of this link may still edit its spreadsheet.

        Links created before the write-access check existed, or whose creator
        lost access since (removed contributor, ownership transferred...), stop
        opening instead of publishing the spreadsheet on the creator's behalf.
        """
        self.ensure_one()
        share = self.sudo()
        creator = share.created_by_id
        if not creator:
            # Users cannot create a link without a creator (see ir.access):
            # only managers or server code can, so such a link is trusted.
            return True
        # A clean context: the public website request carries its own
        # allowed_company_ids, which must not decide the creator's access.
        creator_env = self.env(user=creator.id, su=False, context={})
        return share.spreadsheet_id.with_env(creator_env).has_access("write")

    def _check_share_password(self, password):
        """Return whether ``password`` opens this share.

        The comparison is delegated to the same passlib context that protects
        user passwords (``res.users._crypt_context``), whose verification is
        constant-time. A value stored before hashing was introduced still
        verifies and is transparently upgraded to a hash.
        """
        self.ensure_one()
        share = self.sudo()
        stored = share.password_hash
        if not stored:
            return True
        if not isinstance(password, str) or not password:
            return False
        if len(password) > MAX_PASSWORD_LENGTH:
            return False
        crypt = self.env["res.users"]._crypt_context()
        try:
            valid, replacement = crypt.verify_and_update(password, stored)
            # A value that is not a hash yet is rehashed whatever the
            # deprecation policy of the active context says (tests patch
            # _crypt_context without deprecated=['auto']).
            if valid and not replacement and crypt.identify(stored) == "plaintext":
                replacement = crypt.hash(password)
        except (TypeError, ValueError):
            _logger.warning(
                "Public share %s has an unreadable password hash; access is "
                "refused until its owner sets a new password.",
                share.id,
            )
            return False
        if valid and replacement:
            share.password_hash = replacement
        return valid

    def _get_access_grant(self):
        """Opaque proof, stored in a visitor's session, that the password of
        this share was entered. It changes when the token or the password
        changes, so regenerating either revokes every existing grant."""
        self.ensure_one()
        share = self.sudo()
        message = f"{share.id}:{share.token}:{share.password_hash or ''}"
        return hmac_tool(self.env(su=True), ACCESS_GRANT_SCOPE, message)

    def _register_view(self):
        for share in self.sudo():
            share.write(
                {
                    "view_count": share.view_count + 1,
                    "last_viewed": fields.Datetime.now(),
                }
            )

    @api.model
    def _verify_token(self, token, password=None, count=True):
        """Return the share opened by ``token`` + ``password``, or empty.

        Private on purpose: a public ``verify_token`` was callable over RPC by
        any internal user, which bypassed the brute-force throttle of the
        public controller.
        """
        share = self._get_live_share(token)
        if not share or not share._check_share_password(password):
            return self.sudo().browse()
        if count:
            share._register_view()
        return share

    def _get_spreadsheet_data(self):
        """Return the decoded workbook of the shared spreadsheet.

        Returns None (and logs a warning) when the stored data cannot be
        decoded, so the public page and the download degrade instead of
        answering with a server error.
        """
        self.ensure_one()
        try:
            raw = self.spreadsheet_id.sudo().spreadsheet_raw or {}
        except (TypeError, ValueError):
            # ValueError covers UnicodeDecodeError, binascii.Error and
            # json.JSONDecodeError.
            _logger.warning(
                "Public share %s: the data of spreadsheet %s cannot be decoded.",
                self.id,
                self.spreadsheet_id.id,
                exc_info=True,
            )
            return None
        return raw

    def _get_rendered_sheets(self):
        """Return pre-processed sheet data suitable for HTML rendering.

        Each sheet gets: name, rows (list of dicts with height and cells),
        col_widths, truncated and, when the sheet could not be parsed, error.
        Cells contain: content, display, computed, style_css, colspan, rowspan.
        """
        self.ensure_one()
        raw = self._get_spreadsheet_data()
        if raw is None:
            return []

        def log_error(sheet_name, exc):
            _logger.warning(
                "Public share %s: sheet %r of spreadsheet %s cannot be previewed (%s).",
                self.id,
                sheet_name,
                self.spreadsheet_id.id,
                exc,
            )

        return render_sheets(raw, on_error=log_error)
