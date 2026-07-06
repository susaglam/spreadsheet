# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class SpreadsheetDashboardRule(models.Model):
    _name = "spreadsheet.dashboard.rule"
    _description = "Dashboard Data Filter Rule"
    _order = "sequence, dashboard_id"

    name = fields.Char(
        required=True,
        help="Human label for this filter rule, e.g. 'Salesperson sees own orders'.",
    )
    sequence = fields.Integer(
        default=10,
        help="Evaluation and listing order; lower numbers are applied first.",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to archive this rule so it no longer filters "
        "dashboard data, without deleting it.",
    )
    dashboard_id = fields.Many2one(
        "spreadsheet.dashboard",
        required=True,
        ondelete="cascade",
        help="The dashboard whose pivot/list data sources this rule filters, "
        "e.g. the Sales dashboard.",
    )
    group_ids = fields.Many2many(
        "res.groups",
        string="Apply to Groups",
        help="Rule applies to users in these groups. Empty = all users.",
    )
    model_name = fields.Char(
        string="Model",
        required=True,
        help="Odoo model to apply filter to (e.g., sale.order).",
    )
    domain_extension = fields.Text(
        string="Additional Domain",
        required=True,
        default="[]",
        help="Additional domain applied to the model's data source. "
        "Can use 'user' variable (current user).",
    )

    @api.constrains("domain_extension")
    def _check_domain(self):
        for rec in self:
            try:
                # Validate with the real user in context so any `user.*`
                # reference (user.id, user.partner_id.id, ...) resolves.
                safe_eval(rec.domain_extension, {"user": self.env.user})
            except Exception as e:
                raise ValidationError(
                    self.env._(
                        "The Additional Domain is not a valid Odoo domain "
                        "(%(error)s). Enter a list of tuples such as "
                        "[('user_id', '=', user.id)]; you may reference the "
                        "current user via the `user` variable.",
                        error=str(e),
                    )
                ) from e

    def _get_applicable_rules(self, dashboard_id, model_name):
        """Return rules matching the current user's groups."""
        user = self.env.user
        rules = self.sudo().search(
            [
                ("dashboard_id", "=", dashboard_id),
                ("model_name", "=", model_name),
                ("active", "=", True),
            ]
        )
        applicable = self.browse()
        for rule in rules:
            if not rule.group_ids or user.all_group_ids & rule.group_ids:
                applicable |= rule
        return applicable

    def _build_combined_domain(self):
        """Evaluate and combine domain extensions from all applicable rules."""
        combined = []
        user = self.env.user
        for rule in self:
            try:
                domain = safe_eval(rule.domain_extension, {"user": user})
                if domain:
                    combined.extend(domain)
            except Exception as e:
                _logger.warning("Failed to evaluate rule '%s': %s", rule.name, e)
        return combined
