# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SpreadsheetPortalDashboard(models.Model):
    _name = "spreadsheet.portal.dashboard"
    _description = "Portal Dashboard Assignment"
    _order = "sequence, name"

    name = fields.Char(
        required=True,
        compute="_compute_name",
        store=True,
        readonly=False,
        precompute=True,
    )
    sequence = fields.Integer(
        default=10,
        help="Display order of this dashboard in the portal list; "
        "lower numbers appear first.",
    )
    active = fields.Boolean(default=True)
    dashboard_id = fields.Many2one(
        "spreadsheet.dashboard",
        string="Dashboard",
        required=True,
        ondelete="cascade",
        help="The internal spreadsheet dashboard whose read-only view is "
        "shared with the selected portal partners. Example: a 'Monthly "
        "Sales' dashboard shared with dealers.",
    )
    partner_ids = fields.Many2many(
        "res.partner",
        string="Portal Partners",
        help="Portal partners who can view this dashboard. "
        "Leave empty to share with all portal users.",
    )
    all_portal_users = fields.Boolean(
        string="All Portal Users",
        default=False,
        help="If checked, all portal users can see this dashboard.",
    )
    description = fields.Text(
        help="Description shown to portal users.",
    )

    @api.depends("dashboard_id.name")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.dashboard_id.name if rec.dashboard_id else ""

    def _is_accessible_by_partner(self, partner):
        """Check if a portal partner can access this dashboard."""
        self.ensure_one()
        if self.all_portal_users:
            return True
        commercial = partner.commercial_partner_id
        return commercial in self.partner_ids or partner in self.partner_ids

    @api.model
    def _get_portal_dashboards(self, partner):
        """Return portal dashboard assignments accessible by the given partner."""
        all_dashboards = self.sudo().search([("active", "=", True)])
        return all_dashboards.filtered(lambda d: d._is_accessible_by_partner(partner))

    def get_portal_spreadsheet_data(self):
        """Return spreadsheet data for portal rendering (read-only)."""
        self.ensure_one()
        dashboard = self.dashboard_id.sudo()
        data = dashboard.get_spreadsheet_data()
        data["mode"] = "readonly"
        return data
