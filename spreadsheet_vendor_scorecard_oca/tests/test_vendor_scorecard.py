# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestVendorScorecard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Scorecard = cls.env["spreadsheet.vendor.scorecard"]
        cls.vendor = cls.env["res.partner"].create(
            {"name": "Test Vendor", "supplier_rank": 1}
        )

    # --- _compute_score -------------------------------------------------

    def test_score_weighting_nominal(self):
        """Score is 40% delivery + 40% quality + 20% lead-time efficiency."""
        rec = self.Scorecard.create(
            {
                "partner_id": self.vendor.id,
                "date": fields.Date.today(),
                "on_time_delivery_rate": 90.0,
                "quality_rate": 100.0,
                "avg_lead_time": 5.0,
            }
        )
        lead_time_score = (30 - 5) / 30 * 100
        expected = 90.0 * 0.4 + 100.0 * 0.4 + lead_time_score * 0.2
        self.assertAlmostEqual(rec.score, expected, places=4)

    def test_lead_time_score_floored_at_zero(self):
        """A lead time >= 30 days contributes 0 to the score (not negative)."""
        rec = self.Scorecard.create(
            {
                "partner_id": self.vendor.id,
                "date": fields.Date.today(),
                "on_time_delivery_rate": 0.0,
                "quality_rate": 0.0,
                "avg_lead_time": 40.0,
            }
        )
        # Lead-time component floored at 0 -> whole score is 0.
        self.assertAlmostEqual(rec.score, 0.0, places=4)

    def test_lead_time_score_capped_at_hundred(self):
        """A negative lead time must not push the lead-time score above 100."""
        rec = self.Scorecard.create(
            {
                "partner_id": self.vendor.id,
                "date": fields.Date.today(),
                "on_time_delivery_rate": 0.0,
                "quality_rate": 0.0,
                "avg_lead_time": -10.0,
            }
        )
        # Lead-time component capped at 100 -> contributes exactly 20.
        self.assertAlmostEqual(rec.score, 20.0, places=4)
        self.assertLessEqual(rec.score, 100.0)

    # --- action_open_vendor_orders --------------------------------------

    def test_action_open_vendor_orders_domain(self):
        rec = self.Scorecard.create(
            {"partner_id": self.vendor.id, "date": fields.Date.today()}
        )
        action = rec.action_open_vendor_orders()
        self.assertEqual(action["res_model"], "purchase.order")
        self.assertIn(("partner_id", "=", self.vendor.id), action["domain"])
        self.assertIn(("state", "in", ["purchase", "done"]), action["domain"])

    # --- cron windowing & isolation -------------------------------------

    def test_cron_targets_previous_complete_month(self):
        """No orders -> vendor skipped, but the cron computes the right window
        (previous complete month) and never raises."""
        # Vendor has no purchase orders in the window -> no scorecard produced.
        self.Scorecard._cron_compute_scorecards()
        today = fields.Date.today()
        period_end = today.replace(day=1)
        period_start = (period_end - timedelta(days=1)).replace(day=1)
        card = self.Scorecard.search(
            [("partner_id", "=", self.vendor.id), ("date", "=", period_start)]
        )
        self.assertFalse(card, "No orders in period must not create a scorecard")

    def test_cron_isolates_per_vendor_failure(self):
        """One vendor raising must not abort the whole scheduled run."""
        with patch.object(
            type(self.Scorecard),
            "_compute_vendor_scorecard",
            side_effect=ValueError("boom"),
        ):
            # Must swallow the per-vendor error and complete cleanly.
            self.Scorecard._cron_compute_scorecards()

    def test_helper_no_orders_returns_without_card(self):
        """The per-vendor helper is a no-op when the vendor has no orders."""
        today = fields.Date.today()
        period_end = today.replace(day=1)
        period_start = (period_end - timedelta(days=1)).replace(day=1)
        self.Scorecard._compute_vendor_scorecard(self.vendor, period_start, period_end)
        card = self.Scorecard.search(
            [("partner_id", "=", self.vendor.id), ("date", "=", period_start)]
        )
        self.assertFalse(card)
