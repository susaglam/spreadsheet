# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..models.spreadsheet_version import _bin_content


@tagged("post_install", "-at_install")
class TestVersionHistory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Spreadsheet = cls.env["spreadsheet.spreadsheet"]
        cls.Version = cls.env["spreadsheet.version"]
        cls.raw = {
            "sheets": [
                {
                    "name": "Sheet1",
                    "cells": {
                        "A1": {"content": "hello"},
                        "B1": {"content": "world"},
                    },
                }
            ]
        }
        cls.spreadsheet = cls.Spreadsheet.create(
            {"name": "Test Sheet", "spreadsheet_raw": cls.raw}
        )

    def _make_version(self, raw):
        encoded = base64.b64encode(json.dumps(raw).encode("utf-8")).decode("ascii")
        return self.Version.create(
            {
                "name": "V",
                "spreadsheet_id": self.spreadsheet.id,
                "spreadsheet_data": encoded,
            }
        )

    def test_build_cell_diff_added_changed_removed(self):
        version_data = {"sheets": [{"name": "S", "cells": {"A1": {"content": "x"}}}]}
        current_data = {
            "sheets": [
                {
                    "name": "S",
                    "cells": {
                        "A1": {"content": "y"},  # changed
                        "A2": {"content": "new"},  # added (absent in version)
                    },
                }
            ]
        }
        diff = self.Version._build_cell_diff(version_data, current_data)
        self.assertEqual(diff["changed"], 1)
        self.assertEqual(diff["added"], 1)
        self.assertEqual(diff["removed"], 0)
        self.assertIn("added", diff["html"])

    def test_diff_html_escapes_content(self):
        version_data = {
            "sheets": [
                {"name": "S", "cells": {"A1": {"content": "<script>x</script>"}}}
            ]
        }
        current_data = {"sheets": [{"name": "S", "cells": {"A1": {"content": "safe"}}}]}
        diff = self.Version._build_cell_diff(version_data, current_data)
        self.assertNotIn("<script>", diff["html"])
        self.assertIn("&lt;script&gt;", diff["html"])

    def test_diff_no_changes_message(self):
        diff = self.Version._build_cell_diff(self.raw, self.raw)
        self.assertEqual(diff["added"], 0)
        self.assertEqual(diff["changed"], 0)
        self.assertEqual(diff["removed"], 0)
        self.assertIn("No cell-level changes", diff["html"])

    def test_snapshot_roundtrip_and_size(self):
        version = self._make_version(self.raw)
        decoded = _bin_content(version.spreadsheet_data).decode("utf-8")
        self.assertEqual(json.loads(decoded), self.raw)
        self.assertEqual(version.size_bytes, len(json.dumps(self.raw).encode("utf-8")))

    def test_create_snapshot_action(self):
        result = self.spreadsheet.action_create_snapshot(label="Snap A")
        self.assertEqual(result["tag"], "display_notification")
        self.assertTrue(self.spreadsheet.version_ids)
        self.assertEqual(
            self.spreadsheet.version_count, len(self.spreadsheet.version_ids)
        )

    def test_create_snapshot_empty_raises(self):
        empty = self.Spreadsheet.create({"name": "Empty", "spreadsheet_raw": {}})
        with self.assertRaises(UserError):
            empty.action_create_snapshot()

    def test_restore_overwrites_current(self):
        old_raw = {"sheets": [{"name": "S", "cells": {"A1": {"content": "restored"}}}]}
        version = self._make_version(old_raw)
        version.action_restore()
        self.assertEqual(self.spreadsheet.spreadsheet_raw, old_raw)

    def test_restore_corrupt_raises(self):
        corrupt = self.Version.create(
            {
                "name": "Corrupt",
                "spreadsheet_id": self.spreadsheet.id,
                "spreadsheet_data": base64.b64encode(b"not-json{").decode("ascii"),
            }
        )
        with self.assertRaises(UserError):
            corrupt.action_restore()
