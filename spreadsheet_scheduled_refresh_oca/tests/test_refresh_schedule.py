# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from psycopg2 import IntegrityError

from odoo import fields
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import SQL, mute_logger

_MODEL_LOGGER = "odoo.addons.spreadsheet_scheduled_refresh_oca.models.refresh_schedule"
_DEFAULT_PARAM = "spreadsheet_scheduled_refresh.default_interval_hours"


@tagged("post_install", "-at_install")
class TestRefreshSchedule(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Schedule = cls.env["spreadsheet.refresh.schedule"]
        cls.spreadsheet = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Test Sheet"}
        )
        cls.spreadsheet_2 = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Test Sheet 2"}
        )

    def _make(self, **vals):
        base = {
            "name": "Schedule",
            "spreadsheet_id": self.spreadsheet.id,
        }
        base.update(vals)
        return self.Schedule.create(base)

    def _persisted_last_refresh(self, schedules):
        """Flush, then read last_refresh straight from the database.

        The flush is part of the check: after an unprotected database error the
        transaction is aborted and the flush itself fails.
        """
        self.env.flush_all()
        self.env.cr.execute(
            SQL(
                "SELECT id, last_refresh FROM spreadsheet_refresh_schedule "
                "WHERE id IN %s",
                tuple(schedules.ids),
            )
        )
        return dict(self.env.cr.fetchall())

    def test_schedule_next_from_now_on_create(self):
        """A fresh schedule (no last_refresh) computes next_refresh from now."""
        before = fields.Datetime.now()
        schedule = self._make(interval_number=6, interval_type="hours")
        expected = before + relativedelta(hours=6)
        self.assertTrue(schedule.next_refresh)
        # Allow a small drift window for execution time.
        self.assertAlmostEqual(
            schedule.next_refresh,
            expected,
            delta=timedelta(minutes=5),
        )

    def test_schedule_next_from_last_refresh(self):
        """When last_refresh is set, next_refresh is anchored to it."""
        anchor = fields.Datetime.now() - timedelta(days=10)
        schedule = self._make(interval_number=2, interval_type="days")
        schedule.last_refresh = anchor
        schedule._schedule_next()
        self.assertEqual(schedule.next_refresh, anchor + relativedelta(days=2))

    def test_write_interval_reschedules(self):
        """Editing the interval recomputes next_refresh."""
        schedule = self._make(interval_number=1, interval_type="days")
        first = schedule.next_refresh
        schedule.write({"interval_number": 3, "interval_type": "weeks"})
        self.assertNotEqual(schedule.next_refresh, first)
        expected = (schedule.last_refresh or fields.Datetime.now()) + relativedelta(
            weeks=3
        )
        self.assertAlmostEqual(
            schedule.next_refresh, expected, delta=timedelta(minutes=5)
        )

    def test_interval_must_be_positive(self):
        """The CHECK constraint blocks non-positive intervals."""
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                self._make(interval_number=0, interval_type="hours")

    def test_default_interval_from_config(self):
        """Omitting the interval seeds it from the config parameter (hours)."""
        self.env["ir.config_parameter"].sudo().set_str(_DEFAULT_PARAM, "12")
        schedule = self.Schedule.create(
            {"name": "Defaulted", "spreadsheet_id": self.spreadsheet.id}
        )
        self.assertEqual(schedule.interval_type, "hours")
        self.assertEqual(schedule.interval_number, 12)

    def test_form_defaults_follow_config(self):
        """The form proposes the configured interval, not a hard-coded 1 Days.

        The web client sends every field of a new record on save, defaults
        included, so the configured default has to be the field default itself.
        """
        self.env["ir.config_parameter"].sudo().set_str(_DEFAULT_PARAM, "6")
        defaults = self.Schedule.default_get(["interval_number", "interval_type"])
        self.assertEqual(defaults["interval_number"], 6)
        self.assertEqual(defaults["interval_type"], "hours")
        # Saving exactly what the form proposed keeps the configured interval.
        schedule = self.Schedule.create(
            dict(defaults, name="From form", spreadsheet_id=self.spreadsheet.id)
        )
        self.assertEqual(
            (schedule.interval_number, schedule.interval_type), (6, "hours")
        )

    def test_default_interval_falls_back_when_setting_invalid(self):
        """A non-positive setting never yields a value the CHECK would reject."""
        self.env["ir.config_parameter"].sudo().set_str(_DEFAULT_PARAM, "0")
        schedule = self.Schedule.create(
            {"name": "Fallback", "spreadsheet_id": self.spreadsheet.id}
        )
        self.assertEqual(schedule.interval_number, 24)
        self.assertEqual(schedule.interval_type, "hours")

    def test_cron_selects_due_and_null_skips_inactive(self):
        """Cron refreshes due + never-run schedules, skipping inactive ones."""
        now = fields.Datetime.now()
        due = self._make(name="Due", interval_number=1, interval_type="days")
        due.next_refresh = now - timedelta(hours=1)
        never = self._make(name="Never")
        never.next_refresh = False
        future = self._make(name="Future")
        future.next_refresh = now + timedelta(days=5)
        inactive = self._make(name="Inactive")
        inactive.next_refresh = now - timedelta(hours=1)
        inactive.active = False

        refreshed = []
        original = type(self.Schedule)._refresh_spreadsheet

        def _spy(self):
            refreshed.append(self.id)
            return original(self)

        with patch.object(type(self.Schedule), "_refresh_spreadsheet", _spy):
            self.Schedule._cron_refresh_spreadsheets()

        self.assertIn(due.id, refreshed)
        self.assertIn(never.id, refreshed)
        self.assertNotIn(future.id, refreshed)
        self.assertNotIn(inactive.id, refreshed)

    def test_cron_isolates_failing_schedule(self):
        """A schedule that raises does not stop the others from refreshing."""
        now = fields.Datetime.now()
        bad = self._make(name="Bad", spreadsheet_id=self.spreadsheet.id)
        bad.next_refresh = now - timedelta(hours=1)
        good = self._make(name="Good", spreadsheet_id=self.spreadsheet_2.id)
        good.next_refresh = now - timedelta(hours=1)

        original = type(self.Schedule)._refresh_spreadsheet

        def _maybe_fail(self):
            if self.id == bad.id:
                raise ValueError("boom")
            return original(self)

        with (
            patch.object(type(self.Schedule), "_refresh_spreadsheet", _maybe_fail),
            mute_logger(_MODEL_LOGGER),
        ):
            # Must not propagate the exception.
            self.Schedule._cron_refresh_spreadsheets()

        self.assertTrue(good.last_refresh, "Good schedule should still refresh")
        self.assertFalse(bad.last_refresh, "Failing schedule must not update")

    def test_cron_survives_database_error(self):
        """A database error on one schedule does not abort the whole batch.

        Without a per-schedule savepoint the failed statement leaves the
        transaction aborted, so every later schedule fails as well
        (InFailedSqlTransaction) and nothing can be flushed any more.
        """
        now = fields.Datetime.now()
        # Created first -> lowest id -> processed first by the cron (_order=id).
        bad = self._make(name="Bad DB", spreadsheet_id=self.spreadsheet.id)
        bad.next_refresh = now - timedelta(hours=1)
        good = self._make(name="Good DB", spreadsheet_id=self.spreadsheet_2.id)
        good.next_refresh = now - timedelta(hours=1)

        original = type(self.Schedule)._refresh_spreadsheet

        def _db_error(rec):
            if rec.id == bad.id:
                # A real PostgreSQL error (division_by_zero), not a Python one.
                rec.env.cr.execute(SQL("SELECT 1/0"))
            return original(rec)

        with (
            patch.object(type(self.Schedule), "_refresh_spreadsheet", _db_error),
            mute_logger(_MODEL_LOGGER, "odoo.sql_db"),
        ):
            self.Schedule._cron_refresh_spreadsheets()

        persisted = self._persisted_last_refresh(bad | good)
        self.assertTrue(
            persisted[good.id], "A later schedule must still refresh and persist"
        )
        self.assertFalse(persisted[bad.id], "The failing schedule must not update")

    def test_cron_rolls_back_partial_write_of_failing_schedule(self):
        """An error raised after the write must not leave a half-done refresh."""
        now = fields.Datetime.now()
        bad = self._make(name="Half done", spreadsheet_id=self.spreadsheet.id)
        bad.next_refresh = now - timedelta(hours=1)
        good = self._make(name="Complete", spreadsheet_id=self.spreadsheet_2.id)
        good.next_refresh = now - timedelta(hours=1)

        original = type(self.Schedule)._refresh_spreadsheet

        def _fail_after_write(rec):
            original(rec)
            if rec.id == bad.id:
                raise ValueError("boom after write")

        with (
            patch.object(
                type(self.Schedule), "_refresh_spreadsheet", _fail_after_write
            ),
            mute_logger(_MODEL_LOGGER),
        ):
            self.Schedule._cron_refresh_spreadsheets()

        persisted = self._persisted_last_refresh(bad | good)
        self.assertTrue(persisted[good.id])
        self.assertFalse(
            persisted[bad.id],
            "The failing schedule's last_refresh write must be rolled back so it "
            "stays due and is retried on the next run",
        )

    def test_refresh_updates_and_sends_bus(self):
        """_refresh_spreadsheet sends the bus payload and advances timestamps."""
        schedule = self._make(interval_number=1, interval_type="hours")
        sent = {}

        def _fake_bus_send(self, notification_type, payload, subchannel=None):
            sent["type"] = notification_type
            sent["payload"] = payload
            sent["subchannel"] = subchannel

        with patch.object(type(self.spreadsheet), "_bus_send", _fake_bus_send):
            schedule._refresh_spreadsheet()

        self.assertEqual(sent["type"], "refresh_data")
        self.assertEqual(sent["subchannel"], "spreadsheet_oca")
        self.assertEqual(sent["payload"]["id"], self.spreadsheet.id)
        self.assertIn("timestamp", sent["payload"])
        self.assertTrue(schedule.last_refresh)
        self.assertTrue(schedule.next_refresh)
