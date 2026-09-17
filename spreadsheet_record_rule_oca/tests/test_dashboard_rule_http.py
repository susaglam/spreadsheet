# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import HttpCase, tagged

from .common import VIEWER_PASSWORD, DashboardRuleCommon


@tagged("post_install", "-at_install")
class TestDashboardRuleController(DashboardRuleCommon, HttpCase):
    def test_core_dashboard_route_applies_rules(self):
        """The Dashboards app loads /spreadsheet/dashboard/data/<id>; a plain
        internal user must receive the rule-narrowed data sources."""
        self.create_rule("[('id', '=', partner_id)]")
        self.authenticate(self.viewer.login, VIEWER_PASSWORD)
        response = self.url_open(f"/spreadsheet/dashboard/data/{self.dashboard.id}")
        self.assertEqual(response.status_code, 200)
        snapshot = response.json()["snapshot"]
        leaf = ["id", "=", self.viewer.partner_id.id]
        self.assertEqual(snapshot["pivots"]["1"]["domain"], [leaf])
        self.assertIn(leaf, snapshot["lists"]["1"]["domain"])
        chart = snapshot["sheets"][0]["figures"][0]["data"]
        self.assertEqual(chart["searchParams"]["domain"], [leaf])
