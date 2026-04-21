# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    refresh_default_interval_hours = fields.Integer(
        string="Default Refresh Interval (hours)",
        config_parameter="spreadsheet_scheduled_refresh.default_interval_hours",
        default=24,
    )
