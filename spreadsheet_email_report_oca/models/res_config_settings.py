# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # The old email_report_default_format Selection was a dead setting: nothing
    # read the config_parameter and create() ignored it, and it still offered
    # the removed 'xlsx' format. Removed — the scheduler only produces JSON.
