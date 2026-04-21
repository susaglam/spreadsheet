# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    contract_default_reminder_days = fields.Integer(
        string="Default Contract Renewal Reminder (days)",
        config_parameter="spreadsheet_contract.default_reminder_days",
        default=30,
    )
