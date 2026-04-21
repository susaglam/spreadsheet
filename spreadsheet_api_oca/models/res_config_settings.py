# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    api_default_rate_limit = fields.Integer(
        string="Default API Rate Limit (per minute)",
        config_parameter="spreadsheet_api.default_rate_limit_per_minute",
        default=60,
    )
    api_webhook_retry_max = fields.Integer(
        string="Maximum Webhook Retries",
        config_parameter="spreadsheet_api.webhook_retry_max",
        default=3,
    )
    api_token_default_expiry_days = fields.Integer(
        string="Default Token Expiry (days, 0 = no expiry)",
        config_parameter="spreadsheet_api.default_expiry_days",
        default=0,
    )
