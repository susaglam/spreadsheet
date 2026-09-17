# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

_ACCESS_LOGGER = "odoo.addons.base.models.ir_access"


@tagged("post_install", "-at_install")
class TestRefreshScheduleAccess(TransactionCase):
    """Spreadsheet users manage only their own schedules; managers manage all."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        user_groups = "base.group_user,spreadsheet_oca.group_user"
        cls.user_a = new_test_user(cls.env, login="refresh_user_a", groups=user_groups)
        cls.user_b = new_test_user(cls.env, login="refresh_user_b", groups=user_groups)
        cls.manager = new_test_user(
            cls.env,
            login="refresh_manager",
            groups="base.group_user,spreadsheet_oca.group_manager",
        )
        cls.spreadsheet = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Owned by A", "owner_id": cls.user_a.id}
        )
        cls.Schedule = cls.env["spreadsheet.refresh.schedule"]
        # Created through user A's own rights, as from the UI.
        cls.schedule_a = cls.Schedule.with_user(cls.user_a).create(
            {"name": "Schedule of A", "spreadsheet_id": cls.spreadsheet.id}
        )

    def test_owner_can_edit_own_schedule(self):
        schedule = self.schedule_a.with_user(self.user_a)
        schedule.write({"name": "Renamed by owner", "interval_number": 3})
        self.assertEqual(schedule.name, "Renamed by owner")
        self.assertIn(
            self.schedule_a.id,
            self.Schedule.with_user(self.user_a).search([]).ids,
        )

    @mute_logger(_ACCESS_LOGGER)
    def test_other_user_cannot_edit_or_delete(self):
        other = self.schedule_a.with_user(self.user_b)
        with self.assertRaises(AccessError):
            other.write({"name": "Hijacked"})
        with self.assertRaises(AccessError):
            other.write({"active": False})
        with self.assertRaises(AccessError):
            other.unlink()
        self.assertFalse(
            self.Schedule.with_user(self.user_b).search(
                [("id", "=", self.schedule_a.id)]
            ),
            "Another user's schedule must not even be listed",
        )
        self.schedule_a.invalidate_recordset()
        self.assertTrue(self.schedule_a.exists())
        self.assertEqual(self.schedule_a.name, "Schedule of A")
        self.assertTrue(self.schedule_a.active)

    def test_manager_can_edit_and_delete_any_schedule(self):
        schedule = self.schedule_a.with_user(self.manager)
        schedule.write({"name": "Fixed by manager"})
        self.assertEqual(schedule.name, "Fixed by manager")
        schedule.unlink()
        self.assertFalse(self.schedule_a.exists())

    def test_cron_still_processes_every_users_schedule(self):
        """The owner restriction must not hide schedules from the cron."""
        self.schedule_a.next_refresh = False
        self.Schedule.with_user(self.manager).create(
            {"name": "Schedule of manager", "spreadsheet_id": self.spreadsheet.id}
        )
        cron = self.env.ref(
            "spreadsheet_scheduled_refresh_oca.ir_cron_refresh_spreadsheets"
        )
        # The cron runs as its configured user (root), which bypasses ir.access.
        self.Schedule.with_user(cron.user_id)._cron_refresh_spreadsheets()
        self.assertTrue(self.schedule_a.last_refresh)
