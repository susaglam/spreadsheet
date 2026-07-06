# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SpreadsheetSpreadsheet(models.Model):
    _inherit = "spreadsheet.spreadsheet"

    kpi_alert_ids = fields.One2many(
        "spreadsheet.kpi.alert",
        "spreadsheet_id",
        string="KPI Alerts",
    )
    kpi_alert_count = fields.Integer(
        compute="_compute_kpi_alert_count",
        string="KPI Alert Count",
    )

    @api.depends("kpi_alert_ids")
    def _compute_kpi_alert_count(self):
        for rec in self:
            rec.kpi_alert_count = len(rec.kpi_alert_ids)
