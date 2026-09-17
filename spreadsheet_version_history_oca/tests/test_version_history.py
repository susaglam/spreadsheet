# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json
import time
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import Form
from odoo.tests.common import TransactionCase, tagged

from ..models import spreadsheet_version as version_module
from ..models.spreadsheet_version import _bin_content
from .test_cell_data import LINEAR_TIME_LIMIT, RUNS_PLAIN, RUNS_SQUISHED


def _editor_workbook(cells, name="Sheet1"):
    """A workbook as the saas-19.4 editor saves it (plain-string cells)."""
    return {
        "version": "19.4.9",
        "sheets": [
            {
                "id": "sheet1",
                "name": name,
                "cells": cells,
                "styles": {"A1": 1},
                "formats": {},
                "borders": {},
            }
        ],
        "styles": {"1": {"bold": True}},
        "formats": {},
        "borders": {},
        "revisionId": "START_REVISION",
    }


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

    def test_diff_explains_unreadable_snapshot(self):
        corrupt = self.Version.create(
            {
                "name": "Corrupt",
                "spreadsheet_id": self.spreadsheet.id,
                "spreadsheet_data": base64.b64encode(b"not-json{").decode("ascii"),
            }
        )
        html = str(corrupt.diff_html)
        self.assertIn("unreadable", html)  # what failed
        self.assertIn("cannot be restored", html)  # why it matters
        self.assertIn("New Snapshot", html)  # how to fix it
        self.assertEqual(corrupt.cells_changed, 0)

    # -- saas-19.4 editor format (plain-string, squished cells) ---------------

    def test_build_cell_diff_string_cells(self):
        version_data = _editor_workbook({"A1": "x", "A2": "keep"})
        current_data = _editor_workbook({"A1": "y", "A2": "keep", "B1": "new"})
        diff = self.Version._build_cell_diff(version_data, current_data)
        self.assertEqual(diff["changed"], 1)
        self.assertEqual(diff["added"], 1)
        self.assertEqual(diff["removed"], 0)
        self.assertNotIn("alert-warning", diff["html"])

    def test_build_cell_diff_legacy_version_vs_string_current(self):
        legacy = {
            "sheets": [
                {
                    "name": "Sheet1",
                    "cells": {"A1": {"content": "same"}, "B1": {"content": "old"}},
                }
            ]
        }
        current = _editor_workbook({"A1": "same", "C1": "=A1"})
        diff = self.Version._build_cell_diff(legacy, current)
        self.assertEqual((diff["added"], diff["changed"], diff["removed"]), (1, 0, 1))

    def test_build_cell_diff_squished_runs(self):
        changed = dict(RUNS_PLAIN, B5="=A5*3")
        diff = self.Version._build_cell_diff(
            _editor_workbook(RUNS_SQUISHED), _editor_workbook(changed)
        )
        self.assertEqual((diff["added"], diff["changed"], diff["removed"]), (0, 1, 0))
        # the stored offset is shown as the formula it stands for
        self.assertIn("=A5*2+5", diff["html"])
        self.assertIn("=A5*3", diff["html"])
        same = self.Version._build_cell_diff(
            _editor_workbook(RUNS_SQUISHED), _editor_workbook(RUNS_PLAIN)
        )
        self.assertIn("No cell-level changes", same["html"])

    def test_build_cell_diff_warns_on_unexpandable_cells(self):
        version_data = _editor_workbook({"A1": "$5", "A2:A3": {"N": "+1"}})
        current_data = _editor_workbook({"A1": "$5"})
        diff = self.Version._build_cell_diff(version_data, current_data)
        self.assertIn("alert-warning", diff["html"])
        self.assertEqual(diff["removed"], 2)
        # a friendly placeholder instead of the internal storage syntax
        self.assertIn("compressed value", diff["html"])
        self.assertNotIn('{"N"', diff["html"])

    def test_build_cell_diff_malformed_data_does_not_raise(self):
        version_data = {"sheets": [{"cells": {"A1": "x"}}, "junk"]}
        diff = self.Version._build_cell_diff(version_data, [])
        self.assertEqual(diff["removed"], 1)

    def test_version_form_opens_for_editor_saved_spreadsheet(self):
        """Blocker: the form used to raise AttributeError on string cells."""
        sheet = self.Spreadsheet.create(
            {"name": "Editor Sheet", "spreadsheet_raw": _editor_workbook(RUNS_SQUISHED)}
        )
        sheet.action_create_snapshot(label="Before")
        version = sheet.version_ids
        sheet.spreadsheet_raw = _editor_workbook(dict(RUNS_PLAIN, A1="10", D1="n"))
        version.invalidate_recordset()
        form = Form(version)  # loads the form view and reads every field on it
        self.assertEqual(form.cells_added, 1)  # D1
        self.assertEqual(form.cells_changed, 1)  # A1: 1 -> 10
        self.assertEqual(form.cells_removed, 0)  # squished B2:B5 == plain B2..B5
        self.assertIn("<strong>10</strong>", str(form.diff_html))
        self.assertNotIn("alert-warning", str(form.diff_html))

    def test_compute_diff_survives_unexpected_error(self):
        version = self._make_version(self.raw)
        with (
            patch.object(
                self.registry["spreadsheet.version"],
                "_build_cell_diff",
                side_effect=ValueError("boom"),
            ),
            self.assertLogs(
                "odoo.addons.spreadsheet_version_history_oca.models.spreadsheet_version",
                level="WARNING",
            ),
        ):
            version.invalidate_recordset()
            html = str(version.diff_html)
        self.assertIn("could not be built", html)
        self.assertEqual(version.cells_changed, 0)

    def test_build_cell_diff_caps_listed_rows(self):
        version_data = _editor_workbook({f"A{row}": str(row) for row in range(1, 11)})
        with patch.object(version_module, "MAX_DIFF_ROWS", 3):
            diff = self.Version._build_cell_diff(version_data, _editor_workbook({}))
        self.assertEqual(diff["removed"], 10)  # counters include every difference
        self.assertEqual(diff["html"].count('<tr class="diff-'), 3)
        self.assertIn("7 more differences are not listed", diff["html"])

    def test_build_cell_diff_bounds_huge_range_keys(self):
        """Tiny keys standing for millions of cells must not be expanded:
        each is listed once as stored, with the 'too large' warning."""
        version_data = {
            "sheets": [
                {"name": f"S{index:02d}", "cells": {"A1:A500000": "x"}}
                for index in range(50)
            ]
        }
        diff = self.Version._build_cell_diff(version_data, {})
        self.assertEqual(diff["removed"], 50)
        self.assertEqual(diff["html"].count('<tr class="diff-'), 50)
        self.assertIn("too large to compare every cell", diff["html"])
        self.assertIn("S09, …", diff["html"])  # sheet list is shortened
        self.assertNotIn("S10", diff["html"].split("</div>")[0])

    def test_diff_of_crafted_snapshot_stays_bounded(self):
        """A user can store any JSON in a snapshot of their own and then read
        diff_html: chained legacy formula dependencies and long digit runs
        must neither blow up memory nor tie up the worker."""
        crafted = {
            "sheets": [
                {
                    "name": "Sheet1",
                    "cells": {
                        "A1": {
                            "formula": {
                                "text": "|0|" * 1000,
                                "dependencies": ["|1|" * 1000, "x" * 1000],
                            }
                        },
                        **{f"B{row}": "=" + "1" * 50000 + "a" for row in range(1, 6)},
                    },
                }
            ]
        }
        version = self._make_version(crafted)
        start = time.perf_counter()
        html = str(version.diff_html)
        self.assertLess(time.perf_counter() - start, LINEAR_TIME_LIMIT * 2)
        self.assertIn("too large to compare every cell", html)
        self.assertLess(len(html), 1000000)
        # vs the spreadsheet's A1 "hello" / B1 "world": A1 (kept as stored)
        # and B1 changed, B2..B5 removed
        self.assertEqual((version.cells_changed, version.cells_removed), (2, 4))
