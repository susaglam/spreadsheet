# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTutorialActions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tutorial = cls.env["spreadsheet.tutorial"]

    def test_open_example_without_spreadsheet_returns_warning(self):
        tutorial = self.Tutorial.create({"name": "No example tutorial"})
        result = tutorial.action_open_example()
        self.assertEqual(result.get("type"), "ir.actions.client")
        self.assertEqual(result.get("tag"), "display_notification")
        self.assertEqual(result["params"]["type"], "warning")

    def test_start_tour_without_tour_name_returns_info(self):
        tutorial = self.Tutorial.create({"name": "No tour tutorial"})
        result = tutorial.action_start_tour()
        self.assertEqual(result.get("type"), "ir.actions.client")
        self.assertEqual(result.get("tag"), "display_notification")
        self.assertEqual(result["params"]["type"], "info")

    def test_start_tour_with_tour_name_returns_client_action(self):
        tutorial = self.Tutorial.create(
            {"name": "Quick start", "tour_name": "spreadsheet_quick_start"}
        )
        result = tutorial.action_start_tour()
        self.assertEqual(result.get("type"), "ir.actions.client")
        self.assertEqual(result.get("tag"), "spreadsheet_help_start_tour")
        self.assertEqual(result["params"]["tour_name"], "spreadsheet_quick_start")
