# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SpreadsheetTemplate(models.Model):
    _name = "spreadsheet.template"
    _inherit = ["spreadsheet.abstract"]
    _description = "Spreadsheet Template"
    _order = "sequence, name"

    sequence = fields.Integer(default=10)
    description = fields.Text(translate=True)
    category_id = fields.Many2one(
        "spreadsheet.template.category",
        string="Category",
        ondelete="set null",
        index=True,
    )
    thumbnail = fields.Image(
        max_width=1024,
        max_height=1024,
    )
    usage_count = fields.Integer(
        string="Times Used",
        default=0,
        readonly=True,
    )

    def action_create_spreadsheet(self):
        """Open wizard to create a new spreadsheet from this template."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Create Spreadsheet from Template"),
            "res_model": "spreadsheet.from.template",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "default_template_id": self.id,
                "default_name": self.name,
            },
        }

    def open_spreadsheet(self):
        """Open this template in the spreadsheet editor."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "action_spreadsheet_oca",
            "params": {
                "spreadsheet_id": self.id,
                "model": self._name,
            },
        }
