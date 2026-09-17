# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import importlib.util
from datetime import datetime, time, timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger
from odoo.tools.misc import file_path

MODULE = "spreadsheet_vendor_scorecard_oca"
MODEL_LOGGER = f"odoo.addons.{MODULE}.models.vendor_scorecard"


@tagged("post_install", "-at_install")
class TestVendorScorecard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Scorecard = cls.env["spreadsheet.vendor.scorecard"]
        cls.vendor = cls.env["res.partner"].create(
            {"name": "Test Vendor", "supplier_rank": 1}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Scorecard Test Product", "type": "consu"}
        )

    # --- helpers --------------------------------------------------------

    def _period(self):
        """Same window as the cron: the previous complete month."""
        today = fields.Date.context_today(self.Scorecard)
        period_end = today.replace(day=1)
        period_start = (period_end - timedelta(days=1)).replace(day=1)
        return period_start, period_end

    def _confirmed_order(self, vendor, date_approve, date_order=None, price=50.0):
        """A purchase order confirmed on ``date_approve`` (a datetime)."""
        order = self.env["purchase.order"].create(
            {
                "partner_id": vendor.id,
                "order_line": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 2.0,
                            "price_unit": price,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        order.button_confirm()
        self.assertEqual(order.state, "purchase")
        order.write(
            {
                "date_approve": date_approve,
                "date_order": date_order or date_approve,
            }
        )
        self.env.flush_all()
        return order

    def _in_period(self, days=9):
        period_start, _period_end = self._period()
        return datetime.combine(period_start + timedelta(days=days), time(10, 0))

    def _card(self, vendor):
        period_start, _period_end = self._period()
        return self.Scorecard.search(
            [("partner_id", "=", vendor.id), ("date", "=", period_start)]
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

    # --- purchase.order states (saas-19.4 has no 'done') -----------------

    def test_period_domain_uses_only_valid_order_states(self):
        """Every state the scorecard filters on must exist on purchase.order."""
        valid_states = self.env["purchase.order"]._fields["state"].get_values(self.env)
        self.assertNotIn("done", valid_states)
        period_start, period_end = self._period()
        domain = self.Scorecard._get_period_order_domain(period_start, period_end)
        for field_name, _operator, value in domain:
            if field_name == "state":
                values = value if isinstance(value, list | tuple) else [value]
                for state in values:
                    self.assertIn(state, valid_states)

    def test_action_open_vendor_orders_domain(self):
        rec = self.Scorecard.create(
            {"partner_id": self.vendor.id, "date": fields.Date.today()}
        )
        action = rec.action_open_vendor_orders()
        self.assertEqual(action["res_model"], "purchase.order")
        self.assertIn(("partner_id", "=", self.vendor.id), action["domain"])
        self.assertIn(("state", "=", "purchase"), action["domain"])
        self.assertNotIn("done", str(action["domain"]))

    def test_locked_order_counts_as_confirmed(self):
        """A locked order (19.4's replacement for the old 'done') is counted."""
        order = self._confirmed_order(self.vendor, self._in_period())
        order.button_lock()
        self.assertTrue(order.locked)
        self.assertEqual(order.state, "purchase")

        self.Scorecard._cron_compute_scorecards()

        card = self._card(self.vendor)
        self.assertEqual(len(card), 1)
        self.assertEqual(card.total_orders, 1)
        self.assertAlmostEqual(card.total_amount, order.amount_untaxed, places=2)
        self.assertEqual(card.quality_rate, 100.0)

    def test_report_window_uses_confirmation_date(self):
        """Orders are counted by confirmation date, not by the RFQ deadline:
        a deadline in an earlier month must not zero the order count."""
        period_start, _period_end = self._period()
        confirmed = self._in_period()
        deadline = datetime.combine(period_start - timedelta(days=40), time(10, 0))
        order = self._confirmed_order(self.vendor, confirmed, date_order=deadline)

        self.Scorecard._cron_compute_scorecards()

        card = self._card(self.vendor)
        self.assertEqual(len(card), 1)
        self.assertEqual(card.total_orders, 1)
        self.assertAlmostEqual(card.total_amount, order.amount_untaxed, places=2)
        self.assertTrue(card.total_amount)

    def test_cron_includes_vendor_without_supplier_rank(self):
        """A vendor with orders but no posted bill yet (supplier_rank 0)."""
        vendor = self.env["res.partner"].create(
            {"name": "Unranked Vendor", "supplier_rank": 0}
        )
        self._confirmed_order(vendor, self._in_period())
        self.assertEqual(vendor.supplier_rank, 0)

        self.Scorecard._cron_compute_scorecards()

        self.assertEqual(len(self._card(vendor)), 1)

    def test_rerun_keeps_manual_quality_rate(self):
        """quality_rate is a manual override: re-running the cron for the same
        period refreshes the metrics but keeps the user's quality value."""
        self._confirmed_order(self.vendor, self._in_period())
        self.Scorecard._cron_compute_scorecards()
        card = self._card(self.vendor)
        self.assertEqual(card.quality_rate, 100.0)

        card.write({"quality_rate": 70.0, "total_orders": 99})
        self.Scorecard._cron_compute_scorecards()

        card = self._card(self.vendor)
        self.assertEqual(len(card), 1, "A re-run must update, not duplicate")
        self.assertEqual(card.quality_rate, 70.0)
        self.assertEqual(card.total_orders, 1)

    # --- cron windowing & isolation -------------------------------------

    def test_cron_targets_previous_complete_month(self):
        """No orders -> vendor skipped, but the cron computes the right window
        (previous complete month) and never raises."""
        self.Scorecard._cron_compute_scorecards()
        self.assertFalse(
            self._card(self.vendor), "No orders in period must not create a scorecard"
        )

    def test_order_outside_period_is_ignored(self):
        """An order confirmed this month belongs to next run, not last month."""
        _period_start, period_end = self._period()
        self._confirmed_order(
            self.vendor, datetime.combine(period_end + timedelta(days=1), time(10, 0))
        )
        self.Scorecard._cron_compute_scorecards()
        self.assertFalse(self._card(self.vendor))

    def test_cron_isolates_per_vendor_failure(self):
        """A vendor failing with a SQL error (which aborts the transaction) must
        roll back only its own partial writes; later vendors are still computed.
        """
        failing = self.env["res.partner"].create(
            {"name": "AAA Failing Vendor", "supplier_rank": 1}
        )
        healthy = self.env["res.partner"].create(
            {"name": "ZZZ Healthy Vendor", "supplier_rank": 1}
        )
        self._confirmed_order(failing, self._in_period())
        self._confirmed_order(healthy, self._in_period(days=12))

        scorecard_class = type(self.Scorecard)
        original = scorecard_class._compute_vendor_scorecard
        attempted = []

        def fake_compute(model, vendor, period_start, period_end):
            if vendor not in (failing | healthy):
                return None
            attempted.append(vendor)
            if vendor == failing:
                # Partial write first, then an error that aborts the whole
                # PostgreSQL transaction unless a savepoint contains it.
                model.create({"partner_id": vendor.id, "date": period_start})
                model.env.flush_all()
                model.env.cr.execute("SELECT 1/0")
            return original(model, vendor, period_start, period_end)

        with (
            patch.object(
                scorecard_class,
                "_compute_vendor_scorecard",
                autospec=True,
                side_effect=fake_compute,
            ),
            mute_logger("odoo.sql_db"),
            self.assertLogs(MODEL_LOGGER, level="WARNING") as logs,
        ):
            self.Scorecard._cron_compute_scorecards()

        self.assertIn(failing, attempted)
        self.assertIn(healthy, attempted)
        self.assertLess(
            attempted.index(failing),
            attempted.index(healthy),
            "The failing vendor must run first for this test to prove isolation",
        )
        self.assertFalse(
            self._card(failing), "The failing vendor's partial row must be rolled back"
        )
        healthy_card = self._card(healthy)
        self.assertEqual(len(healthy_card), 1)
        self.assertEqual(healthy_card.total_orders, 1)
        self.assertEqual(len(logs.records), 1)
        self.assertIn(str(failing.id), logs.output[0])

    def test_helper_no_orders_returns_without_card(self):
        """The per-vendor helper is a no-op when the vendor has no orders."""
        period_start, period_end = self._period()
        self.Scorecard._compute_vendor_scorecard(self.vendor, period_start, period_end)
        self.assertFalse(self._card(self.vendor))

    # --- scheduled action data ------------------------------------------

    def test_cron_is_single_noupdate_record(self):
        """The cron is loaded under noupdate so an upgrade keeps admin changes,
        and moving it out of the views file did not create a second job."""
        imd = self.env["ir.model.data"].search(
            [
                ("module", "=", MODULE),
                (
                    "name",
                    "in",
                    [
                        "ir_cron_vendor_scorecard",
                        "ir_cron_vendor_scorecard_ir_actions_server",
                    ],
                ),
            ]
        )
        self.assertEqual(len(imd), 2)
        self.assertTrue(all(imd.mapped("noupdate")))

        cron = self.env.ref(f"{MODULE}.ir_cron_vendor_scorecard")
        self.assertEqual(cron.code, "model._cron_compute_scorecards()")
        self.assertEqual(
            self.env["ir.cron"]
            .with_context(active_test=False)
            .search_count(
                [
                    ("model_id.model", "=", "spreadsheet.vendor.scorecard"),
                    ("code", "=", "model._cron_compute_scorecards()"),
                ]
            ),
            1,
        )

    def test_migration_flags_cron_noupdate(self):
        """The 1.0.2 post-migration flips a legacy noupdate=False cron xmlid and
        is idempotent."""
        imd = self.env["ir.model.data"].search(
            [("module", "=", MODULE), ("name", "=", "ir_cron_vendor_scorecard")]
        )
        imd.noupdate = False
        self.env.flush_all()

        path = file_path(f"{MODULE}/migrations/saas~19.4.1.0.2/post-migrate.py")
        spec = importlib.util.spec_from_file_location("vendor_scorecard_mig", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        migration.migrate(self.env.cr, "saas~19.4.1.0.1")
        migration.migrate(self.env.cr, "saas~19.4.1.0.1")  # idempotent

        imd.invalidate_recordset(["noupdate"])
        self.assertTrue(imd.noupdate)
