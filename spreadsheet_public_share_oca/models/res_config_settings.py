# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    public_share_default_expiry_days = fields.Integer(
        string="Default Share Link Expiry (days, 0 = no expiry)",
        config_parameter="spreadsheet_public_share.default_expiry_days",
        default=0,
    )
    public_share_allow_download_default = fields.Boolean(
        string="Allow Download by Default",
        config_parameter="spreadsheet_public_share.allow_download_default",
        default=False,
    )
