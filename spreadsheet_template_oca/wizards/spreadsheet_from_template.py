# Copyright 2026 Codesnap
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
        help="The template whose contents will be copied into the new spreadsheet.",
    )
    name = fields.Char(
        "Spreadsheet Name",
        required=True,
        compute="_compute_name",
        store=True,
        readonly=False,
        precompute=True,
        help="Name of the spreadsheet that will be created. Defaults to the "
        "template name; change it to something specific like "
        "'Sales Report - March 2026'.",
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
        # Atomic increment so concurrent uses of the same template don't lose
        # counts via a read-modify-write race.
        self.env.cr.execute(
            "UPDATE spreadsheet_template "
            "SET usage_count = COALESCE(usage_count, 0) + 1 WHERE id = %s",
            (self.template_id.id,),
        )
        self.template_id.invalidate_recordset(["usage_count"])
        return spreadsheet.open_spreadsheet()
