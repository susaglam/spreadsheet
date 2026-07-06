# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import copy

from odoo import fields, models
from odoo.fields import Domain


class SpreadsheetDashboard(models.Model):
    _inherit = "spreadsheet.dashboard"

    rule_ids = fields.One2many(
        "spreadsheet.dashboard.rule",
        "dashboard_id",
        string="Data Filter Rules",
    )

    def get_spreadsheet_data(self):
        """Inject user-specific domain filters based on applicable rules."""
        data = super().get_spreadsheet_data()
        if not self.rule_ids:
            return data

        # Mutate pivots/lists in spreadsheet_raw to apply per-user domain
        raw = copy.deepcopy(data.get("spreadsheet_raw") or {})
        Rule = self.env["spreadsheet.dashboard.rule"]

        for source_type in ("pivots", "lists"):
            for _source_id, source in raw.get(source_type, {}).items():
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
        """AND-combine two domains, normalizing operators correctly."""
        return list(Domain.AND([d1 or [], d2 or []]))
