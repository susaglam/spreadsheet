# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_PARAM = "spreadsheet_scheduled_refresh.default_interval_hours"
FALLBACK_INTERVAL_HOURS = 24


class SpreadsheetRefreshSchedule(models.Model):
    _name = "spreadsheet.refresh.schedule"
    _description = "Scheduled Spreadsheet Data Refresh"

    name = fields.Char(
        required=True,
        help="A short label to recognise this schedule in the list, for example "
        "'Sales dashboard - every 6 hours'. It only identifies the schedule and "
        "does not change the spreadsheet itself.",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to pause this schedule without deleting it. The cron skips "
        "inactive schedules, so open sheets stop receiving refresh signals until "
        "you enable it again.",
    )
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        required=True,
        ondelete="cascade",
        help="The spreadsheet whose data sources this schedule refreshes.",
    )
    interval_number = fields.Integer(
        default=lambda self: self._default_interval_number(),
        required=True,
        help="How often to refresh, combined with the interval type. "
        "Example: 6 with Hours refreshes every 6 hours. New schedules start "
        "from the default interval set in Settings > Spreadsheet.",
    )
    interval_type = fields.Selection(
        [
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        # Hours, because the configurable default interval is expressed in hours.
        default="hours",
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

    @api.model
    def _default_interval_number(self):
        """Default interval (in hours) taken from the settings.

        The default is applied through the field default rather than in
        ``create()``: the web client sends every field of a new record (defaults
        included) on save, so a ``create()``-time "no interval given" check never
        fired from the form and the setting was silently ignored.
        """
        hours = self.env["ir.config_parameter"].sudo().get_int(DEFAULT_INTERVAL_PARAM)
        if hours <= 0:
            # Unset, invalid or non-positive setting: never propose a value the
            # CHECK constraint would reject.
            return FALLBACK_INTERVAL_HOURS
        return hours

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
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
            # Read the label before the savepoint so the error log below never
            # depends on a query issued after a failure.
            label = f"{schedule.name} (id={schedule.id})"
            try:
                # One savepoint per schedule. A database error raised while
                # refreshing one schedule (constraint, serialization failure,
                # ...) otherwise leaves PostgreSQL in an aborted-transaction
                # state: every following schedule, and the cron's own
                # bookkeeping, would then fail with InFailedSqlTransaction. The
                # rollback also discards a failing schedule's partial writes.
                with self.env.cr.savepoint():
                    schedule._refresh_spreadsheet()
            except Exception:  # noqa: BLE001 - one bad schedule must not stop the batch
                _logger.exception(
                    "Scheduled spreadsheet refresh %s failed and was skipped. "
                    "The other due schedules are still processed; this one stays "
                    "due and is retried on the next cron run.",
                    label,
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
