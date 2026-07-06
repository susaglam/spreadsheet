# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SpreadsheetToTemplate(models.TransientModel):
    _name = "spreadsheet.to.template"
    _description = "Save Spreadsheet as Template"

    name = fields.Char(
        "Template Name",
        required=True,
        compute="_compute_name",
        store=True,
        readonly=False,
        precompute=True,
        help="Name of the template as it will appear in the template gallery. "
        "Defaults to the current spreadsheet name.",
    )
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        readonly=True,
        required=True,
        help="The spreadsheet whose current contents will be saved as a "
        "reusable template.",
    )
    description = fields.Text(
        "Description",
        help="What this template is for and when to use it — shown on the "
        "template's kanban card.",
    )
    category_id = fields.Many2one(
        "spreadsheet.template.category",
        string="Category",
        help="Optional grouping (Sales, Finance, HR...) used to organise "
        "templates in the gallery search panel.",
    )

    @api.depends("spreadsheet_id.name")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.spreadsheet_id.name

    def create_template(self):
        self.ensure_one()
        spreadsheet_data = self.spreadsheet_id.get_spreadsheet_data()
        spreadsheet_raw = spreadsheet_data["spreadsheet_raw"]
        template = self.env["spreadsheet.template"].create(
            {
                "name": self.name,
                "description": self.description,
                "category_id": self.category_id.id if self.category_id else False,
                "spreadsheet_raw": spreadsheet_raw,
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.name,
                "message": self.env._("Template created successfully."),
                "type": "success",
                "next": template.open_spreadsheet(),
            },
        }
