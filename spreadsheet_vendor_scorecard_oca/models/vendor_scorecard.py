# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


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
    )
    date = fields.Date(
        default=fields.Date.context_today,
        required=True,
    )
    on_time_delivery_rate = fields.Float(
        string="On-Time Delivery (%)",
        help="Percentage of deliveries received on or before the expected date.",
    )
    quality_rate = fields.Float(
        string="Quality Rate (%)",
        help="Percentage of received items without quality issues.",
    )
    avg_lead_time = fields.Float(
        string="Avg Lead Time (days)",
        help="Average number of days from PO confirmation to receipt.",
    )
    total_orders = fields.Integer()
    total_amount = fields.Float()
    score = fields.Float(
        string="Overall Score",
        compute="_compute_score",
        store=True,
    )
    notes = fields.Text()

    @api.depends("on_time_delivery_rate", "quality_rate", "avg_lead_time")
    def _compute_score(self):
        """Weighted score: 40% delivery, 40% quality, 20% lead time efficiency."""
        for rec in self:
            # Lead time score: lower is better, cap at 30 days = 0%
            lead_time_score = max(0, (30 - rec.avg_lead_time) / 30 * 100)
            rec.score = (
                rec.on_time_delivery_rate * 0.4
                + rec.quality_rate * 0.4
                + lead_time_score * 0.2
            )

    @api.model
    def _cron_compute_scorecards(self):
        """Cron: compute monthly scorecards for all active vendors."""
        today = fields.Date.context_today(self)
        first_of_month = today.replace(day=1)

        vendors = self.env["res.partner"].search([("supplier_rank", ">", 0)])

        for vendor in vendors:
            # Count orders confirmed in this month
            orders = self.env["purchase.order"].search(
                [
                    ("partner_id", "=", vendor.id),
                    ("state", "in", ["purchase", "done"]),
                    ("date_approve", ">=", first_of_month),
                    ("date_approve", "<", today),
                ]
            )
            if not orders:
                continue

            # Calculate metrics from purchase.report
            report_data = self.env["purchase.report"]._read_group(
                domain=[
                    ("partner_id", "=", vendor.id),
                    ("state", "in", ["purchase", "done"]),
                    ("date_order", ">=", first_of_month),
                ],
                groupby=[],
                aggregates=[
                    "order_id:count_distinct",
                    "untaxed_total:sum",
                    "delay:avg",
                ],
            )

            if not report_data:
                continue

            order_count, total_amount, avg_delay = report_data[0]

            # On-time delivery: pickings received within expected date
            pickings = self.env["stock.picking"].search(
                [
                    ("partner_id", "=", vendor.id),
                    ("picking_type_code", "=", "incoming"),
                    ("state", "=", "done"),
                    ("date_done", ">=", first_of_month),
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
                    ("date", "=", first_of_month),
                ],
                limit=1,
            )

            vals = {
                "partner_id": vendor.id,
                "date": first_of_month,
                "on_time_delivery_rate": on_time_rate,
                "quality_rate": 100.0,  # Default; can be extended with quality module
                "avg_lead_time": avg_delay or 0,
                "total_orders": order_count,
                "total_amount": total_amount,
            }

            if existing:
                existing.write(vals)
            else:
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
                ("state", "in", ["purchase", "done"]),
            ],
        }
