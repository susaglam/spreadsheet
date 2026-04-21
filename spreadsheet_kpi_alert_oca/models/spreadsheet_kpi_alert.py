# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import operator as op

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

OPERATOR_MAP = {
    ">": op.gt,
    "<": op.lt,
    ">=": op.ge,
    "<=": op.le,
    "=": op.eq,
    "!=": op.ne,
}


class SpreadsheetKpiAlert(models.Model):
    _name = "spreadsheet.kpi.alert"
    _description = "Spreadsheet KPI Alert"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        string="Spreadsheet",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sheet_name = fields.Char(
        required=True,
        default="Sheet1",
        help="Name of the sheet containing the cell to monitor.",
    )
    cell_ref = fields.Char(
        string="Cell Reference",
        required=True,
        help="Cell reference (e.g., B2, C10) to monitor.",
    )
    operator = fields.Selection(
        [
            (">", "Greater than (>)"),
            ("<", "Less than (<)"),
            (">=", "Greater or equal (>=)"),
            ("<=", "Less or equal (<=)"),
            ("=", "Equal (=)"),
            ("!=", "Not equal (!=)"),
        ],
        required=True,
        default=">",
    )
    threshold_value = fields.Float(
        string="Threshold",
        required=True,
    )
    last_value = fields.Float(
        string="Last Known Value",
        readonly=True,
        help="Last evaluated cell value, updated by the JS client.",
    )
    last_checked = fields.Datetime(
        readonly=True,
    )
    last_triggered = fields.Datetime(
        readonly=True,
    )
    cooldown_hours = fields.Integer(
        string="Cooldown (hours)",
        default=24,
        help="Minimum hours between repeated alert notifications.",
    )
    notify_user_ids = fields.Many2many(
        "res.users",
        string="Notify Users",
        help="Users to notify when the threshold is breached.",
    )
    send_email = fields.Boolean(
        default=False,
        help="Also send an email notification when triggered.",
    )

    # Computed display fields
    alert_condition = fields.Char(
        compute="_compute_alert_condition",
        string="Condition",
    )

    def _compute_alert_condition(self):
        for rec in self:
            rec.alert_condition = (
                f"{rec.sheet_name}!{rec.cell_ref} {rec.operator} {rec.threshold_value}"
            )

    def update_cell_values(self, values):
        """Update last_value for multiple alerts at once.

        Called by the JS client via RPC. `values` is a dict mapping
        alert IDs to their evaluated cell values.

        Args:
            values: dict of {alert_id: float_value}
        """
        for alert in self.browse(list(values.keys())):
            val = values.get(alert.id)
            if val is not None:
                try:
                    alert.sudo().write({"last_value": float(val)})
                except (ValueError, TypeError) as exc:
                    _logger.debug(
                        "Skipping non-numeric KPI value for alert %s: %s",
                        alert.id,
                        exc,
                    )

    @api.model
    def _cron_check_kpi_thresholds(self):
        """Cron job: check all active alerts and trigger notifications."""
        alerts = self.search([("active", "=", True)])
        now = fields.Datetime.now()

        for alert in alerts:
            alert.last_checked = now

            # Check cooldown
            if alert.last_triggered and alert.cooldown_hours:
                hours_since = (now - alert.last_triggered).total_seconds() / 3600
                if hours_since < alert.cooldown_hours:
                    continue

            # Compare threshold
            compare_fn = OPERATOR_MAP.get(alert.operator)
            if not compare_fn:
                continue

            if compare_fn(alert.last_value, alert.threshold_value):
                alert._trigger_alert(now)

    def _trigger_alert(self, now):
        """Send notifications for a breached threshold."""
        self.ensure_one()
        self.last_triggered = now

        # Build notification message
        body = self.env._(
            "<p><strong>KPI Alert: %(name)s</strong></p>"
            "<p>Cell <code>%(sheet)s!%(cell)s</code> = "
            "<strong>%(value)s</strong> "
            "(threshold: %(operator)s %(threshold)s)</p>",
            name=self.name,
            sheet=self.sheet_name,
            cell=self.cell_ref,
            value=self.last_value,
            operator=self.operator,
            threshold=self.threshold_value,
        )

        # Post to spreadsheet chatter (visible to followers + specified users)
        partner_ids = self.notify_user_ids.mapped("partner_id").ids
        self.spreadsheet_id.message_post(
            body=body,
            subtype_xmlid="mail.mt_comment",
            partner_ids=partner_ids,
            message_type="comment",
        )

        # Optionally send email
        if self.send_email:
            template = self.env.ref(
                "spreadsheet_kpi_alert_oca.kpi_alert_email_template",
                raise_if_not_found=False,
            )
            if template:
                template.send_mail(self.id, force_send=True)

        _logger.info(
            "KPI Alert triggered: %s (cell %s!%s = %s, threshold %s %s)",
            self.name,
            self.sheet_name,
            self.cell_ref,
            self.last_value,
            self.operator,
            self.threshold_value,
        )

    def action_test_alert(self):
        """Manual test: trigger the alert regardless of threshold."""
        self.ensure_one()
        self._trigger_alert(fields.Datetime.now())
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Test Alert Sent"),
                "message": self.env._(
                    "Notification sent for %(name)s.", name=self.name
                ),
                "type": "success",
            },
        }
