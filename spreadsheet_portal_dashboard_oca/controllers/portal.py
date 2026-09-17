# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


from odoo import http
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class SpreadsheetPortalDashboardController(CustomerPortal):
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "portal_dashboard_count" in counters:
            dashboards = request.env[
                "spreadsheet.portal.dashboard"
            ]._get_portal_dashboards(request.env.user)
            values["portal_dashboard_count"] = len(dashboards)
        return values

    def _get_accessible_portal_dashboard(self, dashboard_id):
        """Return the sudo assignment if the current user may view it.

        Checks existence, the assignment's and the dashboard's ``active`` flag
        and the partner / portal-user scope (see ``_is_accessible_by_user``).
        Returns an empty recordset otherwise.
        """
        portal_dash = (
            request.env["spreadsheet.portal.dashboard"]
            .sudo()
            .browse(dashboard_id)
            .exists()
        )
        if portal_dash and portal_dash._is_accessible_by_user(request.env.user):
            return portal_dash
        return portal_dash.browse()

    @http.route(
        ["/my/dashboards"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_dashboards_list(self, unavailable=None, **kw):
        dashboards = request.env["spreadsheet.portal.dashboard"]._get_portal_dashboards(
            request.env.user
        )
        values = self._prepare_portal_layout_values()
        values.update(
            {
                "dashboards": dashboards,
                "page_name": "dashboards",
                # Set by the detail route when the requested dashboard was
                # archived or unshared: explain it instead of a silent bounce.
                "dashboard_unavailable": bool(unavailable),
            }
        )
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
        portal_dash = self._get_accessible_portal_dashboard(dashboard_id)
        if not portal_dash:
            return request.redirect("/my/dashboards?unavailable=1")

        values = self._prepare_portal_layout_values()
        values.update(
            {
                "dashboard": portal_dash,
                "page_name": "dashboard_detail",
            }
        )
        return request.render(
            "spreadsheet_portal_dashboard_oca.portal_dashboard_detail", values
        )

    @http.route(
        ["/my/dashboards/<int:dashboard_id>/data"],
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        readonly=True,
    )
    def portal_dashboard_data(self, dashboard_id, **kw):
        """JSONRPC endpoint for fetching spreadsheet data for portal rendering."""
        portal_dash = self._get_accessible_portal_dashboard(dashboard_id)
        if not portal_dash:
            return {
                "error": request.env._(
                    "This dashboard is not available to your account. It may "
                    "have been archived or is no longer shared with you. "
                    "Go back to Dashboards, or ask your contact person to "
                    "share it again."
                )
            }
        return portal_dash._get_portal_spreadsheet_data()
