# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def _get_translation_frontend_modules_name(self):
        # Make this module's frontend _t() strings (portal_spreadsheet.js)
        # available to the storefront/portal translation catalogue.
        modules = super()._get_translation_frontend_modules_name()
        return modules + ["spreadsheet_portal_dashboard_oca"]
