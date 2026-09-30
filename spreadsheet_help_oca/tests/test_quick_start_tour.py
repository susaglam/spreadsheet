# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestQuickStartTour(HttpCase):
    def test_quick_start_tour(self):
        """The Help card's Quick Start tour (static/src/js/tours.esm.js) runs
        from the URL stored on its web_tour.tour row to the editor."""
        tour = self.env.ref("spreadsheet_help_oca.tour_quick_start")
        admin = self.env.ref("base.user_admin")
        admin.group_ids = [(4, self.env.ref("spreadsheet_oca.group_manager").id)]
        self.start_tour(tour.url, tour.name, login="admin")
        self.assertTrue(
            self.env["spreadsheet.spreadsheet"].search_count(
                [("name", "=", "Sales Report"), ("owner_id", "=", admin.id)]
            )
        )
