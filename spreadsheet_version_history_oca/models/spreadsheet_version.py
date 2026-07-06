# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json
from html import escape as html_escape

from odoo import api, fields, models
from odoo.exceptions import UserError


def _bin_content(value):
    """saas-19.4: reading a Binary(attachment=True) field returns a
    BinaryValueAttachment wrapper whose bytes() is the raw (already
    base64-decoded) content. Fall back to base64-decoding a legacy str/bytes."""
    if not value:
        return b""
    if isinstance(value, (bytes, bytearray, str)):
        return base64.b64decode(value)
    return bytes(value)


class SpreadsheetVersion(models.Model):
    _name = "spreadsheet.version"
    _description = "Spreadsheet Version Snapshot"
    _order = "create_date desc"

    name = fields.Char(
        required=True,
        default=lambda self: self.env._("Snapshot %(ts)s", ts=fields.Datetime.now()),
        help="Human label for this snapshot; auto-filled as "
        '"Snapshot <timestamp>" when left blank.',
    )
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        required=True,
        ondelete="cascade",
        index=True,
        help="The spreadsheet this snapshot belongs to.",
    )
    version_label = fields.Char(
        help="Optional label (e.g., 'v1.0', 'before Q1 update').",
    )
    spreadsheet_data = fields.Binary(
        string="Snapshot Data",
        required=True,
        attachment=True,
    )
    created_by_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
        help="User who captured this snapshot.",
    )
    note = fields.Text(
        help="What changed in this version.",
    )
    size_bytes = fields.Integer(
        compute="_compute_size_bytes",
        store=True,
        help="Storage size of this snapshot in bytes "
        "(raw JSON before base64 encoding).",
    )
    diff_html = fields.Html(
        compute="_compute_diff",
        string="Visual Diff vs Current",
        sanitize=False,
    )
    cells_added = fields.Integer(
        compute="_compute_diff",
        help="Number of cells added versus the spreadsheet's current state.",
    )
    cells_changed = fields.Integer(
        compute="_compute_diff",
        help="Number of cells changed versus the spreadsheet's current state.",
    )
    cells_removed = fields.Integer(
        compute="_compute_diff",
        help="Number of cells removed versus the spreadsheet's current state.",
    )

    @api.depends("spreadsheet_data")
    def _compute_size_bytes(self):
        for rec in self:
            rec.size_bytes = len(_bin_content(rec.spreadsheet_data))

    @api.depends("spreadsheet_data", "spreadsheet_id.spreadsheet_raw")
    def _compute_diff(self):
        for rec in self:
            if not rec.spreadsheet_data or not rec.spreadsheet_id:
                rec.diff_html = ""
                rec.cells_added = 0
                rec.cells_changed = 0
                rec.cells_removed = 0
                continue
            try:
                version_data = json.loads(
                    _bin_content(rec.spreadsheet_data).decode("utf-8")
                )
            except Exception:
                rec.diff_html = "<p>{}</p>".format(
                    self.env._("Unable to decode version data.")
                )
                rec.cells_added = 0
                rec.cells_changed = 0
                rec.cells_removed = 0
                continue

            current_data = rec.spreadsheet_id.spreadsheet_raw or {}
            diff = rec._build_cell_diff(version_data, current_data)
            rec.diff_html = diff["html"]
            rec.cells_added = diff["added"]
            rec.cells_changed = diff["changed"]
            rec.cells_removed = diff["removed"]

    def _build_cell_diff(self, version_data, current_data):
        """Build a human-readable HTML diff of cell contents between
        version and current spreadsheet states.
        """
        added = changed = removed = 0
        rows_html = []

        version_sheets = {s.get("name"): s for s in version_data.get("sheets", [])}
        current_sheets = {s.get("name"): s for s in current_data.get("sheets", [])}
        all_sheet_names = set(version_sheets) | set(current_sheets)

        for sheet_name in sorted(all_sheet_names):
            v_cells = (version_sheets.get(sheet_name) or {}).get("cells", {})
            c_cells = (current_sheets.get(sheet_name) or {}).get("cells", {})
            all_refs = set(v_cells) | set(c_cells)

            sheet_rows = []
            for ref in sorted(all_refs, key=lambda r: (len(r), r)):
                v_content = (v_cells.get(ref) or {}).get("content", "")
                c_content = (c_cells.get(ref) or {}).get("content", "")
                if v_content == c_content:
                    continue
                if not v_content:
                    added += 1
                    status = "added"
                    badge = (
                        f'<span class="badge bg-success">{self.env._("Added")}</span>'
                    )
                elif not c_content:
                    removed += 1
                    status = "removed"
                    badge = (
                        f'<span class="badge bg-danger">{self.env._("Removed")}</span>'
                    )
                else:
                    changed += 1
                    status = "changed"
                    badge = (
                        f'<span class="badge bg-warning text-dark">'
                        f"{self.env._('Changed')}</span>"
                    )

                v_snippet = html_escape(v_content[:100])
                c_snippet = html_escape(c_content[:100])
                sheet_rows.append(
                    f'<tr class="diff-{status}">'
                    f"<td><code>{html_escape(ref)}</code></td>"
                    f"<td>{badge}</td>"
                    f'<td><small class="text-muted">{v_snippet}</small></td>'
                    f"<td><strong>{c_snippet}</strong></td>"
                    f"</tr>"
                )

            if sheet_rows:
                safe_name = html_escape(sheet_name)
                sheet_label = self.env._("Sheet:")
                th_cell = self.env._("Cell")
                th_status = self.env._("Status")
                th_version = self.env._("Version")
                th_current = self.env._("Current")
                rows_html.append(
                    f'<h5 class="mt-3">{sheet_label} <code>{safe_name}</code></h5>'
                    f'<table class="table table-sm table-bordered">'
                    f'<thead class="table-light"><tr>'
                    f"<th>{th_cell}</th><th>{th_status}</th>"
                    f"<th>{th_version}</th><th>{th_current}</th>"
                    f"</tr></thead><tbody>" + "".join(sheet_rows) + "</tbody></table>"
                )

        if not rows_html:
            html = '<p class="text-muted">{}</p>'.format(
                self.env._("No cell-level changes detected.")
            )
        else:
            summary_label = self.env._("Summary:")
            summary_text = self.env._(
                "%(a)s added, %(c)s changed, %(r)s removed.",
                a=added,
                c=changed,
                r=removed,
            )
            summary = (
                f'<div class="alert alert-info">'
                f"<strong>{summary_label}</strong> "
                f"{summary_text}"
                f"</div>"
            )
            html = summary + "".join(rows_html)

        return {
            "html": html,
            "added": added,
            "changed": changed,
            "removed": removed,
        }

    def action_restore(self):
        self.ensure_one()
        try:
            parsed = json.loads(_bin_content(self.spreadsheet_data).decode("utf-8"))
        except Exception as e:
            raise UserError(
                self.env._(
                    "Cannot restore '%(version)s': its stored snapshot is unreadable "
                    "(corrupted or truncated). Create a fresh snapshot and restore "
                    "that instead.",
                    version=self.name,
                )
            ) from e
        self.spreadsheet_id.write(
            {
                "spreadsheet_raw": parsed,
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Version Restored"),
                "message": self.env._(
                    "Spreadsheet '%(sheet)s' restored to version '%(version)s'.",
                    sheet=self.spreadsheet_id.name,
                    version=self.name,
                ),
                "type": "success",
                "next": self.spreadsheet_id.open_spreadsheet(),
            },
        }
