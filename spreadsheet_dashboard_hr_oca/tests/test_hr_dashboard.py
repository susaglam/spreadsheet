# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import re

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import file_open

from odoo.addons.spreadsheet.utils.validate_data import (
    domain_fields,
    fields_in_spreadsheet,
    menus_xml_ids_in_spreadsheet,
    odoo_charts,
    odoo_view_links,
)

DASHBOARD_XMLID = "spreadsheet_dashboard_hr_oca.spreadsheet_dashboard_hr_overview"
DASHBOARD_FILE = "spreadsheet_dashboard_hr_oca/data/files/hr_dashboard.json"

# Pseudo measure understood by the pivot engine; it is not an ORM field.
COUNT_MEASURE = "__count"

_PIVOT_ID_RE = re.compile(r"ODOO\.PIVOT\(\s*(\d+)")
# =ODOO.PIVOT(10,"__count")  (migrated to PIVOT.VALUE at load time)
_PIVOT_VALUE_RE = re.compile(
    r'\b(?:ODOO\.PIVOT|PIVOT\.VALUE)\(\s*"?(\d+)"?\s*,\s*"([^"]+)"', re.IGNORECASE
)
# =ODOO.PIVOT.HEADER(1,"department_id",...)  -- the field argument is optional
_PIVOT_HEADER_RE = re.compile(
    r'\b(?:ODOO\.)?PIVOT\.HEADER\(\s*"?(\d+)"?\s*(?:,\s*"#?([^"]+)")?', re.IGNORECASE
)
# =ODOO.LIST(1,3,"name")
_LIST_VALUE_RE = re.compile(
    r'\bODOO\.LIST\(\s*"?(\d+)"?\s*,\s*[^,()]+,\s*"([^"]+)"', re.IGNORECASE
)
# =ODOO.LIST.HEADER(1,"name")
_LIST_HEADER_RE = re.compile(
    r'\bODOO\.LIST\.HEADER\(\s*"?(\d+)"?\s*,\s*"([^"]+)"', re.IGNORECASE
)


