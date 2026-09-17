# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.tests.common import HttpCase, TransactionCase, tagged

SPREADSHEETS_ACTION = "spreadsheet_oca.spreadsheet_spreadsheet_act_window"
TAG_MODEL = "spreadsheet.spreadsheet.tag"
# Keys of the web client user context (lang, tz, uid, companies)
SESSION_CONTEXT_KEYS = {"lang", "tz", "uid", "allowed_company_ids"}


def saved_commands(spreadsheet, command_type=None):
    """Core commands of the collaborative revisions of ``spreadsheet``.

    They are stored exactly as dispatched by the editor, so they show whether
    the payload matches what the saas-19.4 core plugins accept. Only commands
    dispatched by the editor or a UI plugin are recorded: the cells a core
    command writes itself (e.g. the =ODOO.LIST formula of INSERT_ODOO_LIST) are
    not.
    """
    commands = []
    for revision in spreadsheet._get_spreadsheet_revisions():
        commands.extend(json.loads(revision.commands).get("commands", []))
    if command_type:
        return [command for command in commands if command["type"] == command_type]
    return commands


class TestSpreadsheetImportWizard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.mode_new = cls.env.ref("spreadsheet_oca.spreadsheet_import_mode_new")
        cls.mode_add = cls.env.ref("spreadsheet_oca.spreadsheet_import_mode_add")
        cls.target = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Wizard Target Sheet"}
        )

    def _insert(self, **vals):
        wizard = self.env["spreadsheet.spreadsheet.import"].create(
            {
                "name": "Wizard New Sheet",
                "datasource_name": "Wizard Data",
                "import_data": {"mode": "pivot", "metaData": {}, "searchParams": {}},
                **vals,
            }
        )
        action = wizard.insert_pivot()
        self.assertEqual(action["tag"], "action_spreadsheet_oca")
        return action["params"]

    def test_new_spreadsheet_forwards_static_mode(self):
        """Unchecking "Dynamic Rows" reaches the editor as dynamic=False, which
        inserts the pivot as static values."""
        params = self._insert(
            mode_id=self.mode_new.id, can_be_dynamic=True, dynamic=False
        )
        spreadsheet = self.env["spreadsheet.spreadsheet"].browse(
            params["spreadsheet_id"]
        )
        self.assertEqual(spreadsheet.name, "Wizard New Sheet")
        import_data = params["import_data"]
        self.assertIs(import_data["dynamic"], False)
        self.assertEqual(import_data["new"], 1)
        self.assertEqual(import_data["name"], "Wizard Data")
        self.assertNotIn("dyn_number_of_rows", import_data)

    def test_add_to_spreadsheet_forwards_dynamic_rows(self):
        params = self._insert(
            mode_id=self.mode_add.id,
            spreadsheet_id=self.target.id,
            import_data={"mode": "list", "metaData": {}},
            can_be_dynamic=True,
            is_tree=True,
            dynamic=True,
            number_of_rows=20,
        )
        self.assertEqual(params["spreadsheet_id"], self.target.id)
        import_data = params["import_data"]
        self.assertIs(import_data["dynamic"], True)
        self.assertEqual(import_data["dyn_number_of_rows"], 20)
        self.assertNotIn("new", import_data)


