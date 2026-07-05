# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    email_report_default_format = fields.Selection(
        [("xlsx", "Excel (XLSX)"), ("json", "JSON Data")],
        string="Default Email Report Format",
        config_parameter="spreadsheet_email_report.default_format",
        default="xlsx",
    )
