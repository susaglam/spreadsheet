# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    kpi_alert_default_cooldown_hours = fields.Integer(
        string="Default KPI Alert Cooldown (hours)",
        config_parameter="spreadsheet_kpi_alert.default_cooldown_hours",
        default=24,
    )
    kpi_alert_default_send_email = fields.Boolean(
        string="Send Email by Default on KPI Alert",
        config_parameter="spreadsheet_kpi_alert.default_send_email",
        default=False,
    )
