# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import HttpCase, tagged

SPREADSHEETS_ACTION = "spreadsheet_oca.spreadsheet_spreadsheet_act_window"


@tagged("post_install", "-at_install")
class TestAddToDashboardTour(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.group_ids = [
            (4, cls.env.ref("spreadsheet_oca.group_manager").id),
            (4, cls.env.ref("spreadsheet_dashboard.group_dashboard_manager").id),
        ]
        # static/tests/tours/add_to_dashboard_tour.esm.js looks these names up
        cls.sheet = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Dashboard Tour Sheet", "owner_id": cls.admin.id}
        )
        cls.section = cls.env["spreadsheet.dashboard.group"].create(
            {"name": "Dashboard Tour Section"}
        )

    def test_add_to_dashboard_from_editor(self):
        """File > Add to dashboard (patched SpreadsheetRenderer) saves the
        spreadsheet, opens the wizard and creates an editable dashboard."""
        self.start_tour(
            f"/odoo/action-{SPREADSHEETS_ACTION}/{self.sheet.id}",
            "spreadsheet_dashboard_oca_add_to_dashboard",
            login="admin",
        )
        dashboard = self.env["spreadsheet.dashboard"].search(
            [("dashboard_group_id", "=", self.section.id)]
        )
        self.assertEqual(dashboard.name, "Dashboard Tour Sheet")
        self.assertTrue(dashboard.can_edit)
