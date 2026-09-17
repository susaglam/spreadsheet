# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import itertools
import re
import time

from odoo.tests.common import TransactionCase, tagged

from ..tools.cell_data import (
    _COL_REFERENCE,
    _RANGE_REFERENCE,
    _ROW_REFERENCE,
    _TOKENIZE_WORK_PER_CHAR,
    MAX_EXPANDED_CELLS,
    MAX_EXPANSION_WORK,
    CompressedCell,
    ExpansionBudget,
    formula_number_end,
    js_number_to_string,
    sheet_cell_contents,
    tokenize,
    workbook_cell_contents,
    xc_sort_key,
)

# Regexes of the o-spreadsheet library shipped with saas-19.4, copied verbatim
# (o_spreadsheet.js: getFormulaNumberRegex(".") and helpers/references.ts).
# Python's backtracking engine gives the same matches as JS for them; the
# helper replaces them with linear-time equivalents, checked against these.
LIBRARY_FORMULA_NUMBER = re.compile(
    r"(?:^-?\d+(?:\.?\d*(?:(E|e)(\+|-)?\d+)?)?|^-?\.\d+)(?!\w|!)", re.ASCII
)
_LIBRARY_PREFIX = r"^\s*('.+'!|[^']+!)?"
LIBRARY_REFERENCES = (
    (
        _RANGE_REFERENCE,
        re.compile(
            _LIBRARY_PREFIX + r"(\$?([A-Z]{1,3})\$?([0-9]{1,7})"
            r"|(\$?[A-Z]{1,3})?\$?[0-9]{1,7}\s*:\s*(\$?[A-Z]{1,3})?\$?[0-9]{1,7}\s*"
            r"|\$?[A-Z]{1,3}(\$?[0-9]{1,7})?\s*:\s*\$?[A-Z]{1,3}(\$?[0-9]{1,7})?\s*"
            r")\Z",
            re.IGNORECASE,
        ),
    ),
    (_COL_REFERENCE, re.compile(_LIBRARY_PREFIX + r"\$?([A-Z]{1,3})\Z", re.I)),
    (_ROW_REFERENCE, re.compile(_LIBRARY_PREFIX + r"\$?([0-9]{1,7})\Z", re.I)),
)
# A quadratic pattern needs tens of seconds on the inputs of the timing tests
# below; a linear one needs milliseconds. The bound leaves room for slow CI.
LINEAR_TIME_LIMIT = 2.0

# The *_SQUISHED dicts below are real ``model.exportData()`` output of the
# o-spreadsheet library shipped with saas-19.4 (o_spreadsheet.js 19.4.9), i.e.
# exactly what the editor saves into ``spreadsheet_raw``. The *_PLAIN dicts are
# the same workbooks exported by that library without squishing.
RUNS_SQUISHED = {
    "A1": "1",
    "A2:A5": {"N": "+1"},
    "B1": "=A1*2+1",
    "B2:B5": {"N": "=|+1", "R": "+R1"},
    "C1": "9",
    "C2:C4": {"N": "-1"},
}
RUNS_PLAIN = {
    "A1": "1",
    "A2": "2",
    "A3": "3",
    "A4": "4",
    "A5": "5",
    "B1": "=A1*2+1",
    "B2": "=A2*2+2",
    "B3": "=A3*2+3",
    "B4": "=A4*2+4",
    "B5": "=A5*2+5",
    "C1": "9",
    "C2": "8",
    "C3": "7",
    "C4": "6",
}
MIXED_SQUISHED = {
    "A1": '=IF(B1>1,"a","no")',
    "A2": {"N": "+1", "S": ["=", "="], "R": "+R1"},
    "A3": {"N": "+1", "S": ["b", "="], "R": "+R1"},
    "A4": {"N": "+1", "S": ["=", "="], "R": "+R1"},
    "B1": "='Other Sheet'!$C$1+C1*0.1",
    "B2": {"N": "+0.1", "R": "=|+R1"},
    "B3": {"N": "+0.09999999999999998", "R": "=|+R1"},
    "B4": {"N": "+0.10000000000000003", "R": "=|+R1"},
    "C1": "hello",
    "C2": "45322",
    "C3": "5",
    "D1": "=SUM(C1:C3)",
    "D2": {"R": "C2:C4"},
    "D3": {"R": "C3:C5"},
    "D4": {"R": "C4:C6"},
    "E1": "=F2",
    "E2:E4": {"R": "+R1"},
    "F1": {"R": "G1"},
    "F2:F4": {"R": "+C1"},
}
MIXED_PLAIN = {
    "A1": '=IF(B1>1,"a","no")',
    "A2": '=IF(B2>2,"a","no")',
    "A3": '=IF(B3>3,"b","no")',
    "A4": '=IF(B4>4,"b","no")',
    "B1": "='Other Sheet'!$C$1+C1*0.1",
    "B2": "='Other Sheet'!$C$1+C2*0.2",
    "B3": "='Other Sheet'!$C$1+C3*0.3",
    "B4": "='Other Sheet'!$C$1+C4*0.4",
    "C1": "hello",
    "C2": "45322",
    "C3": "5",
    "D1": "=SUM(C1:C3)",
    "D2": "=SUM(C2:C4)",
    "D3": "=SUM(C3:C5)",
    "D4": "=SUM(C4:C6)",
    "E1": "=F2",
    "E2": "=F3",
    "E3": "=F4",
    "E4": "=F5",
    "F1": "=G1",
    "F2": "=H1",
    "F3": "=I1",
    "F4": "=J1",
}


