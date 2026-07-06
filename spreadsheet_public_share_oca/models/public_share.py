# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import hmac
import re
import secrets
from datetime import timedelta

from odoo import api, fields, models


def _parse_ref(ref):
    m = re.match(r"^([A-Z]+)(\d+)$", ref, re.IGNORECASE)
    if not m:
        return 0, 0
    letters = m.group(1).upper()
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - 64)
    return col - 1, int(m.group(2)) - 1


def _col_letter(col):
    result = ""
    col += 1
    while col > 0:
        col -= 1
        result = chr(65 + (col % 26)) + result
        col //= 26
    return result


_T_LITERAL_RE = re.compile(r'^=_t\(\s*(["\'])(.*?)\1\s*\)$', re.DOTALL)


def _resolve_display(content):
    """Return (display_text, is_computed) for the engine-less HTML preview.

    Plain content shows verbatim; a pure translation label =_t("...") shows its
    literal text so header rows stay meaningful; any other formula is a value we
    cannot evaluate server-side (no o-spreadsheet engine), flagged so the
    template shows an honest em dash instead of a fake "f(x)".
    """
    if not content or not content.startswith("="):
        return content or "", False
    match = _T_LITERAL_RE.match(content)
    if match:
        return match.group(2), False
    return "", True


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
        help="Spreadsheet whose read-only preview is exposed at the public URL.",
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
        help="How many times the public link has been opened so far.",
    )
    last_viewed = fields.Datetime(
        readonly=True,
        help="Timestamp of the most recent time the public link was opened.",
    )
    password = fields.Char(
        help="Optional password to access the shared spreadsheet.",
    )
    allow_download = fields.Boolean(
        default=lambda self: (
            self.env["ir.config_parameter"]
            .sudo()
            .get_bool("spreadsheet_public_share.allow_download_default")
        ),
        help="Allow downloading the spreadsheet data as a JSON file from the "
        "public page. The default comes from Settings > Spreadsheet.",
    )
    created_by_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
        help="User who created this share link.",
    )
    share_url = fields.Char(
        compute="_compute_share_url",
        string="Share URL",
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

    def action_regenerate_token(self):
        self.ensure_one()
        self.token = secrets.token_urlsafe(32)
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

    @api.model
    def verify_token(self, token, password=None, count=True):
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
        # hmac.compare_digest rejects non-ASCII str; compare on UTF-8 bytes so a
        # password with accented/non-latin characters doesn't raise.
        if rec.password and not hmac.compare_digest(
            rec.password.encode("utf-8"), (password or "").encode("utf-8")
        ):
            return False
        if count:
            rec.sudo().write(
                {
                    "view_count": rec.view_count + 1,
                    "last_viewed": fields.Datetime.now(),
                }
            )
        return rec

    def get_rendered_sheets(self):  # noqa: C901
        """Return pre-processed sheet data suitable for HTML rendering.

        Each sheet gets: name, rows (list of lists of cells), col widths.
        Cells contain: content, style_css, border_css, colspan, rowspan.
        """
        self.ensure_one()
        raw = self.spreadsheet_id.sudo().spreadsheet_raw or {}
        styles = raw.get("styles", {})
        borders = raw.get("borders", {})

        result = []
        for sheet in raw.get("sheets", []):
            # Dashboard exports keep their pivot source data on a sheet named
            # "Data" that feeds the scorecards; it must never reach the public
            # preview. Its `isVisible` flag is unreliable across exports (False /
            # True / absent), so the sheet name is the only stable marker.
            if sheet.get("name") == "Data":
                continue

            cells = sheet.get("cells", {})
            if not cells:
                result.append({"name": sheet.get("name"), "rows": [], "cols": []})
                continue

            max_col = 0
            max_row = 0
            for ref in cells.keys():
                c, r = _parse_ref(ref)
                max_col = max(max_col, c)
                max_row = max(max_row, r)
            truncated = max_col > 25 or max_row > 99
            max_col = min(max_col, 25)
            max_row = min(max_row, 99)

            # Parse merges
            spans = {}
            hidden = set()
            for merge in sheet.get("merges", []):
                try:
                    tl_ref, br_ref = merge.split(":")
                    tl_c, tl_r = _parse_ref(tl_ref)
                    br_c, br_r = _parse_ref(br_ref)
                    spans[(tl_c, tl_r)] = {
                        "colspan": br_c - tl_c + 1,
                        "rowspan": br_r - tl_r + 1,
                    }
                    for r in range(tl_r, br_r + 1):
                        for c in range(tl_c, br_c + 1):
                            if (c, r) != (tl_c, tl_r):
                                hidden.add((c, r))
                except (ValueError, IndexError):
                    continue

            # Column widths
            cols = sheet.get("cols", {})
            col_widths = []
            for col in range(max_col + 1):
                w = (cols.get(str(col)) or cols.get(col) or {}).get("size", 100)
                col_widths.append(w)

            # Build row data
            rows_out = []
            sheet_rows = sheet.get("rows", {})
            for row in range(max_row + 1):
                row_height = (
                    sheet_rows.get(str(row)) or sheet_rows.get(row) or {}
                ).get("size")
                row_cells = []
                for col in range(max_col + 1):
                    if (col, row) in hidden:
                        continue
                    ref = _col_letter(col) + str(row + 1)
                    cell = cells.get(ref, {})
                    content = cell.get("content", "") or ""
                    display, computed = _resolve_display(content)

                    style_css = ""
                    s = (
                        styles.get(str(cell.get("style")))
                        if cell.get("style")
                        else None
                    )
                    if s:
                        if s.get("bold"):
                            style_css += "font-weight:bold;"
                        if s.get("italic"):
                            style_css += "font-style:italic;"
                        if s.get("textColor"):
                            style_css += f"color:{s['textColor']};"
                        if s.get("fillColor"):
                            style_css += f"background-color:{s['fillColor']};"
                        if s.get("fontSize"):
                            style_css += f"font-size:{s['fontSize']}px;"
                        if s.get("align"):
                            style_css += f"text-align:{s['align']};"

                    b = (
                        borders.get(str(cell.get("border")))
                        if cell.get("border")
                        else None
                    )
                    if b:
                        for side in ("top", "right", "bottom", "left"):
                            if b.get(side):
                                bstyle, bcolor = b[side]
                                width = "1px" if bstyle == "thin" else "2px"
                                style_css += (
                                    f"border-{side}:{width} solid {bcolor or '#000'};"
                                )

                    span = spans.get((col, row))
                    row_cells.append(
                        {
                            "content": content,
                            "display": display,
                            "computed": computed,
                            "style_css": style_css,
                            "colspan": span["colspan"] if span else 1,
                            "rowspan": span["rowspan"] if span else 1,
                        }
                    )
                rows_out.append({"height": row_height, "cells": row_cells})

            result.append(
                {
                    "name": sheet.get("name"),
                    "rows": rows_out,
                    "col_widths": col_widths,
                    "truncated": truncated,
                }
            )
        return result
