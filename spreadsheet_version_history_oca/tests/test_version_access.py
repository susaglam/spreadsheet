# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged

from ..models.spreadsheet_version import _bin_content

USER_GROUPS = "base.group_user,spreadsheet_oca.group_user"
MANAGER_GROUPS = "base.group_user,spreadsheet_oca.group_manager"


def _encode(raw):
    return base64.b64encode(json.dumps(raw).encode("utf-8")).decode("ascii")


@tagged("post_install", "-at_install")
class TestVersionAccess(TransactionCase):
    """A snapshot holds a full copy of its spreadsheet and can be restored over
    it, so every operation on it is scoped to the spreadsheet's own access:
    read to see it, write to create, edit, move or restore it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Spreadsheet = cls.env["spreadsheet.spreadsheet"]
        cls.Version = cls.env["spreadsheet.version"]
        cls.owner = new_test_user(cls.env, login="version_owner", groups=USER_GROUPS)
        cls.contributor = new_test_user(
            cls.env, login="version_contributor", groups=USER_GROUPS
        )
        cls.reader = new_test_user(cls.env, login="version_reader", groups=USER_GROUPS)
        cls.stranger = new_test_user(
            cls.env, login="version_stranger", groups=USER_GROUPS
        )
        cls.manager = new_test_user(
            cls.env, login="version_manager", groups=MANAGER_GROUPS
        )
        cls.raw = {"sheets": [{"name": "Sheet1", "cells": {"A1": "secret salary"}}]}
        cls.sheet = cls.Spreadsheet.create(
            {
                "name": "Payroll Private",
                "owner_id": cls.owner.id,
                "spreadsheet_raw": cls.raw,
                "contributor_ids": [Command.link(cls.contributor.id)],
                "reader_ids": [Command.link(cls.reader.id)],
            }
        )
        cls.version = cls.Version.create(
            {
                "name": "Approved v1",
                "spreadsheet_id": cls.sheet.id,
                "spreadsheet_data": _encode(cls.raw),
                "created_by_id": cls.owner.id,
            }
        )
        # A spreadsheet the stranger owns (editable by them), readable by the
        # contributor only.
        cls.stranger_sheet = cls.Spreadsheet.create(
            {
                "name": "Stranger Notes",
                "owner_id": cls.stranger.id,
                "spreadsheet_raw": {"sheets": [{"name": "S", "cells": {"A1": "x"}}]},
                "reader_ids": [Command.link(cls.contributor.id)],
            }
        )
        # A spreadsheet nobody but the stranger and managers can open.
        cls.hidden_sheet = cls.Spreadsheet.create(
            {
                "name": "Hidden Budget Sheet",
                "owner_id": cls.stranger.id,
                "spreadsheet_raw": {"sheets": [{"name": "S", "cells": {"A1": "y"}}]},
            }
        )

    def _reset_access_caches(self):
        self.env.flush_all()
        self.env.invalidate_all()
        self.env.transaction.invalidate_access_cache()

    # -- read ---------------------------------------------------------------

    def test_stranger_cannot_read_version_of_unreadable_spreadsheet(self):
        Version = self.Version.with_user(self.stranger)
        self.assertFalse(Version.search([("id", "=", self.version.id)]))
        rows = Version.search_read([], ["spreadsheet_data"])
        self.assertNotIn(self.version.id, [row["id"] for row in rows])
        with self.assertRaises(AccessError):
            self.version.with_user(self.stranger).read(["spreadsheet_data"])

    def test_reader_and_contributor_can_read_version(self):
        for user in (self.reader, self.contributor, self.owner):
            version = self.Version.with_user(user).search(
                [("id", "=", self.version.id)]
            )
            self.assertEqual(version, self.version, user.login)
            self.assertTrue(version.read(["spreadsheet_data"]), user.login)

    # -- create ---------------------------------------------------------------

    def test_cannot_create_version_on_spreadsheet_without_write_access(self):
        vals = {
            "name": "Planted",
            "spreadsheet_id": self.sheet.id,
            "spreadsheet_data": _encode({"sheets": [{"name": "S", "cells": {}}]}),
        }
        before = self.Version.search_count([("spreadsheet_id", "=", self.sheet.id)])
        # unreadable spreadsheet: refused without revealing its name
        with self.assertRaises(AccessError) as caught:
            self.Version.with_user(self.stranger).create(vals)
        self.assertNotIn(self.sheet.name, str(caught.exception))
        # readable but not editable: refused, and the message teaches
        with self.assertRaises(AccessError) as caught:
            self.Version.with_user(self.reader).create(vals)
        self.assertIn("contributor", str(caught.exception))
        # the snapshot button of a reader is refused the same way
        with self.assertRaises(AccessError):
            self.sheet.with_user(self.reader).action_create_snapshot(label="Mine")
        self.assertEqual(
            self.Version.search_count([("spreadsheet_id", "=", self.sheet.id)]),
            before,
        )

    def test_contributor_can_snapshot_edit_and_restore(self):
        sheet = self.sheet.with_user(self.contributor)
        sheet.action_create_snapshot(label="Contributor snap")
        version = self.Version.with_user(self.contributor).search(
            [("spreadsheet_id", "=", self.sheet.id), ("name", "=", "Contributor snap")]
        )
        self.assertEqual(len(version), 1)
        self.assertEqual(version.created_by_id, self.contributor)
        version.write({"note": "before the Q3 update", "version_label": "v2"})
        self.sheet.spreadsheet_raw = {
            "sheets": [{"name": "Sheet1", "cells": {"A1": "changed"}}]
        }
        self._reset_access_caches()
        version.action_restore()
        self._reset_access_caches()
        self.assertEqual(self.sheet.spreadsheet_raw, self.raw)

    def test_created_by_cannot_be_forged_on_create(self):
        version = self.Version.with_user(self.owner).create(
            {
                "name": "Forged",
                "spreadsheet_id": self.sheet.id,
                "spreadsheet_data": _encode(self.raw),
                "created_by_id": self.contributor.id,
            }
        )
        self.assertEqual(version.sudo().created_by_id, self.owner)

    # -- write / move -----------------------------------------------------------

    def test_stranger_cannot_write_foreign_version(self):
        version = self.version.with_user(self.stranger)
        for vals in (
            {"note": "hijacked"},
            {"spreadsheet_data": _encode({"sheets": []})},
            {"spreadsheet_id": self.stranger_sheet.id},
        ):
            with self.assertRaises(AccessError):
                version.write(vals)
        self._reset_access_caches()
        self.assertFalse(self.version.note)
        self.assertEqual(self.version.spreadsheet_id, self.sheet)

    def test_reader_cannot_write_or_restore_version(self):
        planted = {"sheets": [{"name": "Sheet1", "cells": {"A1": "=HACK()"}}]}
        version = self.version.with_user(self.reader)
        with self.assertRaises(AccessError):
            version.write({"note": "not mine"})
        with self.assertRaises(AccessError):
            version.write({"spreadsheet_data": _encode(planted)})
        with self.assertRaises(AccessError) as caught:
            version.action_restore()
        self.assertIn("contributor", str(caught.exception))
        self._reset_access_caches()
        self.assertEqual(self.sheet.spreadsheet_raw, self.raw)

    def test_contributor_cannot_move_version_to_spreadsheet_they_cannot_edit(self):
        version = self.version.with_user(self.contributor)
        # read-only for the contributor
        with self.assertRaises(AccessError):
            version.write({"spreadsheet_id": self.stranger_sheet.id})
        # not even readable: the name must not leak through the message
        with self.assertRaises(AccessError) as caught:
            version.write({"spreadsheet_id": self.hidden_sheet.id})
        self.assertNotIn(self.hidden_sheet.name, str(caught.exception))
        self._reset_access_caches()
        self.assertEqual(self.version.spreadsheet_id, self.sheet)

    def test_owner_can_move_version_between_own_spreadsheets(self):
        other = self.Spreadsheet.with_user(self.owner).create(
            {"name": "Owner Copy", "spreadsheet_raw": self.raw}
        )
        self.version.with_user(self.owner).write({"spreadsheet_id": other.id})
        self.assertEqual(self.version.spreadsheet_id, other)

    def test_snapshot_content_and_author_are_frozen(self):
        version = self.version.with_user(self.owner)
        tampered = {"sheets": [{"name": "Sheet1", "cells": {"A1": "tampered"}}]}
        with self.assertRaises(UserError):
            version.write({"spreadsheet_data": _encode(tampered)})
        with self.assertRaises(UserError):
            version.write({"created_by_id": self.contributor.id})
        # rewriting the same author and editing the metadata are fine
        version.write({"created_by_id": self.owner.id, "note": "signed off"})
        self._reset_access_caches()
        self.assertEqual(self.version.note, "signed off")
        self.assertEqual(self.version.created_by_id, self.owner)
        self.assertEqual(
            json.loads(_bin_content(self.version.spreadsheet_data)), self.raw
        )

    # -- managers ---------------------------------------------------------------

    def test_manager_manages_versions_of_their_companies_only(self):
        version = self.version.with_user(self.manager)
        self.assertTrue(version.read(["spreadsheet_data"]))
        other_company = self.env["res.company"].create({"name": "Version Other Co"})
        foreign_sheet = self.Spreadsheet.create(
            {
                "name": "Other Company Sheet",
                "company_id": other_company.id,
                "spreadsheet_raw": self.raw,
            }
        )
        foreign_version = self.Version.create(
            {
                "name": "Other company snapshot",
                "spreadsheet_id": foreign_sheet.id,
                "spreadsheet_data": _encode(self.raw),
            }
        )
        self._reset_access_caches()
        self.assertFalse(
            self.Version.with_user(self.manager).search(
                [("id", "=", foreign_version.id)]
            )
        )
        version.unlink()
        self.assertFalse(self.version.exists())
