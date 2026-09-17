# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user, tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

IC_CODE = "189971"
REVENUE_CODE = "799971"


@tagged("post_install", "-at_install")
class TestConsolidationBalances(AccountTestInvoicingCommon):
    """Balances read per company: branches, eliminations and company access."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.parent = cls.company_data["company"]
        cls.company_data_2 = cls.setup_other_company(
            name="Consolidation Subsidiary",
            currency_id=cls.parent.currency_id.id,
        )
        cls.subsidiary = cls.company_data_2["company"]
        cls.branch = cls.env["res.company"].create(
            {"name": "Consolidation Branch", "parent_id": cls.parent.id}
        )
        cls.misc_parent = cls.company_data["default_journal_misc"]
        cls.misc_subsidiary = cls.company_data_2["default_journal_misc"]

        # Fresh accounts without history, so the expected balances are exact.
        # The parent revenue account is shared with the branch: that is the
        # set-up in which current_balance (child_of) counted branch lines twice.
        cls.ic_parent = cls._create_account(
            cls.parent, "IC receivable", IC_CODE, "asset_current"
        )
        cls.revenue_parent = cls._create_account(
            cls.parent, "Group revenue", REVENUE_CODE, "income", cls.branch
        )
        cls.ic_subsidiary = cls._create_account(
            cls.subsidiary, "IC receivable", IC_CODE, "asset_current"
        )
        cls.revenue_subsidiary = cls._create_account(
            cls.subsidiary, "Group revenue", REVENUE_CODE, "income"
        )

    @classmethod
    def _create_account(cls, company, name, code, account_type, extra=None):
        companies = company | (extra or company.browse())
        return (
            cls.env["account.account"]
            .with_company(company)
            .create(
                {
                    "name": name,
                    "code": code,
                    "account_type": account_type,
                    "company_ids": [Command.set(companies.ids)],
                }
            )
        )

    def _post_entry(self, company, journal, debit_account, credit_account, amount):
        move = (
            self.env["account.move"]
            .with_company(company)
            .create(
                {
                    "move_type": "entry",
                    "company_id": company.id,
                    "journal_id": journal.id,
                    "date": fields.Date.today(),
                    "line_ids": [
                        Command.create(
                            {
                                "name": "debit",
                                "account_id": debit_account.id,
                                "debit": amount,
                                "credit": 0.0,
                            }
                        ),
                        Command.create(
                            {
                                "name": "credit",
                                "account_id": credit_account.id,
                                "debit": 0.0,
                                "credit": amount,
                            }
                        ),
                    ],
                }
            )
        )
        move.action_post()
        self.assertEqual(move.company_id, company)
        return move

    def _create_profile(self, companies, elimination_accounts=None):
        return self.env["spreadsheet.consolidation.profile"].create(
            {
                "name": "Balances test",
                "company_ids": [Command.set(companies.ids)],
                "elimination_account_ids": [
                    Command.set(
                        elimination_accounts.ids if elimination_accounts else []
                    )
                ],
                "currency_id": self.parent.currency_id.id,
            }
        )

    @staticmethod
    def _row_of(cells, code):
        for key, cell in cells.items():
            if key[0] == "B" and key[1:].isdigit() and cell.get("content") == code:
                return key[1:]
        raise AssertionError(f"no spreadsheet row for account code {code}")

    # -- branches ------------------------------------------------------------------

    def test_parent_and_branch_not_double_counted(self):
        self._post_entry(
            self.parent, self.misc_parent, self.ic_parent, self.revenue_parent, 100.0
        )
        self._post_entry(
            self.branch, self.misc_parent, self.ic_parent, self.revenue_parent, 40.0
        )
        profile = self._create_profile(self.parent | self.branch)

        data = profile._compute_consolidation_data()

        columns = {column["id"]: column for column in data["companies"]}
        self.assertEqual(set(columns), {self.parent.id, self.branch.id})
        parent_accounts = columns[self.parent.id]["accounts"]
        branch_accounts = columns[self.branch.id]["accounts"]
        # current_balance (child_of) gave the parent -140 and the total -180.
        self.assertAlmostEqual(parent_accounts[REVENUE_CODE]["balance"], -100.0)
        self.assertAlmostEqual(branch_accounts[REVENUE_CODE]["balance"], -40.0)
        self.assertAlmostEqual(data["consolidated"][REVENUE_CODE]["balance"], -140.0)
        self.assertAlmostEqual(data["consolidated"][IC_CODE]["balance"], 140.0)
        self.assertFalse(data["warnings"])

    def test_parent_alone_still_includes_unlisted_branch(self):
        self._post_entry(
            self.parent, self.misc_parent, self.ic_parent, self.revenue_parent, 100.0
        )
        self._post_entry(
            self.branch, self.misc_parent, self.ic_parent, self.revenue_parent, 40.0
        )
        profile = self._create_profile(self.parent)

        data = profile._compute_consolidation_data()

        self.assertEqual(
            [column["id"] for column in data["companies"]], [self.parent.id]
        )
        self.assertAlmostEqual(
            data["companies"][0]["accounts"][REVENUE_CODE]["balance"], -140.0
        )
        self.assertAlmostEqual(data["consolidated"][REVENUE_CODE]["balance"], -140.0)

    # -- eliminations --------------------------------------------------------------

    def test_elimination_code_resolved_per_company_cancels_whole_row(self):
        self._post_entry(
            self.parent, self.misc_parent, self.ic_parent, self.revenue_parent, 30.0
        )
        self._post_entry(
            self.subsidiary,
            self.misc_subsidiary,
            self.ic_subsidiary,
            self.revenue_subsidiary,
            70.0,
        )
        profile = self._create_profile(
            self.parent | self.subsidiary, elimination_accounts=self.ic_subsidiary
        )
        # Precondition of the old bug: the code is company dependent, so read in
        # the parent the subsidiary's account has no code and was never matched.
        self.assertFalse(self.ic_subsidiary.with_company(self.parent).code)

        data = profile.with_company(self.parent)._compute_consolidation_data()

        self.assertAlmostEqual(data["consolidated"][IC_CODE]["balance"], 100.0)
        # The whole code row is eliminated for every consolidated company: the
        # parent's own IC account shares the code, so its 30 is cancelled too.
        self.assertAlmostEqual(data["eliminations"][IC_CODE]["balance"], -100.0)
        self.assertNotIn(REVENUE_CODE, data["eliminations"])
        self.assertFalse(data["warnings"])

        cells = profile._build_spreadsheet_data(data)["sheets"][0]["cells"]
        row = self._row_of(cells, IC_CODE)
        # 2 companies -> C, D; eliminations E; consolidated F.
        self.assertAlmostEqual(float(cells[f"E{row}"]["content"]), -100.0)
        self.assertAlmostEqual(float(cells[f"F{row}"]["content"]), 0.0)

    def test_archived_elimination_account_still_eliminates(self):
        self._post_entry(
            self.parent, self.misc_parent, self.ic_parent, self.revenue_parent, 25.0
        )
        profile = self._create_profile(self.parent, elimination_accounts=self.ic_parent)
        self.ic_parent.action_archive()

        data = profile._compute_consolidation_data()

        self.assertAlmostEqual(data["eliminations"][IC_CODE]["balance"], -25.0)
        self.assertFalse(data["warnings"])

    def test_unused_elimination_account_is_reported(self):
        self._post_entry(
            self.parent, self.misc_parent, self.ic_parent, self.revenue_parent, 10.0
        )
        profile = self._create_profile(
            self.parent, elimination_accounts=self.ic_subsidiary
        )

        data = profile._compute_consolidation_data()

        self.assertFalse(data["eliminations"])
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn(IC_CODE, data["warnings"][0])

    # -- company access ------------------------------------------------------------

    def _restricted_user(self):
        return new_test_user(
            self.env,
            login="consolidation_restricted",
            groups="base.group_user,account.group_account_user",
            company_id=self.parent.id,
            company_ids=[Command.set(self.parent.ids)],
        )

    def test_inaccessible_company_skipped_with_warning(self):
        self._post_entry(
            self.parent, self.misc_parent, self.ic_parent, self.revenue_parent, 100.0
        )
        self._post_entry(
            self.subsidiary,
            self.misc_subsidiary,
            self.ic_subsidiary,
            self.revenue_subsidiary,
            70.0,
        )
        profile = self._create_profile(
            self.parent | self.subsidiary, elimination_accounts=self.ic_subsidiary
        )
        user = self._restricted_user()

        data = (
            profile.with_user(user)
            .with_context(allowed_company_ids=self.parent.ids)
            ._compute_consolidation_data()
        )

        self.assertEqual(
            [column["id"] for column in data["companies"]], [self.parent.id]
        )
        self.assertAlmostEqual(data["consolidated"][REVENUE_CODE]["balance"], -100.0)
        # One warning only: the elimination account of the skipped subsidiary is
        # not reported as misconfigured, its company is already reported.
        self.assertEqual(len(data["warnings"]), 1)
        # The user cannot read the subsidiary: its name is not disclosed.
        self.assertNotIn(self.subsidiary.name, data["warnings"][0])
        self.assertIn("1 company(ies) you cannot see", data["warnings"][0])
        # The warning is rendered above the table, the header follows a blank row.
        cells = profile._build_spreadsheet_data(data)["sheets"][0]["cells"]
        self.assertEqual(cells["A1"]["content"], data["warnings"][0])
        self.assertNotIn("A2", cells)
        self.assertIn("A3", cells)

    def test_inaccessible_parent_keeps_accessible_branch_column(self):
        self._post_entry(
            self.parent, self.misc_parent, self.ic_parent, self.revenue_parent, 100.0
        )
        self._post_entry(
            self.branch, self.misc_parent, self.ic_parent, self.revenue_parent, 40.0
        )
        profile = self._create_profile(self.parent)
        user = new_test_user(
            self.env,
            login="consolidation_branch_only",
            groups="base.group_user,account.group_account_user",
            company_id=self.branch.id,
            company_ids=[Command.set(self.branch.ids)],
        )

        data = (
            profile.with_user(user)
            .with_context(allowed_company_ids=self.branch.ids)
            ._compute_consolidation_data()
        )

        # The parent is skipped, but the branch balances the user may read are
        # kept in a column of their own instead of being dropped with it.
        self.assertEqual(
            [column["id"] for column in data["companies"]], [self.branch.id]
        )
        self.assertAlmostEqual(data["consolidated"][REVENUE_CODE]["balance"], -40.0)
        self.assertEqual(len(data["warnings"]), 1)
        self.assertNotIn(self.parent.name, data["warnings"][0])
        self.assertIn("1 company(ies) you cannot see", data["warnings"][0])

    def test_archived_company_and_branch_reported_as_archived(self):
        self._post_entry(
            self.parent, self.misc_parent, self.ic_parent, self.revenue_parent, 100.0
        )
        self._post_entry(
            self.branch, self.misc_parent, self.ic_parent, self.revenue_parent, 40.0
        )
        self._post_entry(
            self.subsidiary,
            self.misc_subsidiary,
            self.ic_subsidiary,
            self.revenue_subsidiary,
            70.0,
        )
        profile = self._create_profile(self.parent | self.subsidiary)
        (self.branch | self.subsidiary).sudo().action_archive()

        data = profile._compute_consolidation_data()

        self.assertEqual(
            [column["id"] for column in data["companies"]], [self.parent.id]
        )
        self.assertAlmostEqual(data["consolidated"][REVENUE_CODE]["balance"], -100.0)
        # Archived companies get their own reason, not the "no access" advice.
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn("archived", data["warnings"][0])
        self.assertNotIn("allowed companies", data["warnings"][0])

    def test_unreadable_journal_items_reported_separately(self):
        self._post_entry(
            self.parent, self.misc_parent, self.ic_parent, self.revenue_parent, 100.0
        )
        profile = self._create_profile(self.parent | self.subsidiary)
        Profile = self.registry["spreadsheet.consolidation.profile"]
        original = Profile._read_company_balances
        subsidiary_id = self.subsidiary.id

        def read_balances(record, company, member_ids):
            if company.id == subsidiary_id:
                raise AccessError("journal items refused")  # pylint: disable=translation-required
            return original(record, company, member_ids)

        with patch.object(Profile, "_read_company_balances", read_balances):
            data = profile._compute_consolidation_data()

        self.assertEqual(
            [column["id"] for column in data["companies"]], [self.parent.id]
        )
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn(self.subsidiary.name, data["warnings"][0])
        self.assertIn("journal items", data["warnings"][0])
        self.assertNotIn("allowed companies", data["warnings"][0])

    def test_no_journal_item_access_raises_user_error(self):
        profile = self._create_profile(self.parent)
        user = new_test_user(
            self.env,
            login="consolidation_no_accounting",
            groups="base.group_user",
            company_id=self.parent.id,
            company_ids=[Command.set(self.parent.ids)],
        )

        with self.assertRaisesRegex(UserError, "journal items"):
            profile.with_user(user)._compute_consolidation_data()

    def test_no_accessible_company_raises_user_error(self):
        profile = self._create_profile(self.subsidiary)
        user = self._restricted_user()

        with self.assertRaisesRegex(UserError, "allowed companies"):
            profile.with_user(user).with_context(
                allowed_company_ids=self.parent.ids
            )._compute_consolidation_data()