@tagged("post_install", "-at_install")
class TestSpreadsheetInsertTours(HttpCase):
    """'Add to spreadsheet' from the pivot, list and graph views, into a new and
    into an existing spreadsheet, then the re-insert actions of the side panels.
    The tours live in static/tests/tours/insert_flows_tours.esm.js."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.group_ids = [(4, cls.env.ref("spreadsheet_oca.group_manager").id)]
        cls.env[TAG_MODEL].create(
            [{"name": "Insert Tour Tag A"}, {"name": "Insert Tour Tag B"}]
        )
        cls.existing = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Insert Tour Existing Sheet", "owner_id": cls.admin.id}
        )
        cls.pivot_action = cls._view_action(
            "pivot",
            '<pivot string="Insert Tour Pivot"><field name="name" type="row"/></pivot>',
        )
        cls.list_action = cls._view_action(
            "list", '<list><field name="name"/></list>', name="Insert Tour List"
        )
        cls.bar_action = cls._view_action(
            "graph",
            '<graph string="Insert Tour Graph" type="bar"><field name="name"/></graph>',
        )
        cls.line_action = cls._view_action(
            "graph",
            '<graph string="Insert Tour Graph" type="line" cumulated="1">'
            '<field name="name"/></graph>',
        )

    @classmethod
    def _view_action(cls, view_type, arch, name="Insert Tour Tags"):
        view = cls.env["ir.ui.view"].create(
            {
                "name": f"spreadsheet_oca insert tour {view_type}",
                "model": TAG_MODEL,
                "type": view_type,
                "arch": arch,
            }
        )
        return cls.env["ir.actions.act_window"].create(
            {
                "name": name,
                "res_model": TAG_MODEL,
                "view_mode": view_type,
                "view_id": view.id,
                "domain": "[('name', 'like', 'Insert Tour Tag')]",
            }
        )

    def _start(self, action, tour_name):
        self.start_tour(f"/odoo/action-{action.id}", tour_name, login="admin")

    def _created(self, name):
        spreadsheet = self.env["spreadsheet.spreadsheet"].search([("name", "=", name)])
        self.assertEqual(len(spreadsheet), 1)
        return spreadsheet

    def _new_sheet_id(self, name):
        (create_sheet,) = saved_commands(self.existing, "CREATE_SHEET")
        self.assertEqual(create_sheet["name"], name)
        return create_sheet["sheetId"]

    def test_insert_pivot_in_new_spreadsheet(self):
        self._start(self.pivot_action, "spreadsheet_oca_insert_pivot_new")
        spreadsheet = self._created("Insert Tour Pivot")
        (add_pivot,) = saved_commands(spreadsheet, "ADD_PIVOT")
        pivot = add_pivot["pivot"]
        self.assertEqual(pivot["type"], "ODOO")
        self.assertEqual(pivot["model"], TAG_MODEL)
        self.assertEqual(pivot["name"], "Insert Tour Pivot")
        self.assertEqual([row["fieldName"] for row in pivot["rows"]], ["name"])
        self.assertEqual([m["fieldName"] for m in pivot["measures"]], ["__count"])
        self.assertTrue(pivot["style"]["tableStyleId"])
        # The session context of the inserting user is not stored for readers
        self.assertFalse(set(pivot["context"]) & SESSION_CONTEXT_KEYS)
        contents = [c["content"] for c in saved_commands(spreadsheet, "UPDATE_CELL")]
        self.assertIn("=PIVOT(1)", contents)
        self.assertFalse(saved_commands(spreadsheet, "INSERT_PIVOT"))

    def test_insert_static_pivot_in_existing_spreadsheet(self):
        self._start(self.pivot_action, "spreadsheet_oca_insert_pivot_static_existing")
        sheet_id = self._new_sheet_id("Insert Tour Pivot")
        (add_pivot,) = saved_commands(self.existing, "ADD_PIVOT")
        (insert_pivot,) = saved_commands(self.existing, "INSERT_PIVOT")
        self.assertEqual(insert_pivot["pivotId"], add_pivot["pivotId"])
        self.assertEqual(insert_pivot["sheetId"], sheet_id)
        self.assertEqual((insert_pivot["col"], insert_pivot["row"]), (0, 0))
        contents = [c["content"] for c in saved_commands(self.existing, "UPDATE_CELL")]
        self.assertNotIn("=PIVOT(1)", contents)

    def _assert_list_inserted(self, spreadsheet):
        (insert_list,) = saved_commands(spreadsheet, "INSERT_ODOO_LIST")
        self.assertEqual(insert_list["listId"], "1")
        self.assertNotIn("id", insert_list)
        self.assertEqual(insert_list["mode"], "dynamic")
        self.assertEqual(insert_list["linesNumber"], 2)
        definition = insert_list["definition"]
        self.assertEqual(definition["model"], TAG_MODEL)
        self.assertEqual(definition["columns"], [{"name": "name"}])
        self.assertEqual(definition["name"], "Insert Tour List")
        self.assertNotIn("metaData", definition)
        return insert_list

    def test_insert_list_in_new_spreadsheet(self):
        self._start(self.list_action, "spreadsheet_oca_insert_list_new")
        self._assert_list_inserted(self._created("Insert Tour List"))

    def test_insert_list_in_existing_spreadsheet(self):
        """The new sheet name must be unique ignoring case: CREATE_SHEET refuses
        "Insert Tour List" next to "insert tour list"."""
        self.existing.spreadsheet_raw = {
            "sheets": [
                {"id": "sheet1", "name": "Sheet1", "cells": {}},
                {"id": "sheet2", "name": "insert tour list", "cells": {}},
            ],
            "revisionId": "START_REVISION",
        }
        self._start(self.list_action, "spreadsheet_oca_insert_list_existing")
        sheet_id = self._new_sheet_id("Insert Tour List (1)")
        insert_list = self._assert_list_inserted(self.existing)
        self.assertEqual(insert_list["sheetId"], sheet_id)

    def _assert_chart_created(self, spreadsheet, chart_type):
        (create_chart,) = saved_commands(spreadsheet, "CREATE_CHART")
        # saas-19.4 CREATE_CHART is refused without these figure arguments
        for key in ("figureId", "chartId", "sheetId", "col", "row", "offset"):
            self.assertIn(key, create_chart)
        definition = create_chart["definition"]
        self.assertEqual(definition["type"], chart_type)
        self.assertEqual(definition["title"]["text"], "Insert Tour Graph")
        data_source = definition["dataSource"]
        self.assertEqual(data_source["type"], "odoo")
        self.assertEqual(data_source["metaData"]["resModel"], TAG_MODEL)
        self.assertEqual(data_source["metaData"]["groupBy"], ["name"])
        self.assertEqual(data_source["metaData"]["measure"], "__count")
        self.assertEqual(data_source["searchParams"]["groupBy"], [])
        context = data_source["searchParams"]["context"]
        self.assertFalse(set(context) & SESSION_CONTEXT_KEYS)
        return create_chart

    def test_insert_graph_in_new_spreadsheet(self):
        self._start(self.bar_action, "spreadsheet_oca_insert_graph_new")
        create_chart = self._assert_chart_created(
            self._created("Insert Tour Graph"), "bar"
        )
        self.assertIs(create_chart["definition"]["stacked"], True)

    def test_insert_graph_in_existing_spreadsheet(self):
        self._start(self.line_action, "spreadsheet_oca_insert_graph_existing")
        sheet_id = self._new_sheet_id("Insert Tour Graph")
        create_chart = self._assert_chart_created(self.existing, "line")
        self.assertEqual(create_chart["sheetId"], sheet_id)
        self.assertIs(create_chart["definition"]["cumulative"], True)
        self.assertIs(create_chart["definition"]["fillArea"], True)

    def _datasource_sheet(self, name):
        """A spreadsheet holding list #1 and pivot #1 on the tags, no cell."""
        sheet = self.env["spreadsheet.spreadsheet"].create(
            {"name": name, "owner_id": self.admin.id}
        )
        # Current (saas-19.4) data format, without "version" so no migration
        # step rewrites it.
        sheet.spreadsheet_raw = {
            "sheets": [{"id": "sheet1", "name": "Sheet1", "cells": {}}],
            "lists": {
                "1": {
                    "id": "1",
                    "name": "Reinsert tour tags",
                    "model": TAG_MODEL,
                    "columns": [{"name": "name"}],
                    "domain": [],
                    "context": {},
                    "orderBy": [],
                    "fieldMatching": {},
                }
            },
            "listNextId": 2,
            "pivots": {
                "1": {
                    "type": "ODOO",
                    "formulaId": "1",
                    "name": "Reinsert tour tag count",
                    "model": TAG_MODEL,
                    "domain": [],
                    "context": {},
                    "measures": [
                        {
                            "id": "__count:sum",
                            "fieldName": "__count",
                            "aggregator": "sum",
                        }
                    ],
                    "columns": [],
                    "rows": [{"fieldName": "name"}],
                    "fieldMatching": {},
                }
            },
            "pivotNextId": 2,
            "globalFilters": [],
            "revisionId": "START_REVISION",
        }
        return sheet

    def test_reinsert_from_side_panels(self):
        """'Insert list' of the list panel and 'Re-insert Dynamic/Static' of the
        pivot panel cog wheel, at the selected cell."""
        sheet = self._datasource_sheet("Reinsert Tour Sheet")
        self.start_tour(
            f"/odoo/action-{SPREADSHEETS_ACTION}/{sheet.id}",
            "spreadsheet_oca_reinsert_from_side_panels",
            login="admin",
        )
        # A single insertion: the second click, with Rows emptied, only warns.
        (reinsert_list,) = saved_commands(sheet, "RE_INSERT_ODOO_LIST")
        self.assertEqual(reinsert_list["listId"], "1")
        # No cell showed the list: Rows proposed one list view page of records.
        tag_count = self.env[TAG_MODEL].search_count([])
        self.assertEqual(reinsert_list["linesNumber"], min(tag_count, 80) or 80)
        self.assertEqual(reinsert_list["mode"], "dynamic")
        self.assertEqual(reinsert_list["columns"], [{"name": "name"}])
        self.assertEqual((reinsert_list["col"], reinsert_list["row"]), (0, 0))
        contents = [c["content"] for c in saved_commands(sheet, "UPDATE_CELL")]
        self.assertIn("=PIVOT(1)", contents)
        (insert_pivot,) = saved_commands(sheet, "INSERT_PIVOT")
        self.assertEqual(insert_pivot["pivotId"], "1")

    def test_edit_domain_from_side_panels(self):
        """'Edit domain' of the pivot and list panels. DomainSelectorDialog
        confirms a string; the stored domain is a list when it needs no
        context, and stays a string when it does (uid), instead of throwing
        or being frozen at edit time. The debug mode shows the dialog's code
        editor."""
        sheet = self._datasource_sheet("Domain Tour Sheet")
        self.start_tour(
            f"/odoo/action-{SPREADSHEETS_ACTION}/{sheet.id}?debug=1",
            "spreadsheet_oca_edit_datasource_domains",
            login="admin",
        )
        update_pivot = saved_commands(sheet, "UPDATE_PIVOT")[-1]
        self.assertEqual(update_pivot["pivotId"], "1")
        self.assertEqual(
            update_pivot["pivot"]["domain"], [["name", "like", "Insert Tour Tag"]]
        )
        update_list = saved_commands(sheet, "UPDATE_ODOO_LIST_DOMAIN")[-1]
        self.assertEqual(update_list["listId"], "1")
        # Stored unevaluated: the list data source evaluates uid on each load
        self.assertIsInstance(update_list["domain"], str)
        self.assertRegex(update_list["domain"], r"create_uid.*,\s*uid\s*\)")
