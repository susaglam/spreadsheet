# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import ast
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools.safe_eval import expr_eval

_logger = logging.getLogger(__name__)

#: The only names an Additional Domain may reference. They are PLAIN values
#: (ints, lists of ints/strings) on purpose: a recordset, ``env`` or model in
#: the evaluation context exposes methods such as ``sudo()`` / ``write()``,
#: and ``env.user`` is already a superuser record in saas-19.4, so a rule
#: author could run writes as superuser on every dashboard view.
EVAL_CONTEXT_NAMES = (
    "user_id",
    "partner_id",
    "company_id",
    "company_ids",
    "group_xmlids",
)


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
        help="The dashboard whose pivot, list and chart data sources this rule "
        "filters, e.g. the Sales dashboard.",
    )
    group_ids = fields.Many2many(
        "res.groups",
        string="Apply to Groups",
        help="The rule only applies to users who belong to at least one of these "
        "groups (directly or through an implied group). Leave empty to apply "
        "it to every user who opens the dashboard.",
    )
    model_name = fields.Char(
        string="Model",
        required=True,
        help="Technical name of the Odoo model whose dashboard data sources this "
        "rule filters, e.g. sale.order. It must match the model used by the "
        "pivot, list or chart on the dashboard.",
    )
    domain_extension = fields.Text(
        string="Additional Domain",
        required=True,
        default="[]",
        help="Extra conditions AND-ed to the domain of every pivot, list and "
        "chart of this model on the dashboard, for the users this rule applies "
        "to. Only these plain-value variables are available: user_id, "
        "partner_id, company_id (active company), company_ids (active "
        "companies) and group_xmlids (external IDs of the user's groups). "
        "Example: [('user_id', '=', user_id)]. Important: this narrows what "
        "the dashboard displays, it is NOT a security boundary. The filter is "
        "sent to the browser, where a technical user could remove it, although "
        "nobody ever sees more than their normal Odoo access rights allow. Use "
        "access rights (Settings > Technical > Security > Access Rights) to "
        "truly restrict data. "
        "If the domain cannot be evaluated the rule fails closed: its data "
        "sources show no records.",
    )
    evaluation_error = fields.Text(
        string="Evaluation Problem",
        compute="_compute_evaluation_error",
        help="Explains why this rule cannot currently be evaluated, checked with "
        "your own user values (a user in another company may still hit a "
        "different problem). While a problem is shown the rule fails closed: "
        "the users it applies to see no records of its model on the dashboard. "
        "Empty means the rule evaluates correctly.",
    )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    @api.model
    def _get_eval_context(self):
        """Plain values describing the current user, for domain evaluation.

        Never put a recordset, ``env`` or model in here (see
        ``EVAL_CONTEXT_NAMES``). Semantics follow core access rules:
        ``company_id`` / ``company_ids`` are the active company / companies.
        """
        user = self.env.user
        group_xmlids = sorted(
            {
                xmlid
                for xmlids in user.all_group_ids._get_external_ids().values()
                for xmlid in xmlids
            }
        )
        return {
            "user_id": user.id,
            "partner_id": user.partner_id.id,
            "company_id": self.env.company.id,
            "company_ids": list(self.env.companies.ids),
            "group_xmlids": group_xmlids,
        }

    def _evaluate_domain(self, eval_context):
        """Evaluate this rule's Additional Domain into a ``Domain``.

        ``expr_eval`` only supports literals, names from ``eval_context``,
        comparisons, boolean logic and a handful of pure builtins (min, max,
        int, ...). Attribute access only works on recordsets, and the context
        holds none, so no ORM method can ever be reached.

        :raises Exception: on any syntax, name, type or domain-shape problem
        """
        self.ensure_one()
        value = expr_eval(self.domain_extension or "[]", dict(eval_context))
        if not isinstance(value, list | tuple):
            raise TypeError(
                f"expected a list of conditions, got {type(value).__name__}"
            )
        return Domain(list(value))

    def _get_domain_problem(self, eval_context):
        """Return a translated explanation of why this rule is unusable.

        :return: the explanation (str), or ``False`` when the rule evaluates
            and validates against its model
        """
        self.ensure_one()
        model_name = self.model_name or ""
        if not model_name or model_name not in self.env:
            return self.env._(
                "The model '%(model)s' does not exist in this database, so this "
                "rule can never match a dashboard data source. Enter the "
                "technical model name used by the pivot, list or chart, for "
                "example sale.order (see Settings > Technical > Database "
                "Structure > Models).",
                model=model_name,
            )
        if self._uses_legacy_user_variable():
            return self.env._(
                "The Additional Domain uses the 'user' variable, which is no "
                "longer available: it exposed the full user record, whose "
                "methods could change data with administrator rights. Use the "
                "plain values instead: user_id, partner_id, company_id, "
                "company_ids or group_xmlids. For example, replace user.id "
                "with user_id."
            )
        try:
            domain = self._evaluate_domain(eval_context)
            domain.validate(self.env[model_name].sudo())
        except NameError as error:
            name = error.args[0] if error.args else ""
            if isinstance(name, str) and name.isidentifier():
                return self.env._(
                    "The Additional Domain uses '%(name)s', which is not an "
                    "available variable. Only user_id, partner_id, company_id, "
                    "company_ids and group_xmlids can be used; anything else must "
                    "be a literal value such as 'draft', 42 or True.",
                    name=name,
                )
            return self._format_invalid_domain(model_name, error)
        except Exception as error:  # noqa: BLE001 - any failure is reported
            return self._format_invalid_domain(model_name, error)
        return False

    def _uses_legacy_user_variable(self):
        """Whether the domain references the removed ``user`` variable.

        Checked on the syntax tree (nothing is evaluated) so that expressions
        such as ``user.sudo().write(...)`` get the explicit migration hint.
        """
        self.ensure_one()
        try:
            tree = ast.parse((self.domain_extension or "").strip(), mode="eval")
        except (SyntaxError, ValueError, RecursionError):
            return False
        return any(
            isinstance(node, ast.Name) and node.id == "user" for node in ast.walk(tree)
        )

    def _format_invalid_domain(self, model_name, error):
        return self.env._(
            "The Additional Domain is not a valid domain for the model "
            "'%(model)s' (%(error)s). Enter a list of conditions such as "
            "[('user_id', '=', user_id)], using only the variables user_id, "
            "partner_id, company_id, company_ids and group_xmlids.",
            model=model_name,
            error=str(error),
        )

    def _get_fail_closed_hint(self):
        self.ensure_one()
        return self.env._(
            "A rule that cannot be evaluated fails closed: until it is fixed, "
            "the users it applies to see no '%(model)s' records on this "
            "dashboard.",
            model=self.model_name or "",
        )

    @api.depends("domain_extension", "model_name")
    @api.depends_context("uid", "allowed_company_ids")
    def _compute_evaluation_error(self):
        try:
            eval_context = self._get_eval_context()
        except Exception as error:  # noqa: BLE001 - shown to the manager
            eval_context = None
            context_error = str(error)
        for rule in self:
            if eval_context is None:
                problem = rule._format_invalid_domain(
                    rule.model_name or "", context_error
                )
            else:
                problem = rule._get_domain_problem(eval_context)
            rule.evaluation_error = (
                "\n\n".join((problem, rule._get_fail_closed_hint()))
                if problem
                else False
            )

    @api.constrains("domain_extension", "model_name")
    def _check_domain(self):
        eval_context = self._get_eval_context()
        for rec in self:
            problem = rec._get_domain_problem(eval_context)
            if problem:
                raise ValidationError(
                    "\n\n".join((problem, rec._get_fail_closed_hint()))
                )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    def _get_applicable_rules(self, dashboard_id, model_name):
        """Return the active rules of a dashboard/model for the current user.

        The result is a SUDO recordset: dashboard viewers usually have no
        read access on this configuration model, yet their rules must apply.
        """
        user = self.env.user
        rules = self.sudo().search(
            [
                ("dashboard_id", "=", dashboard_id),
                ("model_name", "=", model_name),
                ("active", "=", True),
            ]
        )
        user_groups = user.all_group_ids
        return rules.filtered(
            lambda rule: not rule.group_ids or bool(user_groups & rule.group_ids)
        )

    def _build_combined_domain(self):
        """AND-combine the Additional Domains of the rules in ``self``.

        Fails CLOSED: when the evaluation context or any single rule cannot
        be evaluated, the always-false domain is returned so the data source
        shows nothing instead of everything.

        :return: a domain list; ``[]`` when the rules do not narrow anything
        """
        if not self:
            return []
        try:
            # Values of the REAL user, with the company checks of a non-sudo env.
            eval_context = self.sudo(False)._get_eval_context()
        except Exception:  # noqa: BLE001 - fail closed, never crash the view
            _logger.warning(
                "Dashboard data filter rules %s: the evaluation values for user "
                "id %s could not be computed. Failing closed: the matching data "
                "sources show no records.",
                self.ids,
                self.env.uid,
                exc_info=True,
            )
            return list(Domain.FALSE)
        domains = []
        for rule in self.sudo():
            try:
                domains.append(rule._evaluate_domain(eval_context))
            except Exception as error:  # noqa: BLE001 - fail closed
                _logger.warning(
                    "Dashboard data filter rule %r (id %s, dashboard id %s, model "
                    "%s) could not be evaluated for user id %s: %s. Failing "
                    "closed: the matching data sources show no records until an "
                    "administrator fixes the rule (see its Evaluation Problem).",
                    rule.name,
                    rule.id,
                    rule.dashboard_id.id,
                    rule.model_name,
                    self.env.uid,
                    error,
                )
                return list(Domain.FALSE)
        combined = Domain.AND(domains)
        return [] if combined.is_true() else list(combined)
