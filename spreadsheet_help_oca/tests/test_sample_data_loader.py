# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSampleDataLoader(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Loader = cls.env["spreadsheet.sample.data.loader"]

    def test_load_all_runs_and_is_idempotent(self):
        """action_load with 'all' returns a client action and does not create
        duplicate ORNEK records when run twice."""
        loader = self.Loader.create({"what_to_load": "all"})

        result = loader.action_load()
        self.assertEqual(result.get("type"), "ir.actions.client")
        self.assertEqual(result.get("tag"), "display_notification")

        # Capture counts of any optional-model records that were created.
        counts = {}
        for model, domain in (
            ("spreadsheet.template", [("name", "like", "ORNEK%")]),
            ("spreadsheet.kpi.alert", [("name", "like", "ORNEK%")]),
            ("spreadsheet.contract", [("name", "like", "ORNEK%")]),
            ("spreadsheet.vendor.scorecard", [("notes", "like", "ORNEK%")]),
        ):
            if model in self.env:
                counts[model] = self.env[model].search_count(domain)

        # Second run must not add duplicates.
        loader2 = self.Loader.create({"what_to_load": "all"})
        loader2.action_load()
        for model, before in counts.items():
            after = self.env[model].search_count(
                [("notes", "like", "ORNEK%")]
                if model == "spreadsheet.vendor.scorecard"
                else [("name", "like", "ORNEK%")]
            )
            self.assertEqual(
                after, before, f"{model} gained duplicate ORNEK records on rerun"
            )

    def test_load_templates_guard_when_model_absent(self):
        """The optional-model guard returns '' instead of raising KeyError."""
        loader = self.Loader.create({"what_to_load": "template"})
        if "spreadsheet.template" not in self.env:
            # Guard path: must not raise.
            self.assertEqual(loader._load_templates(), "")
        # Regardless of module presence, action_load must not crash.
        result = loader.action_load()
        self.assertEqual(result.get("type"), "ir.actions.client")

    def test_load_kpi_alerts_guard_when_model_absent(self):
        loader = self.Loader.create({"what_to_load": "kpi_alert"})
        if "spreadsheet.kpi.alert" not in self.env:
            self.assertEqual(loader._load_kpi_alerts(), "")
        result = loader.action_load()
        self.assertEqual(result.get("type"), "ir.actions.client")

    def test_load_vendor_creates_partner_when_none(self):
        """When the scorecard model exists and no supplier partner is found,
        _load_vendors falls back to creating an ORNEK supplier partner."""
        if "spreadsheet.vendor.scorecard" not in self.env:
            self.skipTest("spreadsheet_vendor_scorecard_oca not installed")
        Partner = self.env["res.partner"]
        loader = self.Loader.create({"what_to_load": "vendor"})
        loader._load_vendors()
        self.assertTrue(
            Partner.search_count([("supplier_rank", ">", 0)]) > 0,
            "expected at least one supplier partner after loading vendors",
        )
