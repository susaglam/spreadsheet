# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import re

from odoo.tests.common import TransactionCase, tagged

A1_COL_RE = re.compile(r"^[A-Z]+[0-9]+$")


@tagged("post_install", "-at_install")
class TestConsolidation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env["spreadsheet.consolidation.profile"]
        cls.profile = cls.Profile.create(
            {
                "name": "Test Consolidation",
                "company_ids": [(6, 0, cls.env.company.ids)],
                "currency_id": cls.env.company.currency_id.id,
            }
        )

    def _sample_data(self):
        """Shape mirrors _compute_consolidation_data output (post-fix):

        consolidated keeps the raw sum; eliminations holds the negated sum.
        """
        return {
            "accounts": {},
            "companies": [
                {
                    "id": 1,
                    "name": "Company A",
                    "accounts": {
                        "100": {"name": "Cash", "code": "100", "balance": 100.0},
                        "200": {"name": "Sales", "code": "200", "balance": 20.0},
                    },
                },
                {
                    "id": 2,
                    "name": "Company B",
                    "accounts": {
                        "100": {"name": "Cash", "code": "100", "balance": 50.0},
                        "200": {"name": "Sales", "code": "200", "balance": 10.0},
                    },
                },
            ],
            "consolidated": {
                "100": {"name": "Cash", "code": "100", "balance": 150.0},
                "200": {"name": "Sales", "code": "200", "balance": 30.0},
            },
            "eliminations": {
                # inter-company account fully eliminated
                "100": {"name": "Cash", "code": "100", "balance": -150.0},
            },
        }

    # -- _col_letter helper (Tier 6 regression) --------------------------------

    def test_col_letter_within_az(self):
        self.assertEqual(self.profile._col_letter(0), "A")
        self.assertEqual(self.profile._col_letter(25), "Z")

    def test_col_letter_beyond_z(self):
        # The chr(65 + col) bug produced '[' at index 26; base-26 must give 'AA'.
        self.assertEqual(self.profile._col_letter(26), "AA")
        self.assertEqual(self.profile._col_letter(27), "AB")
        self.assertEqual(self.profile._col_letter(51), "AZ")
        self.assertEqual(self.profile._col_letter(52), "BA")

    # -- builder output --------------------------------------------------------

    def test_eliminated_account_consolidated_is_zero(self):
        data = self._sample_data()
        result = self.profile._build_spreadsheet_data(data)
        cells = result["sheets"][0]["cells"]
        # 2 companies -> C,D; eliminations E; consolidated F. Code 100 -> row 2.
        self.assertAlmostEqual(float(cells["F2"]["content"]), 0.0)

    def test_non_eliminated_account_sums_across_companies(self):
        data = self._sample_data()
        result = self.profile._build_spreadsheet_data(data)
        cells = result["sheets"][0]["cells"]
        # Code 200 -> row 3, no elimination -> 20 + 10 = 30.
        self.assertAlmostEqual(float(cells["F3"]["content"]), 30.0)
        # Per-company columns preserved.
        self.assertAlmostEqual(float(cells["C3"]["content"]), 20.0)
        self.assertAlmostEqual(float(cells["D3"]["content"]), 10.0)

    def test_column_refs_valid_beyond_z(self):
        # 30 companies force column indices past 'Z'; every cell key must be A1.
        data = self._sample_data()
        data["companies"] = [
            {"id": i, "name": f"C{i}", "accounts": {"100": {"balance": 1.0}}}
            for i in range(30)
        ]
        result = self.profile._build_spreadsheet_data(data)
        cells = result["sheets"][0]["cells"]
        self.assertTrue(cells)
        for key in cells:
            self.assertRegex(key, A1_COL_RE, f"invalid cell reference {key!r}")

    def test_generate_report_returns_open_action(self):
        action = self.profile.action_generate_report()
        self.assertIsInstance(action, dict)
        self.assertEqual(action.get("type"), "ir.actions.client")
        self.assertEqual(action.get("tag"), "action_spreadsheet_oca")
