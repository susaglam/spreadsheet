# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Shared checks for the shipped purchase dashboards.

Imported by the tests of this module and of
spreadsheet_dashboard_purchase_stock_oca. The class holds helpers only (no
``test_*`` method), so importing it never runs a test twice.
"""

import json

from odoo.tests import TransactionCase
from odoo.tools.safe_eval import datetime as safe_datetime
from odoo.tools.safe_eval import safe_eval
from odoo.tools.view_validation import get_domain_value_names

PURCHASES_SECTION_XMLID = (
    "spreadsheet_dashboard_purchase_oca.spreadsheet_dashboard_group_purchase"
)
TEMPORAL_TYPES = ("date", "datetime")
EQ_OPERATORS = ("=", "!=", "in", "not in")


class DashboardDataCase(TransactionCase):
    """Validate a dashboard workbook against the real registry.

    Every model, field, field chain, menu and domain a pivot, list, chart or
    global filter uses must exist in saas-19.4, otherwise the end user gets
    ``#ERROR`` cells or an empty chart instead of numbers.
    """

    DASHBOARD_XMLID = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env.ref(cls.DASHBOARD_XMLID)
        cls.data = cls._load_dashboard_data(cls.dashboard)

    @classmethod
    def _load_dashboard_data(cls, dashboard):
        """Return the workbook as a dict.

        ``spreadsheet_raw`` only exists when spreadsheet_dashboard_oca is
        installed; the core ``spreadsheet_data`` text compute always does.
        Never base64-decode ``spreadsheet_binary_data``: in saas-19.4 it reads
        as a ``BinaryValue`` holding the raw JSON bytes.
        """
        if "spreadsheet_raw" in dashboard._fields:
            return dashboard.spreadsheet_raw
        return json.loads(dashboard.spreadsheet_data)

    # ------------------------------------------------------------------
    # Workbook walkers
    # ------------------------------------------------------------------

    def _odoo_charts(self):
        charts = {}
        for sheet in self.data.get("sheets", []):
            for figure in sheet.get("figures", []):
                chart = figure.get("data", {})
                if figure.get("tag") == "chart" and chart.get("type", "").startswith(
                    "odoo_"
                ):
                    charts[figure["id"]] = chart
        return charts

    def _data_sources(self):
        """Yield ``(label, model, definition)`` for every Odoo data source."""
        for pivot_id, pivot in self.data.get("pivots", {}).items():
            if pivot.get("type", "ODOO") == "ODOO":
                yield f"pivot {pivot_id}", pivot["model"], pivot
        for list_id, list_def in self.data.get("lists", {}).items():
            yield f"list {list_id}", list_def["model"], list_def
        for chart_id, chart in self._odoo_charts().items():
            yield f"chart {chart_id}", chart["metaData"]["resModel"], chart

    def _models_used(self):
        return {model for _label, model, _definition in self._data_sources()}

    @staticmethod
    def _field_name(spec):
        """``"date_order:month"`` / ``{"fieldName": ...}`` -> ``"date_order"``."""
        if isinstance(spec, dict):
            spec = spec.get("fieldName") or spec.get("name") or spec.get("field")
        return spec.split(":", 1)[0]

    @staticmethod
    def _groupby_spec(spec):
        """Pivot row/column -> ``read_group`` groupby (``date_order:month``)."""
        if isinstance(spec, str):
            return spec
        if spec.get("granularity"):
            return "{}:{}".format(spec["fieldName"], spec["granularity"])
        return spec["fieldName"]

    def _evaluated_domain(self, domain):
        if isinstance(domain, str):
            return safe_eval(domain, {"context_today": safe_datetime.date.today})
        return domain

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    def _assert_chain(self, model_name, chain, where):
        """Assert ``chain`` (``partner_id.country_id``) resolves on the model.

        Return the last field of the chain.
        """
        self.assertIn(model_name, self.env, f"{where}: unknown model {model_name!r}")
        model = self.env[model_name]
        field = None
        for fname in self._field_name(chain).split("."):
            self.assertIn(
                fname,
                model._fields,
                f"{where}: field {fname!r} does not exist on {model._name} "
                f"(chain {chain!r})",
            )
            field = model._fields[fname]
            if field.relational:
                model = self.env[field.comodel_name]
        return field

    def _assert_domain(self, model_name, domain, where):
        # str(): JSON leaves are lists, which the list branch cannot hash
        field_names, _values = get_domain_value_names(str(domain))
        for fname in field_names:
            self._assert_chain(model_name, fname, f"{where} domain")
        # the domain must be something the ORM accepts, not only valid names
        self.env[model_name].search_count(self._evaluated_domain(domain), limit=1)

    def _assert_selection_values(self, model_name, domain, where):
        """Each selection leaf must keep at least one existing value.

        A leaf like ``state in ['purchase', 'done']`` still works on 19.4
        ('done' simply never matches), but a leaf whose values are ALL gone
        would silently empty the whole data source.
        """
        model = self.env[model_name]
        for leaf in self._evaluated_domain(domain):
            if not isinstance(leaf, (list, tuple)) or len(leaf) != 3:
                continue
            fname, operator, value = leaf
            field = model._fields.get(fname)
            if not field or field.type != "selection" or operator not in EQ_OPERATORS:
                continue
            keys = set(field.get_values(self.env))
            values = set(value) if isinstance(value, (list, tuple)) else {value}
            self.assertTrue(
                values & keys,
                f"{where}: none of {sorted(values)} is a value of "
                f"{model_name}.{fname} (valid: {sorted(keys)})",
            )

    def _measure_aggregate(self, model_name, fname):
        field = self.env[model_name]._fields[fname]
        if field.type in ("many2one", "many2many", "one2many"):
            return f"{fname}:count_distinct"
        return f"{fname}:{field.aggregator or 'sum'}"

    def assert_workbook_matches_registry(self):
        """Check every data source, filter matching and menu of the workbook."""
        filters = {gf["id"]: gf for gf in self.data.get("globalFilters", [])}
        sources = list(self._data_sources())
        self.assertTrue(sources, "the dashboard has no Odoo data source")
        for label, model_name, definition in sources:
            self.assertIn(model_name, self.env, f"{label}: unknown model")
            if label.startswith("pivot"):
                measures = [
                    self._field_name(m)
                    for m in definition.get("measures", [])
                    if "computedBy" not in m
                ]
                groupbys = [
                    self._field_name(g)
                    for g in definition.get("rows", []) + definition.get("columns", [])
                ]
                sorted_column = definition.get("sortedColumn") or {}
                if sorted_column.get("measure"):
                    measures.append(self._field_name(sorted_column["measure"]))
                domain = definition.get("domain", [])
            elif label.startswith("list"):
                measures = []
                groupbys = [self._field_name(c) for c in definition.get("columns", [])]
                groupbys += [o["name"] for o in definition.get("orderBy", [])]
                domain = definition.get("domain", [])
            else:
                meta = definition["metaData"]
                measures = [meta["measure"]]
                groupbys = meta.get("groupBy", []) + definition["searchParams"].get(
                    "groupBy", []
                )
                domain = definition["searchParams"].get("domain", [])
            measures = [m for m in measures if m != "__count"]
            for fname in measures + groupbys:
                self._assert_chain(model_name, fname, label)
            self._assert_domain(model_name, domain, label)
            self._assert_selection_values(model_name, domain, label)
            for filter_id, matching in definition.get("fieldMatching", {}).items():
                where = f"{label} filter {filter_id}"
                self.assertIn(filter_id, filters, f"{where}: unknown global filter")
                chain = matching.get("chain")
                if not chain:
                    continue
                field = self._assert_chain(model_name, chain, where)
                global_filter = filters[filter_id]
                if global_filter["type"] == "relation":
                    self.assertEqual(
                        field.comodel_name,
                        global_filter["modelName"],
                        f"{where}: {chain!r} does not point to "
                        f"{global_filter['modelName']}",
                    )
                elif global_filter["type"] == "date":
                    self.assertIn(field.type, TEMPORAL_TYPES, where)
        for global_filter in filters.values():
            if global_filter["type"] == "relation":
                self.assertIn(global_filter["modelName"], self.env)
        for figure_id, xmlid in self.data.get("chartOdooMenusReferences", {}).items():
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            self.assertTrue(menu, f"figure {figure_id}: menu {xmlid} does not exist")
            self.assertEqual(menu._name, "ir.ui.menu")
            self.assertTrue(
                menu.action or not menu.parent_id,
                f"figure {figure_id}: menu {xmlid} has no action to open",
            )

    def assert_data_sources_load(self, user=None):
        """Run the read_group / search_read each data source triggers."""
        env = self.env(user=user) if user else self.env
        for label, model_name, definition in self._data_sources():
            model = env[model_name]
            if label.startswith("list"):
                order = ", ".join(
                    "{} {}".format(o["name"], "asc" if o.get("asc") else "desc")
                    for o in definition.get("orderBy", [])
                )
                model.search_read(
                    self._evaluated_domain(definition.get("domain", [])),
                    [self._field_name(c) for c in definition.get("columns", [])],
                    order=order or None,
                    limit=5,
                )
                continue
            if label.startswith("pivot"):
                measures = [
                    self._field_name(m)
                    for m in definition.get("measures", [])
                    if "computedBy" not in m
                ]
                groupby = [
                    self._groupby_spec(g)
                    for g in definition.get("rows", []) + definition.get("columns", [])
                ]
                domain = definition.get("domain", [])
            else:
                measures = [definition["metaData"]["measure"]]
                groupby = definition["metaData"].get("groupBy", [])
                domain = definition["searchParams"].get("domain", [])
            aggregates = [
                self._measure_aggregate(model_name, m)
                for m in measures
                if m != "__count"
            ] or ["__count"]
            model._read_group(
                self._evaluated_domain(domain), groupby=groupby, aggregates=aggregates
            )

    def assert_core_validator_accepts_workbook(self):
        # the saas-19.4 constraint checks fields and menus in test mode
        self.dashboard._check_spreadsheet_data()

    def assert_in_purchases_section(self, sequence):
        section = self.env.ref(PURCHASES_SECTION_XMLID)
        self.assertEqual(self.dashboard.dashboard_group_id, section)
        self.assertEqual(self.dashboard.sequence, sequence)
        self.assertTrue(self.dashboard.is_published)
