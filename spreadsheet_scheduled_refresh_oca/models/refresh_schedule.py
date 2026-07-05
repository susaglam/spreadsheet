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
    )
    interval_number = fields.Integer(
        default=1,
        required=True,
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
    )
    last_refresh = fields.Datetime(readonly=True)
    next_refresh = fields.Datetime(readonly=True)

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
