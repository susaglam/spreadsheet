# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json
import re

from odoo.tests.common import TransactionCase, tagged

# Measure/pseudo fields that are not real ORM fields on the model.
SPECIAL_FIELDS = {"__count"}

_PIVOT_ID_RE = re.compile(r"ODOO\.PIVOT\(\s*(\d+)")


@tagged("post_install", "-at_install")
class TestHrDashboard(TransactionCase):
    """Guard the shipped HR Overview dashboard JSON.

    This is a data-only module: the field / pivot / formula references in the
    dashboard JSON are otherwise validated only at runtime, so these checks
    catch KPI mistakes (dead measures, wrong fields, duplicated scorecards)
    before they ship.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env.ref(
            "spreadsheet_dashboard_hr_oca.spreadsheet_dashboard_hr_overview"
        )
        raw = base64.b64decode(cls.dashboard.spreadsheet_binary_data)
        cls.data = json.loads(raw.decode("utf-8"))

    def _model_of(self, definition):
        """Return the recordset for the o-spreadsheet list/pivot model."""
        return self.env[definition["model"]]

    def test_binary_data_is_valid_json(self):
        """The stored dashboard payload must be parseable JSON."""
        self.assertIsInstance(self.data, dict)
        self.assertIn("sheets", self.data)
        self.assertIn("pivots", self.data)

    def test_referenced_fields_exist(self):
        """Every field used by lists / pivots / global filters must exist."""
        # Lists
        for list_def in self.data.get("lists", {}).values():
            model = self._model_of(list_def)
            for field in list_def.get("columns", []):
                if field in SPECIAL_FIELDS:
                    continue
                self.assertIn(
                    field,
                    model._fields,
                    f"list field '{field}' missing on {model._name}",
                )
        # Pivots
        for pivot_def in self.data.get("pivots", {}).values():
            model = self._model_of(pivot_def)
            fields = list(pivot_def.get("rowGroupBys", []))
            fields += list(pivot_def.get("colGroupBys", []))
            fields += [m["field"] for m in pivot_def.get("measures", [])]
            for field in fields:
                if field in SPECIAL_FIELDS:
                    continue
                self.assertIn(
                    field,
                    model._fields,
                    f"pivot field '{field}' missing on {model._name}",
                )
        # Global filters: pivotFields / listFields point at fields on the
        # owning pivot/list model.
        pivots = self.data.get("pivots", {})
        lists = self.data.get("lists", {})
        for gf in self.data.get("globalFilters", []):
            for pid, spec in gf.get("pivotFields", {}).items():
                model = self._model_of(pivots[pid])
                self.assertIn(
                    spec["field"],
                    model._fields,
                    f"filter field '{spec['field']}' missing on {model._name}",
                )
            for lid, spec in gf.get("listFields", {}).items():
                model = self._model_of(lists[lid])
                self.assertIn(
                    spec["field"],
                    model._fields,
                    f"filter field '{spec['field']}' missing on {model._name}",
                )

    def test_no_duplicate_pivot_measures(self):
        """A pivot must not declare the same measure (field+aggregator) twice."""
        for pid, pivot_def in self.data.get("pivots", {}).items():
            seen = set()
            for measure in pivot_def.get("measures", []):
                key = (measure["field"], measure.get("aggregator"))
                self.assertNotIn(
                    key,
                    seen,
                    f"pivot {pid} declares duplicate measure {key}",
                )
                seen.add(key)

    def _data_cell(self, ref):
        for sheet in self.data["sheets"]:
            if sheet["name"] == "Data":
                return sheet["cells"].get(ref, {}).get("content", "")
        return ""

    def test_total_and_new_use_distinct_pivots(self):
        """Total Employees (B2) and New Employees (B3) must not be the same
        formula, otherwise both scorecards render an identical number."""
        b2 = self._data_cell("B2")
        b3 = self._data_cell("B3")
        self.assertTrue(b2 and b3)
        self.assertNotEqual(
            b2, b3, "Total and New Employees scorecards share a formula"
        )
        pid_b2 = _PIVOT_ID_RE.search(b2)
        pid_b3 = _PIVOT_ID_RE.search(b3)
        self.assertTrue(pid_b2 and pid_b3)
        self.assertNotEqual(
            pid_b2.group(1),
            pid_b3.group(1),
            "Total and New Employees must resolve to different pivots",
        )
