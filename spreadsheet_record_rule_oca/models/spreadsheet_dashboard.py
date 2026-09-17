# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import ast
import copy
import json
import logging

from odoo import fields, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class SpreadsheetDashboard(models.Model):
    _inherit = "spreadsheet.dashboard"

    rule_ids = fields.One2many(
        "spreadsheet.dashboard.rule",
        "dashboard_id",
        string="Data Filter Rules",
        help="Data filter rules that narrow the pivot, list and chart data this "
        "dashboard displays for specific groups of users. They are a display "
        "convenience, not a security boundary: users never see more than their "
        "normal access rights allow.",
    )

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------
    def _get_serialized_readonly_dashboard(self):
        """Core Dashboards app path (``/spreadsheet/dashboard/data/<id>``).

        This is how every user normally views a dashboard, so the rules must
        be applied here, not only in the OCA editor loader below.
        """
        body = super()._get_serialized_readonly_dashboard()
        if not self._has_dashboard_rules():
            return body
        payload = json.loads(body)
        payload["snapshot"] = self._apply_dashboard_rules(payload.get("snapshot"))
        # Default ensure_ascii=True keeps len(body) == byte length, which the
        # core controller uses as Content-Length.
        return json.dumps(payload)

    def get_spreadsheet_data(self):
        """OCA loader (OCA viewer/editor, portal dashboards, API)."""
        data = super().get_spreadsheet_data()
        if not self._has_dashboard_rules():
            return data
        if self._is_dashboard_design_editor():
            # The OCA editor saves the whole exported model back into
            # ``spreadsheet_raw`` when the user leaves it. Injecting a per-user
            # filter here would bake that user's filter into the dashboard
            # design for everybody, so editors get the design as stored.
            return data
        data["spreadsheet_raw"] = self._apply_dashboard_rules(
            data.get("spreadsheet_raw")
        )
        return data

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _has_dashboard_rules(self):
        self.ensure_one()
        return bool(
            self.env["spreadsheet.dashboard.rule"]
            .sudo()
            .search_count([("dashboard_id", "=", self.id)], limit=1)
        )

    def _is_dashboard_design_editor(self):
        """Whether the real (non-sudo) user may save this dashboard's design.

        Sudo callers acting for someone else (e.g. portal dashboards) are not
        editors: ``sudo(False)`` restores the real user's access checks.
        """
        self.ensure_one()
        return self.sudo(False).has_access("write")

    def _apply_dashboard_rules(self, snapshot):
        """Return a copy of ``snapshot`` with the current user's rules applied.

        Every Odoo data source (pivot, list, chart, carousel chart) whose model
        has applicable rules gets the rules' domain AND-ed to its own domain.
        """
        self.ensure_one()
        if not isinstance(snapshot, dict) or not self._has_dashboard_rules():
            return snapshot
        snapshot = copy.deepcopy(snapshot)
        Rule = self.env["spreadsheet.dashboard.rule"]
        extra_by_model = {}
        for holder, model in self._iter_rule_data_sources(snapshot):
            if model not in extra_by_model:
                rules = Rule._get_applicable_rules(self.id, model)
                extra_by_model[model] = rules._build_combined_domain()
            extra = extra_by_model[model]
            if extra:
                holder["domain"] = self._merge_domains(holder.get("domain"), extra)
        return snapshot

    @classmethod
    def _iter_rule_data_sources(cls, snapshot):
        """Yield ``(dict_holding_the_domain, model_name)`` per Odoo data source."""
        for key in ("pivots", "lists"):
            sources = snapshot.get(key)
            if not isinstance(sources, dict):
                continue
            for source in sources.values():
                if not isinstance(source, dict):
                    continue
                # Spreadsheet-native pivots (type "SPREADSHEET") have no model.
                if key == "pivots" and source.get("type", "ODOO") != "ODOO":
                    continue
                model = source.get("model")
                if isinstance(model, str) and model:
                    yield source, model
        for definition in cls._iter_chart_definitions(snapshot):
            found = cls._get_chart_rule_source(definition)
            if found:
                yield found

    @staticmethod
    def _iter_chart_definitions(snapshot):
        """Yield every chart definition: figure charts and carousel charts."""
        sheets = snapshot.get("sheets")
        for sheet in sheets if isinstance(sheets, list) else []:
            figures = sheet.get("figures") if isinstance(sheet, dict) else None
            for figure in figures if isinstance(figures, list) else []:
                data = figure.get("data") if isinstance(figure, dict) else None
                if not isinstance(data, dict):
                    continue
                if figure.get("tag") == "chart":
                    yield data
                elif figure.get("tag") == "carousel":
                    chart_defs = data.get("chartDefinitions")
                    if isinstance(chart_defs, dict):
                        yield from chart_defs.values()

    @staticmethod
    def _get_chart_rule_source(definition):
        """Return ``(search_params, model)`` for an Odoo chart, else ``None``."""
        if not isinstance(definition, dict):
            return None
        data_source = definition.get("dataSource")
        if isinstance(data_source, dict) and data_source.get("type") == "odoo":
            source = data_source  # saas-19.4 layout
        elif str(definition.get("type", "")).startswith("odoo_"):
            source = definition  # older layout: metaData/searchParams at top
        else:
            return None
        meta = source.get("metaData")
        params = source.get("searchParams")
        if not isinstance(meta, dict) or not isinstance(params, dict):
            return None
        model = meta.get("resModel")
        return (params, model) if isinstance(model, str) and model else None

    @staticmethod
    def _merge_domains(d1, d2):
        """AND-combine a data source's own domain ``d1`` with the rule domain.

        ``d1`` comes from the spreadsheet JSON: usually a list, but a string
        when it holds contextual expressions (``context_today()``, ...). If it
        cannot be combined safely the always-false domain is returned (fail
        closed) rather than dropping the rule domain.
        """
        if not d2:
            return d1 if d1 is not None else []
        if isinstance(d1, str):
            try:
                return SpreadsheetDashboard._merge_domain_string(d1, d2)
            except (SyntaxError, ValueError, RecursionError) as error:
                _logger.warning(
                    "Dashboard data filter: cannot combine data source domain %r "
                    "with rule domain %r (%s). Failing closed.",
                    d1,
                    d2,
                    error,
                )
                return list(Domain.FALSE)
        try:
            return list(Domain.AND([Domain(d1 or []), Domain(d2)]))
        except (TypeError, ValueError) as error:
            _logger.warning(
                "Dashboard data filter: cannot combine data source domain %r with "
                "rule domain %r (%s). Failing closed.",
                d1,
                d2,
                error,
            )
            return list(Domain.FALSE)

    @staticmethod
    def _merge_domain_string(source, extra):
        """Append the rule leaves to a Python-syntax domain string.

        Concatenating two prefix-notation domains is their implicit AND, so the
        rule leaves are appended as literals to the top-level list, keeping the
        author's contextual expressions untouched for the browser to evaluate.
        """
        source = source.strip()
        tree = ast.parse(source, mode="eval")
        if not isinstance(tree.body, ast.List):
            raise ValueError("the domain string is not a list literal")
        items = [ast.get_source_segment(source, elt) for elt in tree.body.elts]
        if any(item is None for item in items):
            raise ValueError("the domain string could not be split into items")
        items.extend(repr(item) for item in extra)
        return "[{}]".format(", ".join(items))
