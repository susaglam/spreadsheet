# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import HttpCase, tagged

SPREADSHEETS_ACTION = "spreadsheet_oca.spreadsheet_spreadsheet_act_window"


class SpreadsheetTourCommon(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.group_ids = [(4, cls.env.ref("spreadsheet_oca.group_manager").id)]
        # tours/control_panel_tours.esm.js looks this name up
        cls.sheet = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Breadcrumb Tour Sheet", "owner_id": cls.admin.id}
        )

    def _start_breadcrumbs_tour(self, tour_name):
        # Spreadsheets (kanban) > sheet (form) > editor: three breadcrumbs, so
        # the first one collapses into the dropdown of the editor's control
        # panel.
        self.start_tour(
            f"/odoo/action-{SPREADSHEETS_ACTION}/{self.sheet.id}",
            tour_name,
            login="admin",
        )


@tagged("post_install", "-at_install")
class TestSpreadsheetControlPanelTour(SpreadsheetTourCommon):
    def test_collapsed_breadcrumbs_desktop(self):
        """The editor's control panel renders the collapsed breadcrumb dropdown
        (Dropdown/DropdownItem from the parent ControlPanel) and it navigates."""
        self._start_breadcrumbs_tour("spreadsheet_oca_breadcrumbs_desktop")

    def test_list_view_add_to_spreadsheet(self):
        """The list view's own renderer still handles 'Add to spreadsheet'."""
        self.env["spreadsheet.spreadsheet.tag"].create({"name": "List Tour Tag"})
        self.start_tour(
            "/odoo/action-spreadsheet_oca.spreadsheet_spreadsheet_tags_act_window",
            "spreadsheet_oca_list_add_to_spreadsheet",
            login="admin",
        )

    def test_x2many_list_ignores_add_to_spreadsheet(self):
        """An x2many list of a form must not offer "Add to spreadsheet": the
        action lives on the list view controller only, because an x2many's
        env.model.root is the form record, whose fields do not describe the
        list columns ("fields[col.name] is undefined" in 18.0)."""
        partner_model = self.env["ir.model"]._get("res.partner")
        self.start_tour(
            f"/odoo/action-base.action_model_model/{partner_model.id}",
            "spreadsheet_oca_x2many_list_ignores_add",
            login="admin",
        )

    def _graph_action(self, domain):
        return self.env["ir.actions.act_window"].create(
            {
                "name": "Spreadsheet tags graph",
                "res_model": "spreadsheet.spreadsheet.tag",
                "view_mode": "graph",
                "domain": domain,
            }
        )

    def test_graph_add_to_spreadsheet_enabled_with_data(self):
        self.env["spreadsheet.spreadsheet.tag"].create({"name": "Graph Tour Tag"})
        action = self._graph_action("[]")
        self.start_tour(
            f"/odoo/action-{action.id}",
            "spreadsheet_oca_graph_add_enabled",
            login="admin",
        )

    def test_graph_add_to_spreadsheet_disabled_without_data(self):
        action = self._graph_action("[('id', '=', 0)]")
        self.start_tour(
            f"/odoo/action-{action.id}",
            "spreadsheet_oca_graph_add_disabled",
            login="admin",
        )


@tagged("post_install", "-at_install")
class TestSpreadsheetControlPanelMobileTour(SpreadsheetTourCommon):
    browser_size = "375x667"
    touch_enabled = True

    def test_collapsed_breadcrumbs_mobile(self):
        """At 375px the editor keeps a back arrow and the collapsed breadcrumb
        dropdown in its own control panel."""
        self._start_breadcrumbs_tour("spreadsheet_oca_breadcrumbs_mobile")
