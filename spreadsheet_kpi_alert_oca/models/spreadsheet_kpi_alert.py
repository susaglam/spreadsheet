# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import operator as op

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# A JS-synced last_value older than this is treated as stale (the cron ignores
# it) so alerts never fire on data a browser last evaluated days ago.
KPI_VALUE_MAX_AGE_HOURS = 24

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
        help="Last evaluated cell value, pushed by the JS client while a "
        "browser has the spreadsheet open.",
    )
    value_synced_at = fields.Datetime(
        string="Value Synced At",
        readonly=True,
        help="When the JS client last pushed an evaluated value for this cell. "
        "Distinguishes a never-synced cell from a genuine 0, and lets the cron "
        "ignore values older than the staleness window so alerts don't fire on "
        "data a browser evaluated days ago. Not needed for cells holding a "
        "literal number — those the cron reads directly from the stored sheet.",
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
        # JS sends dict keys as strings; cast to int so Odoo's bulk-update
        # SQL generator doesn't emit text='integer comparisons (Postgres
        # rejects them with "operator does not exist: integer = text").
        try:
            id_value_map = {int(k): v for k, v in values.items()}
        except (TypeError, ValueError) as exc:
            _logger.debug("Invalid alert id in update_cell_values payload: %s", exc)
            return
        for alert in self.browse(list(id_value_map.keys())):
            val = id_value_map.get(alert.id)
            if val is not None:
                try:
                    alert.sudo().write(
                        {
                            "last_value": float(val),
                            "value_synced_at": fields.Datetime.now(),
                        }
                    )
                except (ValueError, TypeError) as exc:
                    _logger.debug(
                        "Skipping non-numeric KPI value for alert %s: %s",
                        alert.id,
                        exc,
                    )

    def _resolve_current_value(self):
        """Return a trustworthy current value for the watched cell, or None.

        The server has no o-spreadsheet JS engine, so it cannot evaluate
        formulas. Strategy:
          (a) LITERAL read — if the watched cell holds a plain number in the
              stored spreadsheet_raw, read it directly (works fully unattended,
              the common KPI case).
          (b) FRESH SYNC — else, if the JS client pushed a value recently
              (value_synced_at within the staleness window), trust last_value.
          (c) None — otherwise (formula cell never synced, or a stale sync):
              the caller skips, so the cron never fires on 0.0-default or old
              data.
        Any parse failure degrades gracefully to (b)/(c) — never crashes the
        cron batch.
        """
        self.ensure_one()
        # (a) server-side literal read
        try:
            raw = self.spreadsheet_id.spreadsheet_raw or {}
            sheets = raw.get("sheets") or []
            sheet = next((s for s in sheets if s.get("name") == self.sheet_name), None)
            # The empty-sheet default name _('Sheet1') is translated on write
            # (Blad1 / Sayfa1), so a name mismatch with a single-sheet workbook
            # still points at the only sheet.
            if sheet is None and len(sheets) == 1:
                sheet = sheets[0]
            if sheet is not None:
                cell = (sheet.get("cells") or {}).get(self.cell_ref)
                # Cells are bare strings in the current native format and
                # {"content": ...} objects in the legacy format — handle both.
                content = cell.get("content") if isinstance(cell, dict) else cell
                if content is not None:
                    content = str(content).strip()
                    if content and not content.startswith("="):
                        return float(content)
        except Exception as exc:  # noqa: BLE001 - never let the cron crash
            _logger.debug(
                "Alert %s: literal cell read failed (%s); falling back to sync",
                self.id,
                exc,
            )
        # (b) fresh JS-synced value
        if self.value_synced_at:
            age_hours = (
                fields.Datetime.now() - self.value_synced_at
            ).total_seconds() / 3600
            if age_hours <= KPI_VALUE_MAX_AGE_HOURS:
                return self.last_value
        # (c) nothing trustworthy
        return None

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

            # Resolve a TRUSTWORTHY current value: prefer a server-side literal
            # read from the stored sheet (works fully unattended), else a fresh
            # JS-synced value; skip when neither exists. This removes both the
            # 0.0-default false positive AND the stale-synced false trigger.
            current_value = alert._resolve_current_value()
            if current_value is None:
                _logger.debug(
                    "Alert %s: no fresh KPI value (cell is a formula and no "
                    "recent client sync); skipping",
                    alert.id,
                )
                continue

            if compare_fn(current_value, alert.threshold_value):
                alert._trigger_alert(now, current_value)

    def _trigger_alert(self, now, value=None):
        """Send notifications for a breached threshold.

        `value` is the value the cron actually compared (a server-side literal
        read or a fresh sync); it falls back to last_value for manual test
        triggers so the message never shows a misleading stale number.
        """
        self.ensure_one()
        self.last_triggered = now
        current = value if value is not None else self.last_value

        # Build notification message
        body = self.env._(
            "<p><strong>KPI Alert: %(name)s</strong></p>"
            "<p>Cell <code>%(sheet)s!%(cell)s</code> = "
            "<strong>%(value)s</strong> "
            "(threshold: %(operator)s %(threshold)s)</p>",
            name=self.name,
            sheet=self.sheet_name,
            cell=self.cell_ref,
            value=current,
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
            current,
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
