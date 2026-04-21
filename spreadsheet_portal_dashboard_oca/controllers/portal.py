# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


from odoo import http
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class SpreadsheetPortalDashboardController(CustomerPortal):
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "portal_dashboard_count" in counters:
            partner = request.env.user.partner_id
            dashboards = (
                request.env["spreadsheet.portal.dashboard"]
                .sudo()
                ._get_portal_dashboards(partner)
            )
            values["portal_dashboard_count"] = len(dashboards)
        return values

    @http.route(
        ["/my/dashboards"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_dashboards_list(self, **kw):
        partner = request.env.user.partner_id
        dashboards = (
            request.env["spreadsheet.portal.dashboard"]
            .sudo()
            ._get_portal_dashboards(partner)
        )
        values = {
            "dashboards": dashboards,
            "page_name": "dashboards",
        }
        return request.render(
            "spreadsheet_portal_dashboard_oca.portal_dashboards_list", values
        )

    @http.route(
        ["/my/dashboards/<int:dashboard_id>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_dashboard_detail(self, dashboard_id, **kw):
        partner = request.env.user.partner_id
        portal_dash = (
            request.env["spreadsheet.portal.dashboard"].sudo().browse(dashboard_id)
        )

        if not portal_dash.exists() or not portal_dash._is_accessible_by_partner(
            partner
        ):
            return request.redirect("/my/dashboards")

        values = {
            "dashboard": portal_dash,
            "page_name": "dashboard_detail",
        }
        return request.render(
            "spreadsheet_portal_dashboard_oca.portal_dashboard_detail", values
        )

    @http.route(
        ["/my/dashboards/<int:dashboard_id>/data"],
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def portal_dashboard_data(self, dashboard_id, **kw):
        """JSONRPC endpoint for fetching spreadsheet data for portal rendering."""
        partner = request.env.user.partner_id
        portal_dash = (
            request.env["spreadsheet.portal.dashboard"].sudo().browse(dashboard_id)
        )

        if not portal_dash.exists() or not portal_dash._is_accessible_by_partner(
            partner
        ):
            return {"error": "Access denied"}

        return portal_dash.get_portal_spreadsheet_data()
