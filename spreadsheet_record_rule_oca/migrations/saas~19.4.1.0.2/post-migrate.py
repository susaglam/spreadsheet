# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Move existing rules off the removed ``user`` recordset variable.

Before this version an Additional Domain was evaluated with ``{"user":
<res.users>}``, which let a rule author call ORM methods (``sudo()``,
``write()``...) as superuser. Domains are now evaluated with plain values only
(user_id, partner_id, company_id, company_ids, group_xmlids).

This script rewrites the common, exactly-equivalent expressions in place and
logs every rule that still cannot be evaluated. Such rules are NOT archived:
an unusable rule fails closed (its data sources show no records), whereas
archiving it would silently show everything. The script never raises, so it
can never block an upgrade.
"""

import ast
import logging

from odoo.api import SUPERUSER_ID, Environment

_logger = logging.getLogger(__name__)

#: legacy attribute chain -> plain-value variable
REWRITES = {
    ("user", "id"): "user_id",
    ("user", "partner_id", "id"): "partner_id",
    ("user", "company_id", "id"): "company_id",
    ("user", "company_ids", "ids"): "company_ids",
}


def _attribute_chain(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return tuple(reversed(parts))


def rewrite_expression(source):
    """Return ``source`` with the known ``user.*`` chains replaced.

    Works on the syntax tree, so text inside string literals is never touched.
    AST column offsets are UTF-8 byte offsets, hence the byte arithmetic.

    :raises SyntaxError: when ``source`` is not a Python expression
    """
    source = source.strip()
    tree = ast.parse(source, mode="eval")
    raw = source.encode("utf-8")
    line_starts = [0]
    for line in raw.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        replacement = REWRITES.get(_attribute_chain(node))
        if replacement:
            start = line_starts[node.lineno - 1] + node.col_offset
            end = line_starts[node.end_lineno - 1] + node.end_col_offset
            spans.append((start, end, replacement))
    chunks = []
    position = 0
    for start, end, replacement in sorted(spans):
        if start < position:  # nested inside an already replaced chain
            continue
        chunks.append(raw[position:start])
        chunks.append(replacement.encode("utf-8"))
        position = end
    chunks.append(raw[position:])
    return b"".join(chunks).decode("utf-8")


def _migrate_rule(env, rule, eval_context):
    original = rule.domain_extension or "[]"
    try:
        rewritten = rewrite_expression(original)
    except SyntaxError:
        rewritten = None
    if rewritten is not None and rewritten != original.strip():
        # Plain SQL on purpose: the rewrite is a mechanical 1:1 translation,
        # and it must not be rejected by a constraint evaluated with the
        # superuser's values (e.g. an index into a single-company list).
        env.cr.execute(
            "UPDATE spreadsheet_dashboard_rule SET domain_extension = %s WHERE id = %s",
            (rewritten, rule.id),
        )
        rule.invalidate_recordset(["domain_extension"])
        _logger.info(
            "Dashboard data filter rule %r (id %s): Additional Domain rewritten "
            "from %r to %r (plain-value variables).",
            rule.name,
            rule.id,
            original,
            rewritten,
        )
    problem = rule._get_domain_problem(eval_context)
    if problem:
        _logger.warning(
            "Dashboard data filter rule %r (id %s, dashboard id %s) still cannot "
            "be evaluated after the upgrade: %s Its domain is %r. The rule now "
            "fails closed (its data sources show no records to the users it "
            "applies to) until an administrator rewrites it under Spreadsheets > "
            "Configuration > Dashboard Data Filters.",
            rule.name,
            rule.id,
            rule.dashboard_id.id,
            problem,
            rule.domain_extension,
        )


def migrate(cr, version):
    if not version:
        return
    try:
        env = Environment(cr, SUPERUSER_ID, {})
        if "spreadsheet.dashboard.rule" not in env:
            return
        Rule = env["spreadsheet.dashboard.rule"].with_context(active_test=False)
        eval_context = Rule._get_eval_context()
        for rule in Rule.search([]):
            try:
                with cr.savepoint():
                    _migrate_rule(env, rule, eval_context)
            except Exception:  # noqa: BLE001 - never block the upgrade
                _logger.warning(
                    "Dashboard data filter rule id %s could not be reviewed during "
                    "the upgrade; it is left unchanged and fails closed if it "
                    "cannot be evaluated.",
                    rule.id,
                    exc_info=True,
                )
    except Exception:  # noqa: BLE001 - never block the upgrade
        _logger.warning(
            "spreadsheet_record_rule_oca: reviewing existing dashboard data filter "
            "rules failed; they are left unchanged. Rules still using the removed "
            "'user' variable fail closed until rewritten.",
            exc_info=True,
        )
