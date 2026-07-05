# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json

from odoo import fields, models


class SpreadsheetSpreadsheet(models.Model):
    _inherit = "spreadsheet.spreadsheet"

    version_ids = fields.One2many(
        "spreadsheet.version",
        "spreadsheet_id",
        string="Versions",
    )
    version_count = fields.Integer(compute="_compute_version_count")

    def _compute_version_count(self):
        for rec in self:
            rec.version_count = len(rec.version_ids)

    def action_create_snapshot(self, label=None, note=None):
        """Create a version snapshot of the current state."""
        self.ensure_one()
        raw = self.spreadsheet_raw
        if not raw:
            return False

        encoded = base64.b64encode(json.dumps(raw, default=str).encode("utf-8"))

        return self.env["spreadsheet.version"].create(
            {
                "name": label
                or self.env._("Snapshot %(ts)s", ts=fields.Datetime.now()),
                "spreadsheet_id": self.id,
                "version_label": label,
                "spreadsheet_data": encoded,
                "note": note,
            }
        )

    def action_view_versions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Versions - %(name)s", name=self.name),
            "res_model": "spreadsheet.version",
            "view_mode": "list,form",
            "domain": [("spreadsheet_id", "=", self.id)],
            "context": {"default_spreadsheet_id": self.id},
        }
