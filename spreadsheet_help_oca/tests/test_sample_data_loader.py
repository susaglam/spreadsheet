# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged

from odoo.addons.spreadsheet_help_oca.wizards.sample_data_loader import (
    _sample_domain,
)


@tagged("post_install", "-at_install")
class TestSampleDataLoader(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Loader = cls.env["spreadsheet.sample.data.loader"]

    def _sample_counts(self):
        counts = {}
        for model, field in (
            ("spreadsheet.template", "name"),
            ("spreadsheet.kpi.alert", "name"),
            ("spreadsheet.contract", "name"),
            ("spreadsheet.vendor.scorecard", "notes"),
        ):
            if model in self.env:
                counts[model] = self.env[model].search_count(_sample_domain(field))
        return counts

    def test_load_all_runs_and_is_idempotent(self):
        """action_load with 'all' returns a client action and does not create
        duplicate SAMPLE records when run twice."""
        loader = self.Loader.create({"what_to_load": "all"})

        result = loader.action_load()
        self.assertEqual(result.get("type"), "ir.actions.client")
        self.assertEqual(result.get("tag"), "display_notification")

        counts = self._sample_counts()

        # Second run must not add duplicates.
        loader2 = self.Loader.create({"what_to_load": "all"})
        loader2.action_load()
        for model, after in self._sample_counts().items():
            self.assertEqual(
                after,
                counts[model],
                f"{model} gained duplicate SAMPLE records on rerun",
            )

    def test_legacy_prefix_counts_as_existing_sample(self):
        """Records created before the English rewrite ('ORNEK' prefix) must
        keep the loader idempotent: no new SAMPLE template is added."""
        if "spreadsheet.template" not in self.env:
            self.skipTest("spreadsheet_template_oca not installed")
        Template = self.env["spreadsheet.template"]
        Template.create({"name": "ORNEK - legacy sample"})
        before = Template.search_count(_sample_domain("name"))
        self.assertEqual(
            self.Loader.create({"what_to_load": "template"})._load_templates(), ""
        )
        self.assertEqual(Template.search_count(_sample_domain("name")), before)

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

    def test_failing_loader_degrades_to_warning(self):
        """One broken example loader must not abort the others, and the
        message names the examples (translated label), not the internal key
        or the raw exception text."""
        loader = self.Loader.create({"what_to_load": "all"})
        with patch.object(
            type(loader),
            "_load_templates",
            side_effect=ValueError("broken optional module"),
        ):
            result = loader.action_load()
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "warning")
        message = result["params"]["message"]
        label = dict(loader._fields["what_to_load"]._description_selection(loader.env))[
            "template"
        ]
        self.assertIn(label, message)
        self.assertNotIn("broken optional module", message)

    def test_access_error_tells_who_can_load(self):
        loader = self.Loader.create({"what_to_load": "template"})
        with patch.object(
            type(loader),
            "_load_templates",
            side_effect=AccessError("technical access error text"),
        ):
            result = loader.action_load()
        self.assertEqual(result["params"]["type"], "warning")
        message = result["params"]["message"]
        self.assertNotIn("technical access error text", message)
        self.assertIn("Spreadsheet manager", message)

    def test_sample_kpi_alert_never_anchors_on_help_guides(self):
        """The guides are shared read-only with every Spreadsheet user: the
        sample alert must land on a spreadsheet the user owns or may edit."""
        guide_ids = self.env["spreadsheet.tutorial"]._get_guide_spreadsheet_ids()
        self.assertTrue(guide_ids)
        user = new_test_user(
            self.env,
            login="help_oca_loader_plain_user",
            groups="base.group_user,spreadsheet_oca.group_user",
        )
        loader = self.Loader.with_user(user).create({"what_to_load": "kpi_alert"})
        anchor = loader._get_kpi_anchor_spreadsheet()
        self.assertFalse(set(anchor.ids) & set(guide_ids))

        own_sheet = (
            self.env["spreadsheet.spreadsheet"]
            .with_user(user)
            .create({"name": "Loader anchor sheet"})
        )
        self.assertEqual(loader._get_kpi_anchor_spreadsheet(), own_sheet)

        if "spreadsheet.kpi.alert" not in self.env:
            return
        Alert = self.env["spreadsheet.kpi.alert"]
        Alert.search(_sample_domain("name")).unlink()
        loader._load_kpi_alerts()
        alerts = Alert.search(_sample_domain("name"))
        self.assertTrue(alerts)
        self.assertFalse(set(alerts.spreadsheet_id.ids) & set(guide_ids))

    def test_load_vendor_creates_partner_when_none(self):
        """When the scorecard model exists and no supplier partner is found,
        _load_vendors falls back to creating a SAMPLE supplier partner."""
        if "spreadsheet.vendor.scorecard" not in self.env:
            self.skipTest("spreadsheet_vendor_scorecard_oca not installed")
        Partner = self.env["res.partner"]
        loader = self.Loader.create({"what_to_load": "vendor"})
        loader._load_vendors()
        self.assertTrue(
            Partner.search_count([("supplier_rank", ">", 0)]) > 0,
            "expected at least one supplier partner after loading vendors",
        )
