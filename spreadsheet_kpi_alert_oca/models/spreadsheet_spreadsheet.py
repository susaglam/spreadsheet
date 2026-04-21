# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SpreadsheetSpreadsheet(models.Model):
    _inherit = "spreadsheet.spreadsheet"

    kpi_alert_ids = fields.One2many(
        "spreadsheet.kpi.alert",
        "spreadsheet_id",
        string="KPI Alerts",
    )
    kpi_alert_count = fields.Integer(
        compute="_compute_kpi_alert_count",
        string="KPI Alerts",
    )

    def _compute_kpi_alert_count(self):
        for rec in self:
            rec.kpi_alert_count = len(rec.kpi_alert_ids)
