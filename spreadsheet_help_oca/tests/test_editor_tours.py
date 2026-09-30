# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestEditorTours(HttpCase):
    """The Help cards' editor tours (static/src/js/tours.esm.js) that go through
    the o-spreadsheet top bar. Each one needs an optional module: it runs
    exactly when its Help card offers it (the tutorial is available), and is
    skipped, naming the missing module, when it is not."""

    def _require_tutorial(self, tutorial_xmlid):
        tutorial = self.env.ref(tutorial_xmlid)
        if not tutorial.is_available:
            self.skipTest(
                f"{tutorial.module_name} is not installed: the tour's menu entry "
                "does not exist, and its Help card does not offer the tour"
            )
        return tutorial

    def _admin_sheet(self, name):
        """A spreadsheet in the admin's "My Sheets" (the action's default
        filter), the one card the tours' first step opens."""
        admin = self.env.ref("base.user_admin")
        Spreadsheet = self.env["spreadsheet.spreadsheet"]
        # Sheets other installed modules gave the admin would be opened instead
        # (the test transaction is rolled back afterwards).
        Spreadsheet.search([("owner_id", "=", admin.id)]).write({"active": False})
        sheet = Spreadsheet.create({"name": name, "owner_id": admin.id})
        self.assertEqual(Spreadsheet.search([("owner_id", "=", admin.id)]), sheet)
        return admin, sheet

    def _start(self, tour_xmlid):
        tour = self.env.ref(tour_xmlid)
        self.start_tour(tour.url, tour.name, login="admin")

    def test_save_template_tour(self):
        """File > Save as Template: the wizard creates the template."""
        tutorial = self._require_tutorial("spreadsheet_help_oca.tutorial_template_save")
        admin, sheet = self._admin_sheet("Monthly Sales")
        # File > Save as Template is only shown to template managers
        # (TOUR_REQUIRED_GROUPS in models/spreadsheet_tutorial.py).
        admin.group_ids = [
            (4, self.env.ref("spreadsheet_template_oca.group_template_manager").id)
        ]
        self.assertEqual(
            tutorial.with_user(admin).action_start_tour()["tag"],
            "spreadsheet_help_start_tour",
        )
        self._start("spreadsheet_help_oca.tour_save_template")
        self.assertEqual(
            self.env["spreadsheet.template"].search_count(
                [("name", "=", "Monthly Sales Report Template")]
            ),
            1,
        )

    def test_kpi_alert_tour(self):
        """Data > KPI Alerts: the alert is created on the opened spreadsheet
        and Test Alert notifies right away."""
        self._require_tutorial("spreadsheet_help_oca.tutorial_kpi_alert")
        admin, sheet = self._admin_sheet("Revenue")
        self._start("spreadsheet_help_oca.tour_kpi_alert")
        alert = self.env["spreadsheet.kpi.alert"].search(
            [("spreadsheet_id", "=", sheet.id)]
        )
        self.assertEqual(len(alert), 1)
        self.assertEqual(alert.name, "Revenue threshold crossed")
        self.assertEqual(alert.cell_ref, "B5")
        self.assertEqual(alert.threshold_value, 40000)
        self.assertEqual(alert.create_uid, admin)
        # Test Alert by the spreadsheet's owner is a real (not private) test.
        self.assertTrue(alert.last_triggered)
