# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import re
import secrets

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


class SpreadsheetPublicShare(models.Model):
    _name = "spreadsheet.public.share"
    _description = "Public Spreadsheet Share Link"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        required=True,
        ondelete="cascade",
    )
    token = fields.Char(
        required=True,
        readonly=True,
        default=lambda self: secrets.token_urlsafe(32),
        copy=False,
    )
    expires_at = fields.Datetime(
        help="Optional expiry date for the share link.",
    )
    view_count = fields.Integer(readonly=True, default=0)
    last_viewed = fields.Datetime(readonly=True)
    password = fields.Char(
        help="Optional password to access the shared spreadsheet.",
    )
    allow_download = fields.Boolean(
        default=False,
        help="Allow downloading the spreadsheet data.",
    )
    created_by_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
    )
    share_url = fields.Char(
        compute="_compute_share_url",
        string="Share URL",
    )

    _token_unique = models.Constraint(
        "unique(token)",
        "Token must be unique.",
    )

    @api.depends("token")
    def _compute_share_url(self):
        # saas-19.2: ir.config_parameter.get_param() kaldirildi, get_str kullanilmali
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
    def verify_token(self, token, password=None):
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
        if rec.password and rec.password != (password or ""):
            return False
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
            max_col = min(max_col, 25)
            max_row = min(max_row, 100)

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
                    is_formula = content.startswith("=")

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
                            "is_formula": is_formula,
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
                }
            )
        return result
