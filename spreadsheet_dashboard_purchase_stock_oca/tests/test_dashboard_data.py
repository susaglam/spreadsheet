# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import new_test_user, tagged

from odoo.addons.spreadsheet_dashboard_purchase_oca.tests.common import (
    DashboardDataCase,
)

KPI_REPORT_MODELS = ("purchase.report", "vendor.delay.report")


@tagged("post_install", "-at_install")
class TestPurchaseReceiptsDashboardData(DashboardDataCase):
    """The shipped "Purchase Receipts" dashboard (OCA 19.0) works on saas-19.4.

    Access note: upstream restricts the dashboard to ``stock.group_stock_manager``
    while its KPIs read ``purchase.report`` and ``vendor.delay.report``, which
    saas-19.4 only grants to ``purchase.group_purchase_user``. An inventory
    administrator without purchase rights therefore sees the dashboard with
    failing KPI figures; the tests below pin what does work (a purchase user
    reads every KPI model, and a user holding both groups gets the whole
    dashboard).
    """

    DASHBOARD_XMLID = (
        "spreadsheet_dashboard_purchase_stock_oca.spreadsheet_dashboard_purchase"
    )

    def test_purchases_section(self):
        self.assertEqual(self.dashboard.name, "Purchase Receipts")
        self.assert_in_purchases_section(sequence=300)
        vendors = self.env.ref(
            "spreadsheet_dashboard_purchase_oca.spreadsheet_dashboard_vendors"
        )
        self.assertEqual(vendors.dashboard_group_id, self.dashboard.dashboard_group_id)
        self.assertLess(vendors.sequence, self.dashboard.sequence)
        self.assertIn(
            self.env.ref("stock.model_stock_picking"),
            self.dashboard.main_data_model_ids,
        )

    def test_workbook_matches_registry(self):
        self.assert_workbook_matches_registry()
        self.assertEqual(self._models_used(), {"stock.picking", *KPI_REPORT_MODELS})

    def test_core_validator_accepts_workbook(self):
        self.assert_core_validator_accepts_workbook()

    def test_data_sources_load(self):
        self.assert_data_sources_load()

    def test_purchase_user_reads_kpi_models(self):
        """``purchase.group_purchase_user`` may read every model of the dashboard."""
        buyer = new_test_user(
            self.env,
            login="purchase_receipts_buyer",
            groups="base.group_user,purchase.group_purchase_user",
        )
        for model_name in self._models_used():
            self.assertTrue(
                self.env[model_name].with_user(buyer).has_access("read"),
                f"a purchase user cannot read {model_name}",
            )

    def test_dashboard_audience_reads_every_data_source(self):
        self.assertEqual(
            self.dashboard.group_ids, self.env.ref("stock.group_stock_manager")
        )
        user = new_test_user(
            self.env,
            login="purchase_receipts_manager",
            groups=(
                "base.group_user,stock.group_stock_manager,purchase.group_purchase_user"
            ),
        )
        dashboards = self.env["spreadsheet.dashboard"].with_user(user)
        self.assertEqual(
            dashboards.search([("id", "=", self.dashboard.id)]), self.dashboard
        )
        for model_name in self._models_used():
            self.assertTrue(
                self.env[model_name].with_user(user).has_access("read"),
                f"{user.login} cannot read {model_name}",
            )
        self.assert_data_sources_load(user=user)
