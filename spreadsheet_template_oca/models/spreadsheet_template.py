# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SpreadsheetTemplate(models.Model):
    _name = "spreadsheet.template"
    _inherit = ["spreadsheet.abstract"]
    _description = "Spreadsheet Template"
    _order = "sequence, name"

    sequence = fields.Integer(
        default=10,
        help="Lower numbers sort first in lists and the kanban.",
    )
    description = fields.Text(
        translate=True,
        help="What this template is for and when to use it — shown on the "
        "kanban card. Example: 'Monthly sales summary with a pivot by "
        "salesperson and a total revenue KPI.'",
    )
    category_id = fields.Many2one(
        "spreadsheet.template.category",
        string="Category",
        ondelete="set null",
        index=True,
        help="Optional grouping (Sales, Finance, HR...) shown in the kanban "
        "search panel so users can filter templates by theme.",
    )
    thumbnail = fields.Image(
        max_width=1024,
        max_height=1024,
        help="Preview image shown on the template's kanban card.",
    )
    usage_count = fields.Integer(
        string="Times Used",
        default=0,
        readonly=True,
        help="How many spreadsheets have been created from this template; "
        "increments automatically each time someone uses it.",
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
