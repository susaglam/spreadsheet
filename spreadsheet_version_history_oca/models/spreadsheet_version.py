# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json
import logging
from html import escape as html_escape

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from ..tools.cell_data import (
    CompressedCell,
    ExpansionBudget,
    workbook_cell_contents,
    xc_sort_key,
)

_logger = logging.getLogger(__name__)

# Rows listed in the visual diff; the added/changed/removed counters still
# count every difference. Keeps the form fast and its HTML small.
MAX_DIFF_ROWS = 2000
# Sheet names listed in the "shown as stored" warning.
MAX_WARNING_SHEETS = 10


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
        help="The full content of the spreadsheet at the moment the snapshot was "
        "captured. It cannot be changed afterwards; restoring the snapshot "
        "writes it back to the spreadsheet.",
    )
    created_by_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
        help="User who captured this snapshot. Set automatically when the "
        "snapshot is created and cannot be changed.",
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
        help="Cell-by-cell comparison of this snapshot with the spreadsheet as it "
        "is now: which cells were added, changed or removed since the snapshot, "
        "with the old and new value side by side. Only contents (values and "
        "formulas) are compared, not formatting.",
    )
    cells_added = fields.Integer(
        compute="_compute_diff",
        help="Number of cells that have content in the spreadsheet now but were "
        "empty in this snapshot.",
    )
    cells_changed = fields.Integer(
        compute="_compute_diff",
        help="Number of cells whose content differs between this snapshot and "
        "the spreadsheet now.",
    )
    cells_removed = fields.Integer(
        compute="_compute_diff",
        help="Number of cells that had content in this snapshot but are empty "
        "in the spreadsheet now.",
    )

    # -- access ----------------------------------------------------------------
    #
    # ir.access.csv scopes every operation to the snapshot's spreadsheet:
    # reading needs read access to it, creating or editing needs write access
    # (owner, contributor, manager). The checks below add what those rules
    # cannot express, with messages that explain the refusal. They are not
    # @api.constrains methods: saas-19.4 runs constraints as sudo
    # (BaseModel._validate_fields), where every access check passes.

    def _spreadsheet_label(self, spreadsheet):
        """Name a spreadsheet in an error message without revealing the name
        of one the current user may not open."""
        if spreadsheet.has_access("read"):
            return spreadsheet.display_name
        return f"#{spreadsheet.id}"

    def _check_spreadsheet_editable(self, spreadsheet_values):
        """Raise when the current user may not edit one of the spreadsheets
        (ids or records) a snapshot is about to be attached to.

        The ir.access create check runs after the insert and refuses this too,
        but with a generic message. The write check runs BEFORE the write,
        against the snapshot's current spreadsheet only, so a snapshot moved to
        another spreadsheet is checked here and nowhere else.
        """
        if self.env.su:
            return
        ids = set()
        for value in spreadsheet_values:
            if isinstance(value, models.BaseModel):
                ids.update(value._origin.ids)
            elif isinstance(value, int) and not isinstance(value, bool) and value:
                ids.add(value)
        spreadsheets = self.env["spreadsheet.spreadsheet"].browse(sorted(ids)).exists()
        for spreadsheet in spreadsheets:
            if not spreadsheet.has_access("write"):
                raise AccessError(
                    self.env._(
                        "You cannot save a snapshot on spreadsheet %(spreadsheet)s "
                        "because you are not allowed to edit that spreadsheet. A "
                        "snapshot can be restored over the spreadsheet's content, "
                        "so only its owner, its contributors and spreadsheet "
                        "managers may create a snapshot on it or move one to it. "
                        "Ask the owner to add you as a contributor, or use a "
                        "spreadsheet you can edit.",
                        spreadsheet=self._spreadsheet_label(spreadsheet),
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            default_spreadsheet = self.env.context.get("default_spreadsheet_id")
            self._check_spreadsheet_editable(
                [vals.get("spreadsheet_id", default_spreadsheet) for vals in vals_list]
            )
            # Who captured a snapshot is part of its audit trail: like
            # create_uid, it is always the user who creates it.
            vals_list = [dict(vals, created_by_id=self.env.uid) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        if self.env.su or not self:
            return super().write(vals)
        # Generic refusal first, so a user without access to these snapshots
        # learns nothing about them from the messages below.
        self.check_access("write")
        if "spreadsheet_data" in vals or (
            "created_by_id" in vals
            and any(
                snapshot.created_by_id.id != vals["created_by_id"]
                for snapshot in self.sudo()
            )
        ):
            raise UserError(
                self.env._(
                    "The captured content of a snapshot and the user who captured "
                    "it cannot be changed. They record the spreadsheet as it was "
                    "at that moment, and restoring the snapshot must bring back "
                    "exactly that. You can still edit its name, label and note; "
                    "to record the spreadsheet as it is now, use 'New Snapshot' "
                    "on the spreadsheet."
                )
            )
        if "spreadsheet_id" in vals:
            self._check_spreadsheet_editable([vals["spreadsheet_id"]])
        return super().write(vals)

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
                rec.diff_html = '<p class="text-danger">{}</p>'.format(
                    self.env._(
                        "This snapshot's stored data is unreadable (corrupted or "
                        "truncated), so no comparison can be shown and it cannot "
                        "be restored. A spreadsheet manager can delete it; use "
                        "'New Snapshot' on the spreadsheet to capture a fresh one."
                    )
                )
                rec.cells_added = 0
                rec.cells_changed = 0
                rec.cells_removed = 0
                continue

            try:
                current_data = rec.spreadsheet_id.spreadsheet_raw or {}
                diff = rec._build_cell_diff(version_data, current_data)
            except Exception:
                # The diff is a read-only convenience: an unexpected workbook
                # layout must never stop the snapshot form (and its Restore
                # button) from opening.
                _logger.warning(
                    "Could not build the visual diff of spreadsheet version %s",
                    rec.id,
                    exc_info=True,
                )
                diff = {
                    "html": '<p class="text-warning">{}</p>'.format(
                        self.env._(
                            "The visual diff could not be built for this snapshot. "
                            "The snapshot itself is intact and can still be "
                            "restored. If this keeps happening, send the server "
                            "log to your administrator."
                        )
                    ),
                    "added": 0,
                    "changed": 0,
                    "removed": 0,
                }
            rec.diff_html = diff["html"]
            rec.cells_added = diff["added"]
            rec.cells_changed = diff["changed"]
            rec.cells_removed = diff["removed"]

    def _build_cell_diff(self, version_data, current_data):
        """Build a human-readable HTML diff of cell contents between
        version and current spreadsheet states.

        Both workbook layouts are accepted: legacy object cells
        (``{"content": ...}``) and the plain-string, squished cells the
        saas-19.4 editor saves (see ``tools/cell_data.py``). Only contents
        (values and formulas) are compared, not formatting. Each side gets
        its own expansion budget, and at most ``MAX_DIFF_ROWS`` rows are
        listed (the counters include every difference).
        """
        version_budget = ExpansionBudget()
        current_budget = ExpansionBudget()
        version_sheets, version_partial = workbook_cell_contents(
            version_data, version_budget
        )
        current_sheets, current_partial = workbook_cell_contents(
            current_data, current_budget
        )
        counts = {"added": 0, "changed": 0, "removed": 0}
        rows_html = []
        shown = 0
        for sheet_name in sorted(set(version_sheets) | set(current_sheets)):
            sheet_rows = []
            for ref, v_content, c_content in self._diff_sheet_cells(
                version_sheets.get(sheet_name) or {},
                current_sheets.get(sheet_name) or {},
            ):
                if not v_content:
                    status = "added"
                elif not c_content:
                    status = "removed"
                else:
                    status = "changed"
                counts[status] += 1
                if shown < MAX_DIFF_ROWS:
                    shown += 1
                    sheet_rows.append(
                        self._diff_row_html(ref, status, v_content, c_content)
                    )
            if sheet_rows:
                rows_html.append(self._diff_table_html(sheet_name, sheet_rows))

        html = self._diff_summary_html(counts, rows_html, shown)
        partial_sheets = sorted(version_partial | current_partial)
        if partial_sheets:
            too_large = version_budget.exhausted or current_budget.exhausted
            html = self._diff_partial_warning_html(partial_sheets, too_large) + html
        return {
            "html": html,
            "added": counts["added"],
            "changed": counts["changed"],
            "removed": counts["removed"],
        }

    @staticmethod
    def _diff_sheet_cells(v_cells, c_cells):
        """Yield ``(ref, version content, current content)`` for each cell
        whose content differs, row first then column."""
        for ref in sorted(set(v_cells) | set(c_cells), key=xc_sort_key):
            v_content = v_cells.get(ref, "")
            c_content = c_cells.get(ref, "")
            if v_content != c_content:
                yield ref, v_content, c_content

    def _diff_cell_html(self, content):
        if isinstance(content, CompressedCell):
            # Internal storage syntax (e.g. {"N": "+1"}) means nothing to a
            # user: show a placeholder, keep the raw value in the tooltip.
            placeholder = self.env._(
                "(compressed value — open the spreadsheet to see it)"
            )
            raw = html_escape(content[:500])
            return f'<em title="{raw}">{html_escape(placeholder)}</em>'
        return html_escape(content[:100])

    def _diff_row_html(self, ref, status, v_content, c_content):
        if status == "added":
            badge = f'<span class="badge bg-success">{self.env._("Added")}</span>'
        elif status == "removed":
            badge = f'<span class="badge bg-danger">{self.env._("Removed")}</span>'
        else:
            badge = (
                f'<span class="badge bg-warning text-dark">'
                f"{self.env._('Changed')}</span>"
            )
        return (
            f'<tr class="diff-{status}">'
            f"<td><code>{html_escape(ref)}</code></td>"
            f"<td>{badge}</td>"
            f'<td><small class="text-muted">{self._diff_cell_html(v_content)}'
            f"</small></td>"
            f"<td><strong>{self._diff_cell_html(c_content)}</strong></td>"
            f"</tr>"
        )

    def _diff_table_html(self, sheet_name, sheet_rows):
        return (
            f'<h5 class="mt-3">{self.env._("Sheet:")} '
            f"<code>{html_escape(sheet_name)}</code></h5>"
            f'<table class="table table-sm table-bordered">'
            f'<thead class="table-light"><tr>'
            f"<th>{self.env._('Cell')}</th><th>{self.env._('Status')}</th>"
            f"<th>{self.env._('Version')}</th><th>{self.env._('Current')}</th>"
            f"</tr></thead><tbody>" + "".join(sheet_rows) + "</tbody></table>"
        )

    def _diff_summary_html(self, counts, rows_html, shown):
        if not rows_html:
            return '<p class="text-muted">{}</p>'.format(
                self.env._("No cell-level changes detected.")
            )
        summary_text = self.env._(
            "%(a)s added, %(c)s changed, %(r)s removed.",
            a=counts["added"],
            c=counts["changed"],
            r=counts["removed"],
        )
        html = (
            f'<div class="alert alert-info">'
            f"<strong>{self.env._('Summary:')}</strong> "
            f"{summary_text}"
            f"</div>" + "".join(rows_html)
        )
        hidden = sum(counts.values()) - shown
        if hidden > 0:
            html += '<p class="text-muted">{}</p>'.format(
                self.env._(
                    "%(count)s more differences are not listed, to keep this page "
                    "fast. The summary above counts them all; open the spreadsheet "
                    "to review them.",
                    count=hidden,
                )
            )
        return html

    def _diff_partial_warning_html(self, partial_sheets, too_large):
        names = [html_escape(name) for name in partial_sheets[:MAX_WARNING_SHEETS]]
        if len(partial_sheets) > MAX_WARNING_SHEETS:
            names.append("…")
        sheets = ", ".join(names)
        if too_large:
            warning = self.env._(
                "This spreadsheet is too large to compare every cell on this "
                "screen, so some cells of the sheet(s) %(sheets)s are shown as "
                "stored and may be listed as changed even when their value is "
                "the same. Open the spreadsheet to check those cells.",
                sheets=sheets,
            )
        else:
            warning = self.env._(
                "Some cells of the sheet(s) %(sheets)s are stored in a compressed "
                "form that this screen could not fully expand, so they are shown "
                "as stored and may be listed as changed even when their value is "
                "the same. Open the spreadsheet to check those cells.",
                sheets=sheets,
            )
        return f'<div class="alert alert-warning">{warning}</div>'

    def action_restore(self):
        self.ensure_one()
        spreadsheet = self.spreadsheet_id
        if not spreadsheet.has_access("write"):
            raise AccessError(
                self.env._(
                    "You cannot restore '%(version)s' because you may view "
                    "spreadsheet %(sheet)s but not edit it. Restoring replaces the "
                    "spreadsheet's current content with this snapshot, so only its "
                    "owner, its contributors and spreadsheet managers may do it. "
                    "Ask the owner to restore it, or to add you as a contributor.",
                    version=self.name,
                    sheet=self._spreadsheet_label(spreadsheet),
                )
            )
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
