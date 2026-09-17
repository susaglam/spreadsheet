# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import MagicMock, patch

from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestSpreadsheetSecurity(TransactionCase):
    """Security of spreadsheets and of their collaborative revisions.

    Revision commands are the cell contents of every edit, so
    ``spreadsheet.oca.revision`` must only be reachable through a spreadsheet
    the user can access, never directly.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Spreadsheet = cls.env["spreadsheet.spreadsheet"]
        cls.Revision = cls.env["spreadsheet.oca.revision"]
        cls.group_manager = cls.env.ref("spreadsheet_oca.group_manager")

        # Plain employee: internal, but no Spreadsheet access at all.
        cls.employee = new_test_user(
            cls.env, login="sheet_sec_employee", groups="base.group_user"
        )
        cls.owner = new_test_user(
            cls.env,
            login="sheet_sec_owner",
            groups="base.group_user,spreadsheet_oca.group_user",
        )
        # Spreadsheet user who is neither owner, reader nor contributor.
        cls.outsider = new_test_user(
            cls.env,
            login="sheet_sec_outsider",
            groups="base.group_user,spreadsheet_oca.group_user",
        )

        # "Leads" implies "Readers": a user in Leads is a Reader only by
        # implication (the group is NOT in their explicit group_ids).
        cls.reader_group = cls.env["res.groups"].create(
            {"name": "Spreadsheet security test - Readers"}
        )
        cls.lead_group = cls.env["res.groups"].create(
            {
                "name": "Spreadsheet security test - Leads",
                "implied_ids": [Command.link(cls.reader_group.id)],
            }
        )
        cls.implied_member = new_test_user(
            cls.env,
            login="sheet_sec_implied",
            groups="base.group_user,spreadsheet_oca.group_user",
        )
        cls.implied_member.write({"group_ids": [Command.link(cls.lead_group.id)]})

        cls.sheet = cls.Spreadsheet.create(
            {
                "name": "Payroll 2026",
                "owner_id": cls.owner.id,
                "reader_group_ids": [Command.link(cls.reader_group.id)],
            }
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _revision_message(self, server_revision="START_REVISION", next_rev="rev-1"):
        return {
            "type": "REMOTE_REVISION",
            "clientId": "client-1",
            "serverRevisionId": server_revision,
            "nextRevisionId": next_rev,
            "commands": [
                {
                    "type": "UPDATE_CELL",
                    "sheetId": "sheet1",
                    "col": 0,
                    "row": 0,
                    "content": "Salary: 9000",
                }
            ],
        }

    def _sheet_revisions(self, sheet):
        return self.Revision.sudo().search(
            [("model", "=", sheet._name), ("res_id", "=", sheet.id)]
        )

    # ------------------------------------------------------------------
    # C2: revisions are not readable / forgeable directly
    # ------------------------------------------------------------------
    def test_employee_without_spreadsheet_group_cannot_read_revisions(self):
        self.assertTrue(
            self.sheet.with_user(self.owner).send_spreadsheet_message(
                self._revision_message()
            )
        )
        revision = self._sheet_revisions(self.sheet)
        self.assertEqual(len(revision), 1)

        revisions_as_employee = self.Revision.with_user(self.employee)
        self.assertFalse(revisions_as_employee.has_access("read"))
        with self.assertRaises(AccessError):
            revisions_as_employee.search_read([], ["commands"])
        with self.assertRaises(AccessError):
            revisions_as_employee.create(
                {
                    "model": self.sheet._name,
                    "res_id": self.sheet.id,
                    "type": "REMOTE_REVISION",
                    "commands": "{}",
                }
            )
        with self.assertRaises(AccessError):
            revision.with_user(self.employee).unlink()
        # nor through the spreadsheet itself
        with self.assertRaises(AccessError):
            self.sheet.with_user(self.employee).get_spreadsheet_data()
        with self.assertRaises(AccessError):
            self.sheet.with_user(self.employee).send_spreadsheet_message(
                self._revision_message("rev-1", "rev-2")
            )
        self.assertEqual(len(self._sheet_revisions(self.sheet)), 1)

    def test_spreadsheet_user_reads_revisions_only_through_spreadsheet(self):
        sheet_as_owner = self.sheet.with_user(self.owner)
        sheet_as_owner.send_spreadsheet_message(self._revision_message())

        data = sheet_as_owner.get_spreadsheet_data()
        self.assertEqual(data["mode"], "normal")
        self.assertEqual(len(data["revisions"]), 1)
        self.assertEqual(data["revisions"][0]["nextRevisionId"], "rev-1")
        self.assertEqual(data["revisions"][0]["serverRevisionId"], "START_REVISION")

        # Even the owner cannot bypass the spreadsheet to list revisions of
        # every spreadsheet, nor read the technical One2many directly.
        with self.assertRaises(AccessError):
            self.Revision.with_user(self.owner).search_read([], ["commands"])
        with self.assertRaises(AccessError):
            sheet_as_owner.read(["spreadsheet_revision_ids"])

        # A spreadsheet user without access to this spreadsheet gets nothing.
        with self.assertRaises(AccessError):
            self.sheet.with_user(self.outsider).get_spreadsheet_data()

    def test_reader_cannot_forge_revisions(self):
        sheet_as_reader = self.sheet.with_user(self.implied_member)
        self.assertEqual(sheet_as_reader.get_spreadsheet_data()["mode"], "readonly")
        with self.assertRaises(AccessError):
            sheet_as_reader.send_spreadsheet_message(self._revision_message())
        self.assertFalse(self._sheet_revisions(self.sheet))

    def test_raw_write_and_unlink_clean_revisions(self):
        sheet = self.Spreadsheet.create({"name": "Budget", "owner_id": self.owner.id})
        sheet_as_owner = sheet.with_user(self.owner)
        sheet_as_owner.send_spreadsheet_message(self._revision_message())
        self.assertEqual(len(self._sheet_revisions(sheet)), 1)

        # A reader may not reset the document (and so not wipe its history).
        sheet.write({"reader_ids": [Command.link(self.outsider.id)]})
        with self.assertRaises(AccessError):
            sheet.with_user(self.outsider).write({"spreadsheet_raw": {"sheets": []}})
        self.assertEqual(len(self._sheet_revisions(sheet)), 1)

        sheet_as_owner.write(
            {"spreadsheet_raw": {"sheets": [{"id": "sheet1", "name": "Sheet1"}]}}
        )
        self.assertFalse(self._sheet_revisions(sheet))

        sheet_as_owner.send_spreadsheet_message(self._revision_message())
        self.assertEqual(len(self._sheet_revisions(sheet)), 1)
        sheet_id = sheet.id
        sheet_as_owner.unlink()
        self.assertFalse(
            self.Revision.sudo().search(
                [("model", "=", "spreadsheet.spreadsheet"), ("res_id", "=", sheet_id)]
            )
        )

    # ------------------------------------------------------------------
    # SEC-GROUPS: sharing with a group reaches implied members
    # ------------------------------------------------------------------
    def test_implied_group_member_can_read_shared_spreadsheet(self):
        # The scenario only proves something if the membership is implied.
        self.assertNotIn(self.reader_group, self.implied_member.group_ids)
        self.assertIn(self.reader_group, self.implied_member.all_group_ids)

        sheet_as_member = self.sheet.with_user(self.implied_member)
        sheet_as_member.check_access("read")
        self.assertEqual(
            self.Spreadsheet.with_user(self.implied_member).search(
                [("id", "=", self.sheet.id)]
            ),
            self.sheet,
        )
        # Read-only share: no write.
        with self.assertRaises(AccessError):
            sheet_as_member.write({"name": "Hacked"})
        # Not shared with the outsider.
        self.assertFalse(
            self.Spreadsheet.with_user(self.outsider).search(
                [("id", "=", self.sheet.id)]
            )
        )

    def test_implied_group_member_can_edit_contributor_spreadsheet(self):
        sheet = self.Spreadsheet.create(
            {
                "name": "Team forecast",
                "owner_id": self.owner.id,
                "contributor_group_ids": [Command.link(self.reader_group.id)],
            }
        )
        sheet.with_user(self.implied_member).write({"name": "Team forecast Q3"})
        self.assertEqual(sheet.name, "Team forecast Q3")

    def test_manager_sees_import_modes_through_implied_user_group(self):
        manager = new_test_user(
            self.env,
            login="sheet_sec_manager",
            groups="base.group_user,spreadsheet_oca.group_manager",
        )
        self.assertNotIn(self.env.ref("spreadsheet_oca.group_user"), manager.group_ids)
        modes = self.env["spreadsheet.spreadsheet.import.mode"].with_user(manager)
        self.assertIn(
            self.env.ref("spreadsheet_oca.spreadsheet_import_mode_new"),
            modes.search([]),
        )

    # ------------------------------------------------------------------
    # SEC-ADMIN
    # ------------------------------------------------------------------
    def test_admin_is_spreadsheet_manager(self):
        admin = self.env.ref("base.user_admin")
        self.assertIn(admin, self.group_manager.user_ids)
        self.assertTrue(admin._has_group("spreadsheet_oca.group_manager"))
        self.assertIn(
            self.env.ref("base.user_root"),
            self.group_manager.with_context(active_test=False).user_ids,
        )

    # ------------------------------------------------------------------
    # BUG17: filename compute on several records
    # ------------------------------------------------------------------
    def test_filename_compute_multi_record(self):
        sheets = self.Spreadsheet.create(
            [
                {"name": "Budget", "owner_id": self.owner.id},
                {"name": "Forecast", "owner_id": self.owner.id},
            ]
        )
        sheets.invalidate_recordset(["filename"])
        self.assertEqual(sheets.mapped("filename"), ["Budget.json", "Forecast.json"])
        sheets._compute_filename()
        self.assertEqual(sheets[1].filename, "Forecast.json")

    # ------------------------------------------------------------------
    # L5: unknown model in a spreadsheet bus channel
    # ------------------------------------------------------------------
    def test_bus_channel_unknown_model_is_skipped(self):
        mock_wsrequest = MagicMock()
        mock_wsrequest.session.uid = self.owner.id
        with patch("odoo.addons.bus.models.ir_websocket.wsrequest", new=mock_wsrequest):
            channels = (
                self.env["ir.websocket"]
                .with_user(self.owner)
                ._build_bus_channel_list(
                    [
                        "spreadsheet_oca;no.such.model;1",
                        f"spreadsheet_oca;spreadsheet.spreadsheet;{self.sheet.id}",
                    ]
                )
            )
        # Compare tuples only: `tuple in list_of_records` would call
        # BaseModel.__eq__ with a tuple, which emits a warning.
        tuple_channels = [c for c in channels if isinstance(c, tuple)]
        db_name = self.env.registry.db_name
        self.assertIn(
            (db_name, "spreadsheet.spreadsheet", self.sheet.id, "spreadsheet_oca"),
            tuple_channels,
        )
        self.assertFalse([c for c in tuple_channels if "no.such.model" in c])

    def test_bus_channel_of_inaccessible_spreadsheet_is_not_granted(self):
        mock_wsrequest = MagicMock()
        mock_wsrequest.session.uid = self.outsider.id
        with patch("odoo.addons.bus.models.ir_websocket.wsrequest", new=mock_wsrequest):
            channels = (
                self.env["ir.websocket"]
                .with_user(self.outsider)
                ._build_bus_channel_list(
                    [f"spreadsheet_oca;spreadsheet.spreadsheet;{self.sheet.id}"]
                )
            )
        tuple_channels = [c for c in channels if isinstance(c, tuple)]
        self.assertNotIn(
            (
                self.env.registry.db_name,
                "spreadsheet.spreadsheet",
                self.sheet.id,
                "spreadsheet_oca",
            ),
            tuple_channels,
        )

    def _bus_tuples(self, user, channels, session_uid=None):
        mock_wsrequest = MagicMock()
        mock_wsrequest.session.uid = session_uid
        with patch("odoo.addons.bus.models.ir_websocket.wsrequest", new=mock_wsrequest):
            result = (
                self.env["ir.websocket"]
                .with_user(user)
                ._build_bus_channel_list(list(channels))
            )
        return [c for c in result if isinstance(c, tuple)]

    def test_bus_channel_of_non_internal_user_is_skipped_not_denied(self):
        # Raising AccessDenied here would abort the whole bus subscription
        # (chat, notifications...) of the portal/public session.
        portal = new_test_user(
            self.env, login="sheet_sec_portal", groups="base.group_portal"
        )
        public = self.env.ref("base.public_user")
        channel = f"spreadsheet_oca;spreadsheet.spreadsheet;{self.sheet.id}"
        forbidden = (
            self.env.registry.db_name,
            "spreadsheet.spreadsheet",
            self.sheet.id,
            "spreadsheet_oca",
        )
        for user, session_uid in ((portal, portal.id), (public, None)):
            with self.subTest(user=user.login):
                tuples = self._bus_tuples(user, [channel], session_uid)
                self.assertNotIn(forbidden, tuples)

    def test_bus_channel_with_trailing_garbage_is_not_granted(self):
        tuples = self._bus_tuples(
            self.owner,
            [f"spreadsheet_oca;spreadsheet.spreadsheet;{self.sheet.id};junk"],
            self.owner.id,
        )
        self.assertFalse([c for c in tuples if "spreadsheet_oca" in c])