@tagged("post_install", "-at_install")
class TestCellData(TransactionCase):
    def _contents(self, cells):
        contents, partial = sheet_cell_contents({"name": "S", "cells": cells})
        return contents, partial

    def test_legacy_object_cells(self):
        contents, partial = self._contents(
            {
                "A1": {"content": "hello", "style": 1},
                "B2": {"content": '=A1&"!"', "format": 2},
                "C3": {"style": 4},  # formatting only, no content
            }
        )
        self.assertEqual(contents, {"A1": "hello", "B2": '=A1&"!"'})
        self.assertFalse(partial)

    def test_very_old_formula_object_cells(self):
        contents, _partial = self._contents(
            {"A3": {"formula": {"text": "=|0|+|1|", "dependencies": ["A1", "B2"]}}}
        )
        self.assertEqual(contents, {"A3": "=A1+B2"})

    def test_current_string_cells(self):
        contents, partial = self._contents({"A1": "hello", "B1": "=A1", "C1": ""})
        self.assertEqual(contents, {"A1": "hello", "B1": "=A1"})
        self.assertFalse(partial)

    def test_range_key_repeats_the_value(self):
        contents, partial = self._contents({"A1:A3": "same", "B2:B3": "=$A$1"})
        self.assertEqual(
            contents,
            {"A1": "same", "A2": "same", "A3": "same", "B2": "=$A$1", "B3": "=$A$1"},
        )
        self.assertFalse(partial)

    def test_squished_number_and_formula_runs_match_library(self):
        contents, partial = self._contents(RUNS_SQUISHED)
        self.assertEqual(contents, RUNS_PLAIN)
        self.assertFalse(partial)

    def test_squished_strings_floats_columns_and_sheets_match_library(self):
        contents, partial = self._contents(MIXED_SQUISHED)
        self.assertEqual(contents, MIXED_PLAIN)
        self.assertFalse(partial)

    def test_plain_export_is_read_unchanged(self):
        for cells in (RUNS_PLAIN, MIXED_PLAIN):
            contents, partial = self._contents(cells)
            self.assertEqual(contents, cells)
            self.assertFalse(partial)

    def test_unexpandable_cells_are_kept_as_stored_and_flagged(self):
        contents, partial = self._contents(
            {
                "A1": "$5",  # formatted literal: its run cannot be rebuilt here
                "A2:A3": {"N": "+1"},
                "B1": {"R": "+R1"},  # offset without any base formula
                "not a cell": "x",
                "C1:C9999999": "too many cells",
            }
        )
        self.assertTrue(partial)
        self.assertEqual(contents["A1"], "$5")
        self.assertNotIsInstance(contents["A1"], CompressedCell)  # real content
        self.assertEqual(contents["A2"], '{"N": "+1"}')
        self.assertEqual(contents["B1"], '{"R": "+R1"}')
        # stored objects are flagged, so a UI can hide the storage syntax
        self.assertIsInstance(contents["A2"], CompressedCell)
        self.assertIsInstance(contents["B1"], CompressedCell)
        self.assertEqual(contents["not a cell"], "x")
        self.assertEqual(contents["C1:C9999999"], "too many cells")
        self.assertNotIn("C2", contents)  # the huge key was never expanded

    def test_malformed_workbooks_never_raise(self):
        for data in (None, [], {}, {"sheets": None}, {"sheets": ["junk", 3]}):
            sheets, partial = workbook_cell_contents(data)
            self.assertEqual(sheets, {})
            self.assertEqual(partial, set())
        sheets, _partial = workbook_cell_contents(
            {"sheets": [{"cells": {"A1": True, "B1": 2.5, "C1": [1]}}]}
        )
        self.assertEqual(sheets, {"#1": {"A1": "TRUE", "B1": "2.5", "C1": "[1]"}})
        # malformed legacy formula objects and offsets: kept as stored, flagged
        sheets, partial = workbook_cell_contents(
            {
                "sheets": [
                    {
                        "name": "S",
                        "cells": {
                            "A1": {"formula": {"text": "=|0|", "dependencies": 5}},
                            "B1": {"formula": {"text": 7, "dependencies": []}},
                            "C1": "=D1",
                            "C2": {"S": [1, {"x": 2}], "N": 3, "R": {"bad": 1}},
                            "D1": "1",
                            "D2": {"N": 1},  # parseFloat(1) === 1
                            "E1": "=1",
                            "E2:E3": {"N": "+1e999999"},
                        },
                    }
                ]
            }
        )
        self.assertEqual(partial, {"S"})
        cells = sheets["S"]
        self.assertIsInstance(cells["A1"], CompressedCell)
        self.assertIn('"dependencies": 5', cells["A1"])
        self.assertIsInstance(cells["B1"], CompressedCell)
        self.assertIsInstance(cells["C2"], CompressedCell)
        self.assertEqual((cells["D1"], cells["D2"]), ("1", "2"))
        self.assertEqual(cells["C1"], "=D1")

    def test_single_cell_reference_parts_collapse_like_library(self):
        """createRange() drops the second part of a range covering one cell,
        whatever its $ markers (o_spreadsheet.js, helpers/range.ts): the
        19.4.9 library exports "=$A$1:A1" as "=$A$1"."""
        contents, _partial = self._contents(
            {
                "A1": "=$A$1:A1",
                "B1": "=A1:$A$1",
                "C1": "=SUM($A$2:A2)",
                "D1": "=$B2:B2+1",
                "E1": "=A$3:A3",
                "G2": "=SUM($A$1:A1)",
                "G3": {"R": "$A$1:A2"},
            }
        )
        self.assertEqual(
            contents,
            {
                "A1": "=$A$1",
                "B1": "=A1",
                "C1": "=SUM($A$2)",
                "D1": "=$B2+1",
                "E1": "=A$3",
                "G2": "=SUM($A$1)",
                "G3": "=SUM($A$1:A2)",
            },
        )

    def test_expansion_budget_is_shared_across_sheets(self):
        budget = ExpansionBudget(cells=10)
        sheets, partial = workbook_cell_contents(
            {
                "sheets": [
                    {"name": "S1", "cells": {"A1:A6": "x"}},
                    {"name": "S2", "cells": {"A1:A6": "y"}},  # 6 > 4 left
                    {"name": "S3", "cells": {"B1": "z"}},
                ]
            },
            budget,
        )
        self.assertEqual(len(sheets["S1"]), 6)
        self.assertEqual(sheets["S2"], {"A1:A6": "y"})  # kept once, as stored
        self.assertEqual(sheets["S3"], {"B1": "z"})
        self.assertEqual(partial, {"S2"})
        self.assertTrue(budget.exhausted)
        self.assertEqual(budget.cells, 3)

    def test_huge_range_keys_never_exceed_the_workbook_cap(self):
        """A 20-byte key stands for 100000 cells: many such sheets must not
        expand more than MAX_EXPANDED_CELLS cells in total."""
        data = {
            "sheets": [
                {"name": f"S{index}", "cells": {"A1:A100000": "=B1+1"}}
                for index in range(20)
            ]
            + [
                {"name": f"H{index}", "cells": {"A1:A500000": "x"}}
                for index in range(200)
            ]
        }
        budget = ExpansionBudget()
        sheets, partial = workbook_cell_contents(data, budget)
        stored_keys = len(data["sheets"])
        total = sum(len(cells) for cells in sheets.values())
        self.assertLessEqual(total, MAX_EXPANDED_CELLS + stored_keys)
        self.assertTrue(budget.exhausted)
        self.assertGreaterEqual(budget.cells, 0)
        self.assertEqual(sheets["H0"], {"A1:A500000": "x"})
        self.assertEqual(len(partial), stored_keys - 2)  # S0 and S1 fit

    def test_work_budget_bounds_rerendered_offsets(self):
        """One small offset re-renders a long formula for every cell of its
        run: the work budget stops that, not only the cell count."""
        cells = {
            "A1": "=" + "+".join(["B1"] * 1000),
            "A2:A5000": {"R": "|".join(["+R1"] * 1000)},
        }
        budget = ExpansionBudget(work=200000)
        contents, partial = sheet_cell_contents({"cells": cells}, budget)
        self.assertTrue(partial)
        self.assertTrue(budget.exhausted)
        self.assertGreaterEqual(budget.work, 0)
        self.assertEqual(contents["A1"], cells["A1"])
        self.assertIsInstance(contents["A2:A5000"], CompressedCell)
        self.assertNotIn("A2", contents)

    def test_js_number_to_string(self):
        cases = {
            2.0: "2",
            -0.5: "-0.5",
            0.1 + 0.2: "0.30000000000000004",
            1e21: "1e+21",
            1e-7: "1e-7",
            0.000001: "0.000001",
            12345678901234567890.0: "12345678901234567000",
        }
        for value, expected in cases.items():
            self.assertEqual(js_number_to_string(value), expected)

    def test_sort_key_is_row_then_column(self):
        refs = ["A10", "B1", "A2", "AA1", "A1", "bad"]
        self.assertEqual(
            sorted(refs, key=xc_sort_key), ["A1", "B1", "AA1", "A2", "A10", "bad"]
        )

    # -- crafted payloads: bounded work, linear-time patterns ------------------

    def test_legacy_formula_dependencies_follow_library_migration(self):
        """Expected contents come from the 19.4.9 library loading these
        version-8 cells: its migration 0.9 replaces every "|i|" marker with
        dependency i, one dependency after the other, through a JS string
        replacement in which "$$" and "$&" are special."""
        contents, partial = self._contents(
            {
                "A1": {"formula": {"text": "=|0|+|1|", "dependencies": ["A2", "B2"]}},
                "A2": {"formula": {"text": "=|0|+|1|", "dependencies": ["|1|", "B2"]}},
                "A3": {
                    "formula": {"text": "=SUM(|0|)*|0|", "dependencies": ["$A$1:B2"]}
                },
                "A4": {"formula": {"text": '=|0|&"x"', "dependencies": ["$$C3"]}},
                "A5": {"formula": {"text": "=|0|+1", "dependencies": ["$&B1"]}},
            }
        )
        self.assertFalse(partial)
        self.assertEqual(
            contents,
            {
                "A1": "=A2+B2",
                "A2": "=B2+B2",
                "A3": "=SUM($A$1:B2)*$A$1:B2",
                "A4": '=$C3&"x"',
                "A5": "=|0|B1+1",
            },
        )
        # "$`" inserts the text before the match: never real data, refused
        contents, partial = self._contents(
            {"A1": {"formula": {"text": "=|0|", "dependencies": ["$`"]}}}
        )
        self.assertTrue(partial)
        self.assertIsInstance(contents["A1"], CompressedCell)

    def test_chained_legacy_formula_dependencies_are_bounded(self):
        """A 4 KB cell whose dependencies re-insert markers used to be
        rebuilt into a 216 million character string before any check."""
        cell = {
            "formula": {"text": "|0|" * 600, "dependencies": ["|1|" * 600, "x" * 600]}
        }
        budget = ExpansionBudget()
        start = time.perf_counter()
        sheets, partial = workbook_cell_contents(
            {"sheets": [{"name": "S", "cells": {"A1": cell}}]}, budget
        )
        self.assertLess(time.perf_counter() - start, LINEAR_TIME_LIMIT)
        self.assertEqual(partial, {"S"})
        self.assertTrue(budget.exhausted)
        self.assertGreaterEqual(budget.work, 0)
        content = sheets["S"]["A1"]
        self.assertLess(len(content), MAX_EXPANSION_WORK)
        self.assertIsInstance(content, CompressedCell)  # kept as stored
        # a dependency list that only makes the scans long is bounded too
        cell = {"formula": {"text": "=" + "x" * 100000, "dependencies": ["y"] * 100000}}
        budget = ExpansionBudget()
        contents, partial = sheet_cell_contents({"cells": {"A1": cell}}, budget)
        self.assertTrue(partial)
        self.assertTrue(budget.exhausted)

    def test_formula_number_scanner_matches_library_regex(self):
        for length in range(6):
            for chars in itertools.product("1.eE+-a! ", repeat=length):
                text = "".join(chars)
                for index in range(len(text) + 1):
                    # JS matches "^" against the remaining text
                    match = LIBRARY_FORMULA_NUMBER.match(text[index:])
                    expected = index + match.end() if match else None
                    self.assertEqual(
                        formula_number_end(text, index), expected, repr(text)
                    )

    def test_long_digit_runs_tokenize_in_linear_time(self):
        """The library number regex backtracks quadratically on a digit run
        followed by a letter: 50000 digits took about 45 s per cell."""
        digits = "1" * 50000
        start = time.perf_counter()
        tokens = tokenize("=" + digits + "a")
        tokenize("=" + digits + "." + digits + "e+" + digits + "a")
        self.assertLess(time.perf_counter() - start, LINEAR_TIME_LIMIT)
        self.assertEqual(tokens, [("OPERATOR", "="), ("SYMBOL", digits + "a")])

    def test_reference_patterns_match_library_in_linear_time(self):
        for length in range(6):
            for chars in itertools.product(" '!aA1:$", repeat=length):
                text = "".join(chars)
                for ours, library in LIBRARY_REFERENCES:
                    self.assertEqual(
                        bool(ours.match(text)), bool(library.match(text)), repr(text)
                    )
        # a stored reference offset starting with spaces was quadratic
        offset = " " * 20000 + "a!" * 20000
        start = time.perf_counter()
        contents, _partial = self._contents({"A1": "=B1", "A2": {"R": offset}})
        self.assertLess(time.perf_counter() - start, LINEAR_TIME_LIMIT)
        self.assertEqual(contents["A1"], "=B1")
        self.assertIn("A2", contents)

    def test_formula_tokenizing_is_charged_before_it_runs(self):
        formula = "=" + "+".join(["A1"] * 3000)  # 8999 characters
        cells = {f"A{row}": formula for row in range(1, 11)}
        budget = ExpansionBudget(work=len(formula) * _TOKENIZE_WORK_PER_CHAR * 3)
        contents, partial = sheet_cell_contents({"cells": cells}, budget)
        self.assertTrue(partial)
        self.assertTrue(budget.exhausted)
        self.assertGreaterEqual(budget.work, 0)
        # refused formulas are still listed, with their stored content
        self.assertEqual(contents, cells)
