# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class VendorScorecard(models.Model):
    _name = "spreadsheet.vendor.scorecard"
    _description = "Vendor Performance Scorecard"
    _order = "partner_id, date desc"

    partner_id = fields.Many2one(
        "res.partner",
        string="Vendor",
        required=True,
        domain=[("supplier_rank", ">", 0)],
        index=True,
        help="The supplier this scorecard rates. The list offers contacts "
        "flagged as vendors: created from a purchase order's Vendor field or "
        "used on a posted vendor bill.",
    )
    date = fields.Date(
        default=fields.Date.context_today,
        required=True,
        help="First day of the period this scorecard summarises.",
    )
    on_time_delivery_rate = fields.Float(
        string="On-Time Delivery (%)",
        help="Percentage of deliveries received on or before the expected date.",
    )
    quality_rate = fields.Float(
        string="Quality Rate (%)",
        help="Manual quality override; defaults to 100 pending QC integration. "
        "Percentage of received items without quality issues.",
    )
    avg_lead_time = fields.Float(
        string="Avg Lead Time (days)",
        help="Average number of days between a purchase order's order deadline "
        "and the planned receipt date of its lines (the 'Days to Receive' "
        "measure of the purchase analysis), for orders confirmed in the period. "
        "Example: order deadline on the 1st, goods planned for the 6th -> 5 days.",
    )
    total_orders = fields.Integer(
        help="Number of purchase orders confirmed in the period (locked "
        "orders included).",
    )
    total_amount = fields.Float(
        help="Untaxed total, in company currency, of the purchase orders "
        "confirmed in the period.",
    )
    score = fields.Float(
        string="Overall Score",
        compute="_compute_score",
        store=True,
        help="Weighted 0-100 rating: 40% on-time delivery + 40% quality + "
        "20% lead-time efficiency. Example: 90% on-time, 100% quality, "
        "5-day lead time -> ~89.",
    )
    notes = fields.Text(
        help="Free-text manual remarks, e.g. reason for a low score.",
    )

    @api.depends("on_time_delivery_rate", "quality_rate", "avg_lead_time")
    def _compute_score(self):
        """Weighted score: 40% delivery, 40% quality, 20% lead time efficiency."""
        for rec in self:
            # Lead time score: lower is better, cap at 30 days = 0%
            # Clamp both ends: early receipts (negative lead time) must not
            # push the score above 100 and break the progressbar max_value.
            lead_time_score = min(100, max(0, (30 - rec.avg_lead_time) / 30 * 100))
            rec.score = (
                rec.on_time_delivery_rate * 0.4
                + rec.quality_rate * 0.4
                + lead_time_score * 0.2
            )

    @api.model
    def _cron_compute_scorecards(self):
        """Cron: compute last month's scorecard for every vendor with an order
        confirmed in that month."""
        today = fields.Date.context_today(self)
        # Target the previous complete month so the run on the 1st is not an
        # empty window. period_start = first day of last month,
        # period_end = first day of this month (exclusive upper bound).
        period_end = today.replace(day=1)
        period_start = (period_end - timedelta(days=1)).replace(day=1)

        # Only vendors with an order confirmed in the window can get a card.
        # Taking them from the orders (not from supplier_rank > 0) also covers
        # vendors whose rank is still 0 because no vendor bill was posted yet.
        order_groups = self.env["purchase.order"]._read_group(
            self._get_period_order_domain(period_start, period_end),
            groupby=["partner_id"],
        )
        vendors = self.env["res.partner"].union(partner for (partner,) in order_groups)

        for vendor in vendors:
            # One savepoint per vendor: a failure (including a SQL error, which
            # aborts the whole transaction without one) only rolls back that
            # vendor's partial writes, and the remaining vendors still run.
            try:
                with self.env.cr.savepoint():
                    self._compute_vendor_scorecard(vendor, period_start, period_end)
            except Exception:  # noqa: BLE001 - isolate one vendor's failure
                _logger.warning(
                    "Vendor scorecard skipped for vendor %s (id %s); the other "
                    "vendors are still computed. Fix the cause below and run the "
                    "'Spreadsheet: Compute Vendor Scorecards' scheduled action again.",
                    vendor.display_name,
                    vendor.id,
                    exc_info=True,
                )

    @api.model
    def _get_period_order_domain(self, period_start, period_end):
        """Domain of the purchase orders confirmed in [period_start, period_end).

        saas-19.4 has no 'done' state: a finished order stays 'purchase' and is
        only flagged ``locked``, so 'purchase' covers open and locked orders.
        """
        return [
            ("state", "=", "purchase"),
            ("date_approve", ">=", period_start),
            ("date_approve", "<", period_end),
        ]

    def _compute_vendor_scorecard(self, vendor, period_start, period_end):
        """Compute and upsert one vendor's scorecard for a single period."""
        # Orders confirmed in the target period (open and locked alike).
        orders = self.env["purchase.order"].search(
            [("partner_id", "=", vendor.id)]
            + self._get_period_order_domain(period_start, period_end)
        )
        if not orders:
            return

        # Calculate metrics from purchase.report over the SAME window: keyed on
        # the confirmation date too (date_order is the RFQ deadline in 19.4 and
        # can fall in another month than the confirmation).
        report_data = self.env["purchase.report"]._read_group(
            domain=[("partner_id", "=", vendor.id)]
            + self._get_period_order_domain(period_start, period_end),
            groupby=[],
            aggregates=[
                "order_id:count_distinct",
                "untaxed_total:sum",
                "delay_pass:avg",
            ],
        )

        if not report_data:
            return

        order_count, total_amount, avg_delay = report_data[0]

        # On-time delivery: pickings received within expected date
        pickings = self.env["stock.picking"].search(
            [
                ("partner_id", "=", vendor.id),
                ("picking_type_code", "=", "incoming"),
                ("state", "=", "done"),
                ("date_done", ">=", period_start),
                ("date_done", "<", period_end),
            ]
        )
        on_time = sum(
            1
            for p in pickings
            if p.date_done and p.scheduled_date and p.date_done <= p.scheduled_date
        )
        on_time_rate = (on_time / len(pickings) * 100) if pickings else 100.0

        # Update or create scorecard
        existing = self.search(
            [
                ("partner_id", "=", vendor.id),
                ("date", "=", period_start),
            ],
            limit=1,
        )

        vals = {
            "partner_id": vendor.id,
            "date": period_start,
            "on_time_delivery_rate": on_time_rate,
            "avg_lead_time": avg_delay or 0.0,
            "total_orders": order_count or 0,
            "total_amount": total_amount or 0.0,
        }

        if existing:
            # quality_rate is a manual override (no QC integration yet): a
            # re-run for the same period must not reset it back to 100.
            existing.write(vals)
        else:
            vals["quality_rate"] = 100.0  # default until a QC module feeds it
            self.create(vals)

    def action_open_vendor_orders(self):
        """Open purchase orders for this vendor in this period."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Purchase Orders - %(name)s", name=self.partner_id.name),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [
                ("partner_id", "=", self.partner_id.id),
                ("state", "=", "purchase"),
            ],
        }
