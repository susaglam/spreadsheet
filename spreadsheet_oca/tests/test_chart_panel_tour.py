# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import HttpCase, tagged
from odoo.tools import mute_logger

from .test_insert_flows import saved_commands

SPREADSHEETS_ACTION = "spreadsheet_oca.spreadsheet_spreadsheet_act_window"
TAG_MODEL = "spreadsheet.spreadsheet.tag"
# Names looked up by static/tests/tours/chart_panel_tours.esm.js
GRAPH_TITLE = "Chart Panel Tour Graph"
LINKED_MENU_XMLID = "spreadsheet_oca.spreadsheet_spreadsheet_tag_menu"


@tagged("post_install", "-at_install")
class TestSpreadsheetChartPanelTour(HttpCase):
    """The chart side panel of charts fed by Odoo data (graph view inserted in a
    spreadsheet) and the getExtraModelCustom() extension point of the editor."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.group_ids = [(4, cls.env.ref("spreadsheet_oca.group_manager").id)]
        cls.env[TAG_MODEL].create(
            [{"name": "Chart Tour Tag A"}, {"name": "Chart Tour Tag B"}]
        )
        view = cls.env["ir.ui.view"].create(
            {
                "name": "spreadsheet_oca chart panel tour graph",
                "model": TAG_MODEL,
                "type": "graph",
                "arch": f'<graph string="{GRAPH_TITLE}" type="bar">'
                '<field name="name"/></graph>',
            }
        )
        cls.graph_action = cls.env["ir.actions.act_window"].create(
            {
                "name": GRAPH_TITLE,
                "res_model": TAG_MODEL,
                "view_mode": "graph",
                "view_id": view.id,
                "domain": "[('name', 'like', 'Chart Tour Tag')]",
            }
        )

    def _start_on_form(self, spreadsheet, tour_name):
        self.start_tour(
            f"/odoo/action-{SPREADSHEETS_ACTION}/{spreadsheet.id}",
            tour_name,
            login="admin",
        )

    def test_odoo_chart_types_and_menu_link(self):
        """The type picker of an Odoo data chart offers only the types the
        "odoo" data source supports, and the menu link is saved with the menu
        xml id and shown again when the spreadsheet is reopened."""
        self.start_tour(
            f"/odoo/action-{self.graph_action.id}",
            "spreadsheet_oca_chart_panel_odoo_chart",
            login="admin",
        )
        spreadsheet = self.env["spreadsheet.spreadsheet"].search(
            [("name", "=", GRAPH_TITLE)]
        )
        self.assertEqual(len(spreadsheet), 1)
        (create_chart,) = saved_commands(spreadsheet, "CREATE_CHART")
        self.assertEqual(create_chart["definition"]["dataSource"]["type"], "odoo")
        (update_link,) = saved_commands(spreadsheet, "UPDATE_ODOO_LINK_TO_CHART")
        self.assertEqual(update_link["chartId"], create_chart["chartId"])
        self.assertEqual(
            update_link["odooLink"],
            {"type": "odooMenu", "odooMenuId": LINKED_MENU_XMLID},
        )
        # The removed saas-19.2 command must not be sent any more
        self.assertFalse(saved_commands(spreadsheet, "LINK_ODOO_MENU_TO_CHART"))

        self._start_on_form(spreadsheet, "spreadsheet_oca_chart_panel_link_persists")

    def test_extra_model_custom_hook(self):
        spreadsheet = self.env["spreadsheet.spreadsheet"].create(
            {"name": "Model Custom Tour Sheet", "owner_id": self.admin.id}
        )
        self._start_on_form(spreadsheet, "spreadsheet_oca_model_custom_hook")

    def test_extra_model_custom_hook_failure(self):
        """A broken add-on hook shows a warning, the spreadsheet still opens."""
        spreadsheet = self.env["spreadsheet.spreadsheet"].create(
            {"name": "Model Custom Failure Tour Sheet", "owner_id": self.admin.id}
        )
        # The editor logs the add-on error as a browser console warning
        with mute_logger(f"{self._logger.name}.browser"):
            self._start_on_form(
                spreadsheet, "spreadsheet_oca_model_custom_hook_failure"
            )
