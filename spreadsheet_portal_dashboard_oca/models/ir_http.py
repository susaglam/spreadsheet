# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _get_translation_frontend_modules_name(cls):
        # Make this module's frontend _t() strings (portal_spreadsheet.js)
        # available to the storefront/portal translation catalogue.
        # MUST be a classmethod: every core override (http_routing, portal,
        # delivery, website_sale ...) is one, and their super() chain calls it
        # without an instance -> an instance method here raises TypeError and
        # turns /website/translations into a site-wide 500.
        modules = super()._get_translation_frontend_modules_name()
        return modules + ["spreadsheet_portal_dashboard_oca"]
