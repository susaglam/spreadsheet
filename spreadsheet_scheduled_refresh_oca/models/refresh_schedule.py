# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SpreadsheetRefreshSchedule(models.Model):
    _name = "spreadsheet.refresh.schedule"
    _description = "Scheduled Spreadsheet Data Refresh"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        required=True,
        ondelete="cascade",
        help="The spreadsheet whose data sources this schedule refreshes.",
    )
    interval_number = fields.Integer(
        default=1,
        required=True,
        help="How often to refresh, combined with the interval type. "
        "Example: 6 with Hours refreshes every 6 hours.",
    )
    interval_type = fields.Selection(
        [
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        default="days",
        required=True,
        help="Unit paired with the interval number (hours/days/weeks/months).",
    )
    last_refresh = fields.Datetime(
        readonly=True,
        help="When the cron last pushed a refresh signal. "
        "Read-only, set automatically.",
    )
    next_refresh = fields.Datetime(
        readonly=True,
        help="When the cron will next signal open sheets. Computed from the last "
        "refresh plus the interval; read-only.",
    )

    _interval_positive = models.Constraint(
        "CHECK(interval_number > 0)",
        "The refresh interval must be a positive number of intervals (e.g. 6 Hours).",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        default_hours = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_int("spreadsheet_scheduled_refresh.default_interval_hours")
        ) or 24
        for rec, vals in zip(records, vals_list, strict=False):
            # When the user did not specify any interval, honour the
            # configured default (expressed in hours) instead of the raw
            # field defaults (1 / days).
            if "interval_number" not in vals and "interval_type" not in vals:
                rec.write(
                    {
                        "interval_type": "hours",
                        "interval_number": default_hours,
                    }
                )
            rec._schedule_next()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "interval_number" in vals or "interval_type" in vals:
            for rec in self:
                rec._schedule_next()
        return res

    def _schedule_next(self):
        self.ensure_one()
        base = self.last_refresh or fields.Datetime.now()
        delta_args = {self.interval_type: self.interval_number}
        self.next_refresh = base + relativedelta(**delta_args)

    @api.model
    def _cron_refresh_spreadsheets(self):
        """Cron: check all schedules and trigger refresh for due ones."""
        now = fields.Datetime.now()
        schedules = self.search(
            [
                ("active", "=", True),
                "|",
                ("next_refresh", "<=", now),
                ("next_refresh", "=", False),
            ]
        )

        for schedule in schedules:
            try:
                schedule._refresh_spreadsheet()
            except Exception as e:
                _logger.error(
                    "Failed to refresh spreadsheet '%s': %s",
                    schedule.spreadsheet_id.name,
                    e,
                )

    def _refresh_spreadsheet(self):
        """Force a revision bump to trigger client-side data reload."""
        self.ensure_one()
        spreadsheet = self.spreadsheet_id
        # Send a bus notification to connected clients
        spreadsheet._bus_send(
            "refresh_data",
            {"id": spreadsheet.id, "timestamp": fields.Datetime.now().isoformat()},
            subchannel="spreadsheet_oca",
        )

        self.write(
            {
                "last_refresh": fields.Datetime.now(),
            }
        )
        self._schedule_next()

        _logger.info(
            "Refreshed spreadsheet '%s' (schedule: %s)", spreadsheet.name, self.name
        )
