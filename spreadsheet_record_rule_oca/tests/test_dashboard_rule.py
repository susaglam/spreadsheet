# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import importlib.util
import json

from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.models import BaseModel
from odoo.tests.common import new_test_user, tagged
from odoo.tools import mute_logger
from odoo.tools.misc import file_path

from odoo.addons.spreadsheet_record_rule_oca.models.dashboard_rule import (
    EVAL_CONTEXT_NAMES,
)

from .common import DashboardRuleCommon

MODULE = "odoo.addons.spreadsheet_record_rule_oca"
RULE_LOGGER = f"{MODULE}.models.dashboard_rule"
DASHBOARD_LOGGER = f"{MODULE}.models.spreadsheet_dashboard"
MIGRATION_LOGGER = f"{MODULE}.migrations.test_post_migrate"


def _leaves(domain):
    """Normalise a domain coming from Python (tuples) or JSON (lists)."""
    return [tuple(item) if isinstance(item, list) else item for item in domain]


@tagged("post_install", "-at_install")
class TestDashboardRule(DashboardRuleCommon):
    # ------------------------------------------------------------------
    # _merge_domains
    # ------------------------------------------------------------------
    def test_merge_domains_keeps_or_operator_valid(self):
        """An OR domain from a rule must survive the merge as a parsable
        domain (guards the old operator-flatten bug)."""
        existing = [("is_company", "=", True)]
        extra = ["|", ("id", "=", 1), ("id", "=", 2)]
        merged = self.Dashboard._merge_domains(existing, extra)
        self.assertIsInstance(merged, list)
        Domain(merged)

    def test_merge_domains_empty_sides(self):
        self.assertEqual(
            self.Dashboard._merge_domains([], [("a", "=", 1)]),
            list(Domain([("a", "=", 1)])),
        )
        self.assertEqual(
            self.Dashboard._merge_domains([("a", "=", 1)], []),
            list(Domain([("a", "=", 1)])),
        )

    def test_merge_domains_string_source_keeps_contextual_expressions(self):
        """A data source domain stored as a string (contextual values) gets
        the rule leaves appended instead of crashing the dashboard load."""
        source = "[('date', '>=', context_today().strftime('%Y-%m-%d'))]"
        merged = self.Dashboard._merge_domains(source, [("id", "=", 7)])
        self.assertEqual(
            merged,
            "[('date', '>=', context_today().strftime('%Y-%m-%d')), ('id', '=', 7)]",
        )

    @mute_logger(DASHBOARD_LOGGER)
    def test_merge_domains_uncombinable_string_fails_closed(self):
        merged = self.Dashboard._merge_domains("foo() + []", [("id", "=", 7)])
        self.assertTrue(Domain(merged).is_false())

    # ------------------------------------------------------------------
    # Plain-value evaluation context (H5)
    # ------------------------------------------------------------------
    def test_eval_context_holds_plain_values_only(self):
        context = self.Rule.with_user(self.viewer)._get_eval_context()
        self.assertEqual(set(context), set(EVAL_CONTEXT_NAMES))
        for name, value in context.items():
            values = value if isinstance(value, list) else [value]
            for item in values:
                self.assertNotIsInstance(item, BaseModel, name)
                self.assertIsInstance(item, int | str, name)
        self.assertEqual(context["user_id"], self.viewer.id)
        self.assertEqual(context["partner_id"], self.viewer.partner_id.id)
        self.assertIn("base.group_user", context["group_xmlids"])

    def test_plain_value_domains_evaluate_for_the_viewing_user(self):
        self.create_rule("[('id', '=', partner_id)]")
        self.create_rule(
            "[] if 'base.group_system' in group_xmlids else [('id', '=', user_id)]",
            model="res.users",
        )
        Rule = self.Rule.with_user(self.viewer)
        partner_domain = Rule._get_applicable_rules(
            self.dashboard.id, "res.partner"
        )._build_combined_domain()
        self.assertEqual(partner_domain, [("id", "=", self.viewer.partner_id.id)])
        users_domain = Rule._get_applicable_rules(
            self.dashboard.id, "res.users"
        )._build_combined_domain()
        self.assertEqual(users_domain, [("id", "=", self.viewer.id)])
        # An administrator is not narrowed by the conditional expression.
        admin = self.env.ref("base.user_admin")
        admin_domain = (
            self.Rule.with_user(admin)
            ._get_applicable_rules(self.dashboard.id, "res.users")
            ._build_combined_domain()
        )
        self.assertEqual(admin_domain, [])

    def test_company_ids_expression(self):
        self.create_rule("[('company_id', 'in', company_ids + [False])]")
        domain = (
            self.Rule.with_user(self.viewer)
            ._get_applicable_rules(self.dashboard.id, "res.partner")
            ._build_combined_domain()
        )
        self.assertEqual(len(domain), 1)
        field, operator, value = domain[0]
        self.assertEqual((field, operator), ("company_id", "in"))
        self.assertEqual(set(value), {*self.viewer.company_ids.ids, False})

    def test_sudo_write_expression_is_rejected_on_save(self):
        """The privilege-escalation payload of H5 cannot be saved."""
        for payload in (
            "user.sudo().write({'function': 'pwned'}) or []",
            "[('id', '=', user.id)]",
            "env['res.users'].sudo().search([]) and []",
            "__import__('os').system('true') or []",
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    self.create_rule(payload)

    @mute_logger(RULE_LOGGER)
    def test_legacy_sudo_write_expression_is_never_executed(self):
        """A payload already stored in the database (before the upgrade) is
        never executed when the dashboard is viewed; it fails closed."""
        rule = self.create_rule("[]")
        self.force_domain(
            rule, "user.sudo().write({'function': 'pwned'}) or [('id', '!=', 0)]"
        )
        dashboard = self.dashboard.with_user(self.viewer)
        payload = json.loads(dashboard._get_serialized_readonly_dashboard())
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT function FROM res_partner WHERE id IN %s",
            (tuple((self.viewer.partner_id | self.env.user.partner_id).ids),),
        )
        self.assertNotIn("pwned", [row[0] for row in self.env.cr.fetchall()])
        self.assertTrue(Domain(payload["snapshot"]["pivots"]["1"]["domain"]).is_false())

    def test_legacy_user_variable_gets_explicit_hint(self):
        rule = self.create_rule("[]")
        self.force_domain(rule, "[('id', '=', user.partner_id.id)]")
        self.assertIn("user_id", rule.evaluation_error)
        self.assertIn("'user'", rule.evaluation_error)

    def test_rules_are_administrator_only(self):
        """Spreadsheet managers may read rules but not create/change them."""
        rule = self.create_rule("[('id', '=', partner_id)]")
        manager_rule = rule.with_user(self.spreadsheet_manager)
        self.assertEqual(manager_rule.name, "Test rule")
        with self.assertRaises(AccessError):
            self.Rule.with_user(self.spreadsheet_manager).create(
                {
                    "name": "Escalation attempt",
                    "dashboard_id": self.dashboard.id,
                    "model_name": "res.partner",
                    "domain_extension": "[]",
                }
            )
        with self.assertRaises(AccessError):
            manager_rule.write({"domain_extension": "[]"})
        admin = new_test_user(self.env, login="rr_admin", groups="base.group_system")
        self.Rule.with_user(admin).create(
            {
                "name": "Admin rule",
                "dashboard_id": self.dashboard.id,
                "model_name": "res.partner",
                "domain_extension": "[('id', '=', partner_id)]",
            }
        )

    # ------------------------------------------------------------------
    # _check_domain
    # ------------------------------------------------------------------
    def test_check_domain_rejects_syntax_error(self):
        with self.assertRaises(ValidationError):
            self.create_rule("[('id', '=', ]")

    def test_check_domain_rejects_unknown_field_and_model(self):
        with self.assertRaises(ValidationError):
            self.create_rule("[('no_such_field_xyz', '=', 1)]")
        with self.assertRaises(ValidationError):
            self.create_rule("[]", model="no.such.model.xyz")

    def test_valid_rule_has_no_evaluation_error(self):
        rule = self.create_rule("[('id', '=', partner_id)]")
        self.assertFalse(rule.evaluation_error)

    # ------------------------------------------------------------------
    # Fail closed
    # ------------------------------------------------------------------
    @mute_logger(RULE_LOGGER)
    def test_eval_error_fails_closed(self):
        rule = self.create_rule("[('id', '=', partner_id)]")
        self.force_domain(rule, "[('id', '=', company_ids[99])]")
        self.assertTrue(rule.evaluation_error)
        combined = (
            self.Rule.with_user(self.viewer)
            ._get_applicable_rules(self.dashboard.id, "res.partner")
            ._build_combined_domain()
        )
        self.assertTrue(Domain(combined).is_false())
        payload = json.loads(
            self.dashboard.with_user(self.viewer)._get_serialized_readonly_dashboard()
        )
        snapshot = payload["snapshot"]
        self.assertTrue(Domain(snapshot["pivots"]["1"]["domain"]).is_false())
        self.assertTrue(Domain(snapshot["lists"]["1"]["domain"]).is_false())
        chart = snapshot["sheets"][0]["figures"][0]["data"]
        self.assertTrue(Domain(chart["searchParams"]["domain"]).is_false())
        # Other models are not affected by the broken rule.
        self.assertEqual(snapshot["lists"]["2"]["domain"], [])

    @mute_logger(RULE_LOGGER)
    def test_one_broken_rule_closes_the_model_even_with_valid_rules(self):
        self.create_rule("[('id', '=', partner_id)]", name="Valid")
        broken = self.create_rule("[]", name="Broken")
        self.force_domain(broken, "[('id', '=', not_a_variable)]")
        combined = (
            self.Rule.with_user(self.viewer)
            ._get_applicable_rules(self.dashboard.id, "res.partner")
            ._build_combined_domain()
        )
        self.assertTrue(Domain(combined).is_false())

    # ------------------------------------------------------------------
    # _get_applicable_rules
    # ------------------------------------------------------------------
    def test_get_applicable_rules_matches_implied_group(self):
        """A user holding the rule's group only through implication must
        still match (all_group_ids, not group_ids)."""
        base_group = self.env["res.groups"].create({"name": "Base Implied"})
        parent_group = self.env["res.groups"].create(
            {"name": "Parent Implies Base", "implied_ids": [(4, base_group.id)]}
        )
        user = self.env["res.users"].create(
            {
                "name": "Implied User",
                "login": "implied_user_test",
                "group_ids": [(6, 0, [parent_group.id])],
            }
        )
        rule = self.create_rule("[]", group_ids=[(6, 0, [base_group.id])])
        applicable = self.Rule.with_user(user)._get_applicable_rules(
            self.dashboard.id, "res.partner"
        )
        self.assertIn(rule, applicable)

    def test_get_applicable_rules_skips_other_groups(self):
        other_group = self.env["res.groups"].create({"name": "Not The Viewer's"})
        self.create_rule("[('id', '=', 0)]", group_ids=[(6, 0, [other_group.id])])
        applicable = self.Rule.with_user(self.viewer)._get_applicable_rules(
            self.dashboard.id, "res.partner"
        )
        self.assertFalse(applicable)

    def test_get_applicable_rules_empty_groups_applies_to_all(self):
        rule = self.create_rule("[]")
        applicable = self.Rule._get_applicable_rules(self.dashboard.id, "res.partner")
        self.assertIn(rule, applicable)

    # ------------------------------------------------------------------
    # Core Dashboards app path (BYPASS10)
    # ------------------------------------------------------------------
    def test_core_serialized_dashboard_applies_rules(self):
        """/spreadsheet/dashboard/data uses _get_serialized_readonly_dashboard;
        the rules must be applied there for a plain internal user who has no
        access to the rule model itself."""
        self.create_rule("[('id', '=', partner_id)]")
        dashboard = self.dashboard.with_user(self.viewer)
        body = dashboard._get_serialized_readonly_dashboard()
        snapshot = json.loads(body)["snapshot"]
        leaf = ("id", "=", self.viewer.partner_id.id)
        self.assertEqual(_leaves(snapshot["pivots"]["1"]["domain"]), [leaf])
        list_domain = _leaves(snapshot["lists"]["1"]["domain"])
        self.assertIn(leaf, list_domain)
        self.assertIn(("is_company", "=", True), list_domain)
        chart = snapshot["sheets"][0]["figures"][0]["data"]
        self.assertEqual(_leaves(chart["searchParams"]["domain"]), [leaf])
        self.assertEqual(snapshot["lists"]["2"]["domain"], [])
        # The stored design itself is never modified.
        self.assertEqual(self.dashboard.spreadsheet_raw["pivots"]["1"]["domain"], [])

    def test_core_serialized_dashboard_untouched_without_rules(self):
        dashboard = self.dashboard.with_user(self.viewer)
        body = dashboard._get_serialized_readonly_dashboard()
        self.assertEqual(json.loads(body)["snapshot"]["pivots"]["1"]["domain"], [])

    def test_apply_rules_to_saas194_chart_layout_and_carousel(self):
        self.create_rule("[('id', '=', partner_id)]")
        snapshot = {
            "sheets": [
                {
                    "figures": [
                        {
                            "tag": "chart",
                            "data": {
                                "type": "odoo_line",
                                "dataSource": {
                                    "type": "odoo",
                                    "metaData": {"resModel": "res.partner"},
                                    "searchParams": {"domain": []},
                                },
                            },
                        },
                        {
                            "tag": "carousel",
                            "data": {
                                "chartDefinitions": {
                                    "c1": {
                                        "dataSource": {
                                            "type": "odoo",
                                            "metaData": {"resModel": "res.partner"},
                                            "searchParams": {"domain": "[]"},
                                        }
                                    }
                                }
                            },
                        },
                    ]
                }
            ]
        }
        result = self.dashboard.with_user(self.viewer)._apply_dashboard_rules(snapshot)
        leaf = ("id", "=", self.viewer.partner_id.id)
        figures = result["sheets"][0]["figures"]
        chart_params = figures[0]["data"]["dataSource"]["searchParams"]
        self.assertEqual(_leaves(chart_params["domain"]), [leaf])
        carousel_params = figures[1]["data"]["chartDefinitions"]["c1"]["dataSource"][
            "searchParams"
        ]
        self.assertEqual(carousel_params["domain"], f"[{leaf!r}]")
        # The input snapshot is not mutated.
        self.assertEqual(
            snapshot["sheets"][0]["figures"][0]["data"]["dataSource"]["searchParams"][
                "domain"
            ],
            [],
        )

    # ------------------------------------------------------------------
    # OCA loader (get_spreadsheet_data)
    # ------------------------------------------------------------------
    def test_get_spreadsheet_data_noop_without_rules(self):
        data = self.dashboard.get_spreadsheet_data()
        self.assertIn("spreadsheet_raw", data)
        self.assertEqual(data["spreadsheet_raw"]["pivots"]["1"]["domain"], [])

    def test_get_spreadsheet_data_injects_domain_for_non_editors(self):
        """Portal-style call (sudo on behalf of a user who cannot edit the
        dashboard) gets the rule domain."""
        self.create_rule("[('id', '=', partner_id)]")
        data = self.dashboard.with_user(self.viewer).sudo().get_spreadsheet_data()
        raw = data["spreadsheet_raw"]
        leaf = ("id", "=", self.viewer.partner_id.id)
        self.assertIn(leaf, _leaves(raw["pivots"]["1"]["domain"]))
        list_domain = _leaves(raw["lists"]["1"]["domain"])
        self.assertIn(leaf, list_domain)
        self.assertIn(("is_company", "=", True), list_domain)

    def test_get_spreadsheet_data_keeps_design_for_editors(self):
        """Editors save the exported model back into the dashboard; the
        per-user filter must not be baked into the design."""
        self.create_rule("[('id', '=', user_id)]")
        data = self.dashboard.get_spreadsheet_data()
        self.assertEqual(data["spreadsheet_raw"]["pivots"]["1"]["domain"], [])

    def test_design_editor_detection(self):
        self.assertTrue(
            self.dashboard.with_user(
                self.dashboard_manager
            )._is_dashboard_design_editor()
        )
        self.assertFalse(
            self.dashboard.with_user(self.viewer)._is_dashboard_design_editor()
        )
        self.assertFalse(
            self.dashboard.with_user(self.viewer).sudo()._is_dashboard_design_editor()
        )

    # ------------------------------------------------------------------
    # Upgrade script
    # ------------------------------------------------------------------
    def _load_migration(self):
        path = file_path(
            "spreadsheet_record_rule_oca/migrations/saas~19.4.1.0.2/post-migrate.py"
        )
        spec = importlib.util.spec_from_file_location(MIGRATION_LOGGER, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_migration_rewrite_expression(self):
        migration = self._load_migration()
        self.assertEqual(
            migration.rewrite_expression(
                "['|', ('user_id', '=', user.id), ('company_id', 'in', "
                "user.company_ids.ids)]"
            ),
            "['|', ('user_id', '=', user_id), ('company_id', 'in', company_ids)]",
        )
        # Text inside string literals is left alone.
        self.assertEqual(
            migration.rewrite_expression("[('name', '=', 'user.id'), ('x', '=', 1)]"),
            "[('name', '=', 'user.id'), ('x', '=', 1)]",
        )

    @mute_logger(MIGRATION_LOGGER, RULE_LOGGER)
    def test_migration_rewrites_existing_rules(self):
        migration = self._load_migration()
        fixable = self.create_rule("[]", name="Fixable")
        self.force_domain(
            fixable, "['|', ('id', '=', user.partner_id.id), ('name', '=', 'user.id')]"
        )
        unfixable = self.create_rule("[]", name="Unfixable")
        self.force_domain(unfixable, "[('id', 'in', user.child_ids.ids)]")
        migration.migrate(self.env.cr, "saas~19.4.1.0.1")
        fixable.invalidate_recordset()
        unfixable.invalidate_recordset()
        self.assertEqual(
            fixable.domain_extension,
            "['|', ('id', '=', partner_id), ('name', '=', 'user.id')]",
        )
        self.assertFalse(fixable.evaluation_error)
        # Not rewritable: left as is (fails closed), and still active.
        self.assertEqual(
            unfixable.domain_extension, "[('id', 'in', user.child_ids.ids)]"
        )
        self.assertTrue(unfixable.active)
        self.assertTrue(unfixable.evaluation_error)
