# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import copy

from odoo import fields, models


class SpreadsheetDashboard(models.Model):
    _inherit = "spreadsheet.dashboard"

    rule_ids = fields.One2many(
        "spreadsheet.dashboard.rule",
        "dashboard_id",
        string="Data Filter Rules",
    )
    rule_count = fields.Integer(compute="_compute_rule_count")

    def _compute_rule_count(self):
        for rec in self:
            rec.rule_count = len(rec.rule_ids)

    def get_spreadsheet_data(self):
        """Inject user-specific domain filters based on applicable rules."""
        data = super().get_spreadsheet_data()
        if not self.rule_ids:
            return data

        # Mutate pivots/lists in spreadsheet_raw to apply per-user domain
        raw = copy.deepcopy(data.get("spreadsheet_raw") or {})
        Rule = self.env["spreadsheet.dashboard.rule"]

        for source_type in ("pivots", "lists"):
            for source_id, source in raw.get(source_type, {}).items():
                model = source.get("model")
                if not model:
                    continue
                rules = Rule._get_applicable_rules(self.id, model)
                if rules:
                    extra = rules._build_combined_domain()
                    existing = source.get("domain", [])
                    source["domain"] = self._merge_domains(existing, extra)

        data["spreadsheet_raw"] = raw
        return data

    @staticmethod
    def _merge_domains(d1, d2):
        """AND-combine two domains."""
        if not d1:
            return d2
        if not d2:
            return d1
        # Wrap with '&' for each additional term from d2
        result = list(d1)
        for term in d2:
            result = ["&"] + result + [term]
        return result
