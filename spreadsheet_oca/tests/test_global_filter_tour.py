# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.tests.common import HttpCase, tagged

SPREADSHEETS_ACTION = "spreadsheet_oca.spreadsheet_spreadsheet_act_window"


@tagged("post_install", "-at_install")
class TestSpreadsheetGlobalFilterTour(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        cls.admin.group_ids = [(4, cls.env.ref("spreadsheet_oca.group_manager").id)]
        # tours/global_filter_tours.esm.js selects this record as default value
        cls.partner = cls.env["res.partner"].create({"name": "Filter Tour Partner"})
        cls.sheet = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Global Filter Tour Sheet", "owner_id": cls.admin.id}
        )
        # Current (saas-19.4) data format, without "version" so no migration
        # step rewrites it: an Odoo list and an Odoo pivot the filters can be
        # matched with.
        cls.sheet.spreadsheet_raw = {
            "sheets": [
                {
                    "id": "sheet1",
                    "name": "Sheet1",
                    "cells": {"A1": '=ODOO.LIST.VALUE("1", "1", "name")'},
                }
            ],
            "lists": {
                "1": {
                    "id": "1",
                    "name": "Tour partners",
                    "model": "res.partner",
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
                    "name": "Tour partner count",
                    "model": "res.partner",
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
                    "rows": [],
                    "fieldMatching": {},
                }
            },
            "pivotNextId": 2,
            "globalFilters": [],
            "revisionId": "START_REVISION",
        }

    def test_global_filters_side_panel(self):
        """Text, relation and date global filters can be created with a default
        value and a data source matching, reopened, and their value changed
        from the Filters panel, on the saas-19.4 global filter API (field
        matching registry, operator-wrapped default values, FilterValue
        setGlobalFilterValue prop)."""
        self.start_tour(
            f"/odoo/action-{SPREADSHEETS_ACTION}/{self.sheet.id}",
            "spreadsheet_oca_global_filters",
            login="admin",
        )
        # The collaborative revisions hold the commands exactly as dispatched:
        # check the payload matches what the saas-19.4 core plugins accept.
        commands = {}
        for revision in self.sheet._get_spreadsheet_revisions():
            for command in json.loads(revision.commands).get("commands", []):
                if command["type"] in ("ADD_GLOBAL_FILTER", "EDIT_GLOBAL_FILTER"):
                    commands[(command["type"], command["filter"]["label"])] = command

        text = commands[("ADD_GLOBAL_FILTER", "Tour Text")]
        self.assertEqual(
            text["filter"]["defaultValue"], {"operator": "ilike", "strings": ["Azure"]}
        )
        self.assertEqual(text["list"]["1"], {"chain": "name", "type": "char"})
        self.assertEqual(text["pivot"]["1"], {})

        relation = commands[("ADD_GLOBAL_FILTER", "Tour Partner")]
        self.assertEqual(relation["filter"]["modelName"], "res.partner")
        self.assertEqual(
            relation["filter"]["defaultValue"],
            {"operator": "in", "ids": [self.partner.id]},
        )
        self.assertEqual(relation["pivot"]["1"], {"chain": "id", "type": "integer"})

        date = commands[("ADD_GLOBAL_FILTER", "Tour Date")]
        self.assertEqual(date["filter"]["defaultValue"], "last_30_days")
        self.assertNotIn("rangeType", date["filter"])

        renamed = commands[("EDIT_GLOBAL_FILTER", "Tour Text Renamed")]
        self.assertEqual(renamed["filter"]["id"], text["filter"]["id"])
        self.assertEqual(
            renamed["filter"]["defaultValue"], text["filter"]["defaultValue"]
        )
        self.assertEqual(renamed["list"]["1"], {"chain": "name", "type": "char"})
