# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import new_test_user, tagged

from .common import PURCHASES_SECTION_XMLID, DashboardDataCase


@tagged("post_install", "-at_install")
class TestVendorsDashboardData(DashboardDataCase):
    """The shipped "Vendors" dashboard (OCA 19.0 export) works on saas-19.4."""

    DASHBOARD_XMLID = "spreadsheet_dashboard_purchase_oca.spreadsheet_dashboard_vendors"

    def test_purchases_section(self):
        section = self.env.ref(PURCHASES_SECTION_XMLID)
        self.assertEqual(section.name, "Purchases")
        self.assertEqual(section.sequence, 200)
        self.assert_in_purchases_section(sequence=200)
        self.assertIn(
            self.env.ref("purchase.model_purchase_order"),
            self.dashboard.main_data_model_ids,
        )

    def test_workbook_matches_registry(self):
        self.assert_workbook_matches_registry()
        self.assertEqual(self._models_used(), {"purchase.report", "purchase.order"})

    def test_core_validator_accepts_workbook(self):
        self.assert_core_validator_accepts_workbook()

    def test_data_sources_load(self):
        self.assert_data_sources_load()

    def test_dashboard_audience_reads_every_data_source(self):
        """A user of the dashboard's access group sees it and all its data."""
        self.assertEqual(
            self.dashboard.group_ids, self.env.ref("purchase.group_purchase_manager")
        )
        manager = new_test_user(
            self.env,
            login="purchase_dashboard_manager",
            groups="base.group_user,purchase.group_purchase_manager",
        )
        dashboards = self.env["spreadsheet.dashboard"].with_user(manager)
        self.assertEqual(
            dashboards.search([("id", "=", self.dashboard.id)]), self.dashboard
        )
        self.assertTrue(self.dashboard.dashboard_group_id.with_user(manager).name)
        for model_name in self._models_used():
            self.assertTrue(
                self.env[model_name].with_user(manager).has_access("read"),
                f"a purchase manager cannot read {model_name}",
            )
        self.assert_data_sources_load(user=manager)

    def test_hidden_from_users_outside_access_group(self):
        employee = new_test_user(
            self.env, login="purchase_dashboard_employee", groups="base.group_user"
        )
        dashboards = self.env["spreadsheet.dashboard"].with_user(employee)
        self.assertFalse(dashboards.search([("id", "=", self.dashboard.id)]))
