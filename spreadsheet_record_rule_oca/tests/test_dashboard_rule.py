# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDashboardRule(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env["spreadsheet.dashboard.rule"]
        cls.Dashboard = cls.env["spreadsheet.dashboard"]
        cls.group = cls.env["spreadsheet.dashboard.group"].create(
            {"name": "Test Dashboard Group"}
        )
        cls.dashboard = cls.Dashboard.create(
            {
                "name": "Test Dashboard",
                "dashboard_group_id": cls.group.id,
            }
        )

    # ------------------------------------------------------------------
    # _merge_domains
    # ------------------------------------------------------------------
    def test_merge_domains_keeps_or_operator_valid(self):
        """An OR domain from a rule must survive the merge as a parsable
        domain (guards the old operator-flatten bug)."""
        existing = [("is_company", "=", True)]
        extra = ["|", ("id", "=", 1), ("id", "=", 2)]
        merged = self.Dashboard._merge_domains(existing, extra)
        # Must still be a list and parse without raising.
        self.assertIsInstance(merged, list)
        # Constructing a Domain from it proves operator/operand balance.
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

    # ------------------------------------------------------------------
    # _check_domain
    # ------------------------------------------------------------------
    def test_check_domain_accepts_user_attribute_reference(self):
        """Any user.* reference must validate, not only literal user.id
        (guards the old string-replace hack)."""
        rule = self.Rule.create(
            {
                "name": "Own partner",
                "dashboard_id": self.dashboard.id,
                "model_name": "res.partner",
                "domain_extension": "[('id', '=', user.partner_id.id)]",
            }
        )
        self.assertTrue(rule)

    def test_check_domain_rejects_syntax_error(self):
        with self.assertRaises(ValidationError):
            self.Rule.create(
                {
                    "name": "Broken",
                    "dashboard_id": self.dashboard.id,
                    "model_name": "res.partner",
                    "domain_extension": "[('id', '=', ]",
                }
            )

    # ------------------------------------------------------------------
    # _get_applicable_rules (implied groups)
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
        rule = self.Rule.create(
            {
                "name": "Implied group rule",
                "dashboard_id": self.dashboard.id,
                "model_name": "res.partner",
                "group_ids": [(6, 0, [base_group.id])],
                "domain_extension": "[]",
            }
        )
        applicable = self.Rule.with_user(user)._get_applicable_rules(
            self.dashboard.id, "res.partner"
        )
        self.assertIn(rule, applicable)

    def test_get_applicable_rules_empty_groups_applies_to_all(self):
        rule = self.Rule.create(
            {
                "name": "All users rule",
                "dashboard_id": self.dashboard.id,
                "model_name": "res.partner",
                "domain_extension": "[]",
            }
        )
        applicable = self.Rule._get_applicable_rules(self.dashboard.id, "res.partner")
        self.assertIn(rule, applicable)

    # ------------------------------------------------------------------
    # get_spreadsheet_data
    # ------------------------------------------------------------------
    def test_get_spreadsheet_data_noop_without_rules(self):
        """No rules -> the override returns the parent data untouched."""
        data = self.dashboard.get_spreadsheet_data()
        self.assertIn("spreadsheet_raw", data)

    def test_get_spreadsheet_data_injects_domain(self):
        """With an applicable rule the pivot/list data source domains gain
        the rule's extra domain."""
        self.dashboard.spreadsheet_raw = {
            "sheets": [],
            "pivots": {"1": {"model": "res.partner", "domain": []}},
            "lists": {
                "1": {
                    "model": "res.partner",
                    "domain": [("is_company", "=", True)],
                }
            },
        }
        self.Rule.create(
            {
                "name": "Own records",
                "dashboard_id": self.dashboard.id,
                "model_name": "res.partner",
                "domain_extension": "[('id', '=', user.id)]",
            }
        )
        data = self.dashboard.get_spreadsheet_data()
        raw = data["spreadsheet_raw"]
        user_leaf = ("id", "=", self.env.user.id)
        pivot_domain = list(raw["pivots"]["1"]["domain"])
        list_domain = list(raw["lists"]["1"]["domain"])
        self.assertIn(user_leaf, pivot_domain)
        self.assertIn(user_leaf, list_domain)
        # The list source's pre-existing leaf is preserved.
        self.assertIn(("is_company", "=", True), list_domain)
