# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SpreadsheetFromTemplate(models.TransientModel):
    _name = "spreadsheet.from.template"
    _description = "Create Spreadsheet from Template"

    template_id = fields.Many2one(
        "spreadsheet.template",
        string="Template",
        required=True,
        readonly=True,
    )
    name = fields.Char(
        "Spreadsheet Name",
        required=True,
        compute="_compute_name",
        store=True,
        readonly=False,
        precompute=True,
    )

    @api.depends("template_id.name")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.template_id.name

    def create_spreadsheet(self):
        self.ensure_one()
        template_data = self.template_id.get_spreadsheet_data()
        spreadsheet_raw = template_data["spreadsheet_raw"]
        spreadsheet = self.env["spreadsheet.spreadsheet"].create(
            {
                "name": self.name,
                "spreadsheet_raw": spreadsheet_raw,
            }
        )
        self.template_id.sudo().write({"usage_count": self.template_id.usage_count + 1})
        return spreadsheet.open_spreadsheet()