@tagged("post_install", "-at_install")
class TestHrDashboard(TransactionCase):
    """Guard the shipped HR Overview dashboard JSON against the real ORM.

    This is a data-only module: the model / field / pivot / formula references
    in the dashboard JSON are otherwise only validated when a user opens the
    dashboard, where a wrong reference renders ``#ERROR``. These checks catch
    dead measures, renamed fields and duplicated scorecards before they ship.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env.ref(DASHBOARD_XMLID)
        cls.data = cls._load_dashboard_data(cls.dashboard)

    @classmethod
    def _load_dashboard_data(cls, dashboard):
        """Return the dashboard spreadsheet as a dict.

        Never base64-decode ``spreadsheet_binary_data``: in saas-19.4 reading
        a Binary field returns a ``BinaryValue`` wrapper whose content is
        already the raw JSON bytes, so decoding it again raises (or yields
        garbage). ``spreadsheet_raw`` is the decoded dict form, but it is only
        added by ``spreadsheet_dashboard_oca``, which this module does not
        depend on -- fall back to the core ``spreadsheet_data`` text compute.
        """
        if "spreadsheet_raw" in dashboard._fields:
            return dashboard.spreadsheet_raw
        return json.loads(dashboard.spreadsheet_data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _assert_field_chain(self, model_name, chain, where):
        """Assert that ``model_name`` exists and ``chain`` resolves on it.

        ``chain`` may carry a granularity or aggregator suffix
        (``create_date:month``, ``amount:sum``) and may traverse relations
        (``department_id.company_id``).
        """
        self.assertIn(
            model_name,
            self.env,
            f"{where}: model {model_name!r} does not exist",
        )
        model = self.env[model_name]
        chain = chain.split(":", 1)[0]
        for fname in chain.split("."):
            self.assertIn(
                fname,
                model._fields,
                f"{where}: field {fname!r} does not exist on {model._name} "
                f"(chain {chain!r})",
            )
            field = model._fields[fname]
            if field.relational:
                model = self.env[field.comodel_name]

    @staticmethod
    def _pivot_measure_ids(pivot):
        """Measure identifiers a pivot formula can reference.

        Old-format measures (``{"field": ..., "aggregator": ...}``) are
        migrated to ``{"id": field, ...}`` when the spreadsheet loads, newer
        ones already carry their ``id``.
        """
        ids = set()
        for measure in pivot.get("measures", []):
            if isinstance(measure, str):
                ids.add(measure)
                continue
            measure_id = (
                measure.get("id")
                or measure.get("field")
                or measure.get("fieldName")
                or measure.get("name")
            )
            if measure_id:
                ids.add(measure_id)
        return ids

    @staticmethod
    def _pivot_measure_fields(pivot):
        fields = []
        for measure in pivot.get("measures", []):
            if isinstance(measure, str):
                fields.append(measure)
            elif not measure.get("computedBy"):
                fields.append(
                    measure.get("fieldName")
                    or measure.get("field")
                    or measure.get("name")
                )
        return [f for f in fields if f and f != COUNT_MEASURE]

    @staticmethod
    def _pivot_group_bys(pivot):
        group_bys = list(pivot.get("rowGroupBys", []))
        group_bys += pivot.get("colGroupBys", [])
        for dimension in pivot.get("rows", []) + pivot.get("columns", []):
            group_bys.append(dimension.get("fieldName") or dimension.get("name"))
        return [g for g in group_bys if g]

    def _formula_cells(self):
        for sheet in self.data.get("sheets", []):
            for ref, cell in sheet.get("cells", {}).items():
                content = cell if isinstance(cell, str) else cell.get("content", "")
                if content.startswith("="):
                    yield f"{sheet['name']}!{ref}", content

    @staticmethod
    def _matching_refs(model, source, label):
        """Filter matchings stored on the data source (odooVersion >= 5)."""
        for filter_id, match in source.get("fieldMatching", {}).items():
            if match.get("chain"):
                yield model, match["chain"], f"{label} filter {filter_id}"

    def _list_refs(self, lists):
        for list_id, list_def in lists.items():
            model = list_def["model"]
            label = f"list {list_id}"
            for column in list_def.get("columns", []):
                name = column.get("name") if isinstance(column, dict) else column
                yield model, name, f"{label} column"
            for order in list_def.get("orderBy", []):
                yield model, order["name"], f"{label} orderBy"
            for fname in domain_fields(list_def.get("domain", [])):
                yield model, fname, f"{label} domain"
            yield from self._matching_refs(model, list_def, label)

    def _pivot_refs(self, pivots):
        for pivot_id, pivot in pivots.items():
            if pivot.get("type", "ODOO") != "ODOO":
                continue
            model = pivot["model"]
            label = f"pivot {pivot_id}"
            for fname in self._pivot_group_bys(pivot):
                yield model, fname, f"{label} groupBy"
            for fname in self._pivot_measure_fields(pivot):
                yield model, fname, f"{label} measure"
            for fname in domain_fields(pivot.get("domain", [])):
                yield model, fname, f"{label} domain"
            yield from self._matching_refs(model, pivot, label)

    def _chart_refs(self, charts):
        for chart_id, chart in charts.items():
            meta = chart["metaData"]
            model = meta["resModel"]
            label = f"chart {chart_id}"
            search = chart.get("searchParams", {})
            for fname in list(meta.get("groupBy", [])) + search.get("groupBy", []):
                yield model, fname, f"{label} groupBy"
            if meta.get("measure") and meta["measure"] != COUNT_MEASURE:
                yield model, meta["measure"], f"{label} measure"
            for fname in domain_fields(search.get("domain", [])):
                yield model, fname, f"{label} domain"
            yield from self._matching_refs(model, chart, label)

    def _view_link_refs(self):
        for view in odoo_view_links(self.data):
            action = view["action"]
            model = action["modelName"]
            self.assertIn(model, self.env, f"view link targets unknown model {model!r}")
            for fname in domain_fields(action.get("domain", [])):
                yield model, fname, "view link domain"

    def _legacy_filter_refs(self, pivots, lists, charts):
        """Filter matchings stored on the filter itself (odooVersion < 5)."""
        models = {
            "pivotFields": {pid: p["model"] for pid, p in pivots.items()},
            "listFields": {lid: lst["model"] for lid, lst in lists.items()},
            "graphFields": {
                cid: c["metaData"]["resModel"] for cid, c in charts.items()
            },
        }
        for gf in self.data.get("globalFilters", []):
            for key, model_by_id in models.items():
                for obj_id, match in gf.get(key, {}).items():
                    # Undeclared ids: see test_global_filters_target_existing_sources
                    if obj_id in model_by_id:
                        where = f"filter {gf['id']} {key}"
                        yield model_by_id[obj_id], match["field"], where

    def _formula_refs(self, pivots, lists):
        """ODOO.LIST(id, row, "field"), ODOO.LIST.HEADER(id, "field") and
        ODOO.PIVOT.HEADER(id, "field", value) read fields directly."""
        for where, content in self._formula_cells():
            for regex in (_LIST_VALUE_RE, _LIST_HEADER_RE):
                for list_id, fname in regex.findall(content):
                    if list_id in lists:
                        yield lists[list_id]["model"], fname, where
            for pivot_id, fname in _PIVOT_HEADER_RE.findall(content):
                if fname and fname != "measure" and pivot_id in pivots:
                    yield pivots[pivot_id]["model"], fname, where

    def _field_references(self):
        """Collect every (model, field chain, location) used by the JSON."""
        pivots = self.data.get("pivots", {})
        lists = self.data.get("lists", {})
        charts = {chart["id"]: chart for chart in odoo_charts(self.data)}
        refs = list(self._list_refs(lists))
        refs += self._pivot_refs(pivots)
        refs += self._chart_refs(charts)
        refs += self._view_link_refs()
        refs += self._legacy_filter_refs(pivots, lists, charts)
        refs += self._formula_refs(pivots, lists)
        return refs

    def _data_cell(self, ref):
        for sheet in self.data["sheets"]:
            if sheet["name"] == "Data":
                cell = sheet["cells"].get(ref, {})
                return cell if isinstance(cell, str) else cell.get("content", "")
        return ""

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_payload_is_valid_json(self):
        """The stored dashboard payload must decode to a spreadsheet dict."""
        self.assertIsInstance(self.data, dict)
        for key in ("sheets", "pivots", "lists", "globalFilters"):
            self.assertIn(key, self.data)
        self.assertTrue(self.data["sheets"], "The dashboard has no sheet")

    def test_stored_binary_matches_shipped_file(self):
        """The Binary field content is the raw JSON of the shipped file.

        Guards the saas-19.4 Binary contract: the field reads back as a
        wrapper over the already-decoded bytes, so the content must parse as
        JSON as-is (no base64 layer) and be identical to the data file.
        """
        value = self.dashboard.spreadsheet_binary_data
        self.assertTrue(value, "The dashboard has no spreadsheet payload")
        stored = json.loads(bytes(value))
        with file_open(DASHBOARD_FILE, "rb") as fobj:
            shipped = json.load(fobj)
        self.assertEqual(stored, shipped)
        self.assertEqual(self.data, shipped)

    def test_referenced_models_and_fields_exist(self):
        """Every model / field referenced anywhere in the JSON must exist."""
        refs = self._field_references()
        self.assertTrue(refs, "No field reference found: the collector is broken")
        for model, chain, where in refs:
            with self.subTest(model=model, field=chain, where=where):
                self._assert_field_chain(model, chain, where)

    def test_core_validator_references_exist(self):
        """Same check through saas-19.4's own spreadsheet validator.

        Keeps this test aligned with ``spreadsheet.mixin``'s data constraint
        if core starts extracting references this test does not know about.
        """
        for model, chains in fields_in_spreadsheet(self.data).items():
            for chain in chains:
                with self.subTest(model=model, field=chain):
                    self._assert_field_chain(model, chain, "core validator")

    def test_menu_xmlids_exist(self):
        """Chart menu references and odoo://ir_menu_xml_id links must resolve."""
        for xmlid in menus_xml_ids_in_spreadsheet(self.data):
            with self.subTest(xmlid=xmlid):
                self.assertTrue(
                    self.env.ref(xmlid, raise_if_not_found=False),
                    f"menu xml id {xmlid!r} does not exist",
                )

    def test_global_filters_target_existing_sources(self):
        """Filters must point at declared pivots / lists / charts and models."""
        sources = {
            "pivotFields": self.data.get("pivots", {}),
            "listFields": self.data.get("lists", {}),
            "graphFields": {chart["id"]: chart for chart in odoo_charts(self.data)},
        }
        for gf in self.data.get("globalFilters", []):
            for key, declared in sources.items():
                for obj_id in gf.get(key, {}):
                    self.assertIn(
                        obj_id,
                        declared,
                        f"filter {gf['id']} {key} targets undeclared id {obj_id!r}",
                    )
            if gf.get("type") == "relation":
                self.assertIn(
                    gf["modelName"],
                    self.env,
                    f"filter {gf['id']} targets unknown model {gf['modelName']!r}",
                )

    def test_formulas_reference_declared_sources(self):
        """ODOO.PIVOT / ODOO.LIST formulas must use declared ids and measures.

        A measure that is not declared on the pivot renders
        "Field ... is not a measure" in the scorecard at runtime.
        """
        pivots = self.data.get("pivots", {})
        lists = self.data.get("lists", {})
        checked = 0
        for where, content in self._formula_cells():
            for pivot_id, measure in _PIVOT_VALUE_RE.findall(content):
                checked += 1
                self.assertIn(pivot_id, pivots, f"{where}: unknown pivot {pivot_id}")
                self.assertIn(
                    measure,
                    self._pivot_measure_ids(pivots[pivot_id]),
                    f"{where}: measure {measure!r} is not declared on pivot {pivot_id}",
                )
            for pivot_id, _fname in _PIVOT_HEADER_RE.findall(content):
                checked += 1
                self.assertIn(pivot_id, pivots, f"{where}: unknown pivot {pivot_id}")
            for regex in (_LIST_VALUE_RE, _LIST_HEADER_RE):
                for list_id, _fname in regex.findall(content):
                    checked += 1
                    self.assertIn(list_id, lists, f"{where}: unknown list {list_id}")
        self.assertTrue(checked, "No ODOO.PIVOT / ODOO.LIST formula found")

    def test_no_duplicate_pivot_measures(self):
        """A pivot must not declare the same measure (field+aggregator) twice."""
        for pid, pivot_def in self.data.get("pivots", {}).items():
            seen = set()
            for measure in pivot_def.get("measures", []):
                if isinstance(measure, str):
                    key = (measure, None)
                else:
                    key = (
                        measure.get("fieldName")
                        or measure.get("field")
                        or measure.get("name"),
                        measure.get("aggregator"),
                    )
                self.assertNotIn(
                    key,
                    seen,
                    f"pivot {pid} declares duplicate measure {key}",
                )
                seen.add(key)

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
