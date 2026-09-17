# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.spreadsheet_public_share_oca.models.sheet_preview import (
    _col_letter,
    _parse_ref,
    _parse_zone,
    _resolve_display,
    border_to_css,
    render_sheets,
    resolve_cells,
    safe_color,
    safe_number,
    style_to_css,
)

from .fixtures import export_data_workbook, legacy_workbook


def _cells_by_ref(sheet):
    """Map "A1"-style references to rendered cells.

    Cells covered by a horizontal merge are not rendered, so the column index
    advances by the anchor's colspan (the fixtures use no vertical merges).
    """
    result = {}
    for row_index, row in enumerate(sheet["rows"]):
        col = 0
        for cell in row["cells"]:
            result[f"{_col_letter(col)}{row_index + 1}"] = cell
            col += cell["colspan"]
    return result


@tagged("post_install", "-at_install")
class TestPreviewHelpers(TransactionCase):
    """Pure helper functions used by the engine-less HTML preview."""

    def test_parse_ref_roundtrip(self):
        # A1 -> (0, 0); Z1 -> (25, 0); AA1 -> (26, 0)
        self.assertEqual(_parse_ref("A1"), (0, 0))
        self.assertEqual(_parse_ref("Z1"), (25, 0))
        self.assertEqual(_parse_ref("AA1"), (26, 0))
        self.assertEqual(_parse_ref("B3"), (1, 2))

    def test_parse_ref_invalid(self):
        self.assertEqual(_parse_ref("not-a-ref"), (0, 0))

    def test_col_letter_roundtrip(self):
        for col in (0, 1, 25, 26, 27, 51, 52, 701, 702):
            letter = _col_letter(col)
            parsed_col, _row = _parse_ref(letter + "1")
            self.assertEqual(parsed_col, col, f"roundtrip failed for col {col}")

    def test_parse_zone(self):
        self.assertEqual(_parse_zone("B2"), (1, 1, 1, 1))
        self.assertEqual(_parse_zone("B9:A2"), (0, 1, 1, 8))
        self.assertIsNone(_parse_zone("A1:B2:C3"))
        self.assertIsNone(_parse_zone("nope"))

    def test_resolve_display_literal(self):
        # Plain content is shown verbatim, not flagged as computed.
        self.assertEqual(_resolve_display("Hello"), ("Hello", False))
        self.assertEqual(_resolve_display(""), ("", False))
        self.assertEqual(_resolve_display(None), ("", False))

    def test_resolve_display_translation_label(self):
        # A pure translation label resolves to its literal text.
        self.assertEqual(_resolve_display('=_t("Total")'), ("Total", False))

    def test_resolve_display_formula(self):
        # Any other formula cannot be evaluated server-side -> flagged computed.
        display, computed = _resolve_display("=SUM(A1:A9)")
        self.assertEqual(display, "")
        self.assertTrue(computed)

    def test_squished_number_offsets(self):
        # 1, 2, 3, 4 squished as a base and a "+1" zone; 10 restarts the base.
        grid, _legacy, used_col, used_row = resolve_cells(
            {"A1": "1", "A2:A4": {"N": "+1"}, "A5": "10", "A6": {"N": "+5"}},
            25,
            99,
        )
        values = [grid[(0, row)]["display"] for row in range(6)]
        self.assertEqual(values, ["1", "2", "3", "4", "10", "15"])
        self.assertEqual((used_col, used_row), (0, 5))

    def test_squished_offsets_carry_outside_the_window(self):
        # Offsets beyond the visible rows still advance the running number.
        grid, _legacy, _col, used_row = resolve_cells(
            {"A1": "0", "A2:A200": {"N": "+1"}, "B1": {"N": "+1"}}, 25, 99
        )
        self.assertEqual(grid[(0, 99)]["display"], "99")
        self.assertNotIn((0, 150), grid)
        self.assertEqual(grid[(1, 0)]["display"], "200")
        self.assertEqual(used_row, 199)

    def test_formula_offsets_are_computed(self):
        grid, _legacy, _col, _row = resolve_cells(
            {"A1": "=B1*2", "A2:A3": {"R": "+R1"}}, 25, 99
        )
        self.assertTrue(all(grid[(0, row)]["computed"] for row in range(3)))

    def test_orphan_offset_is_not_invented(self):
        # An offset that follows plain text cannot be rebuilt: never show a
        # made-up number, flag it as a live value instead.
        grid, _legacy, _col, _row = resolve_cells(
            {"A1": "label", "A2": {"N": "+1"}}, 25, 99
        )
        self.assertEqual(grid[(0, 1)]["display"], "")
        self.assertTrue(grid[(0, 1)]["computed"])

    def test_style_css_whitelist(self):
        css = style_to_css(
            {
                "bold": True,
                "textColor": "red;background:url(https://evil.example/x)",
                "fillColor": "#abcdef",
                "fontSize": "12px;position:fixed",
                "align": "center;display:none",
                "verticalAlign": "middle",
            }
        )
        self.assertEqual(
            css, "font-weight:bold;background-color:#abcdef;vertical-align:middle;"
        )
        self.assertNotIn("url(", css)

    def test_safe_color(self):
        self.assertEqual(safe_color("#FFF"), "#FFF")
        self.assertEqual(safe_color("rgba(1, 2, 3, 0.5)"), "rgba(1, 2, 3, 0.5)")
        self.assertIsNone(safe_color("expression(alert(1))"))
        self.assertIsNone(safe_color("#12345"))
        self.assertIsNone(safe_color(None))

    def test_border_css_both_formats(self):
        self.assertEqual(
            border_to_css({"top": ["thin", "#000000"]}), "border-top:1px solid #000000;"
        )
        self.assertEqual(
            border_to_css({"left": {"style": "dashed", "color": "url(x)"}}),
            "border-left:1px dashed #000;",
        )

    def test_export_data_fixture_renders_values_and_styles(self):
        sheets = render_sheets(export_data_workbook())
        # The hidden sheet and the "Data" helper sheet never reach the preview.
        self.assertEqual([sheet["name"] for sheet in sheets], ["Report"])
        report = sheets[0]
        self.assertFalse(report["truncated"])
        self.assertEqual(report["col_widths"], [180, 90, 100, 100])
        self.assertEqual(report["rows"][0]["height"], 30)
        cells = _cells_by_ref(report)

        self.assertEqual(cells["A1"]["display"], "Quarter")
        self.assertIn("font-weight:bold;", cells["A1"]["style_css"])
        self.assertIn("background-color:#875a7b;", cells["A1"]["style_css"])
        self.assertIn("color:#FFFFFF;", cells["A1"]["style_css"])
        self.assertIn("font-size:13pt;", cells["A1"]["style_css"])
        self.assertIn("text-align:center;", cells["B1"]["style_css"])
        # =_t("...") label, merged over C1:D1, styled through the zone map.
        self.assertEqual(cells["C1"]["display"], "Notes")
        self.assertEqual(cells["C1"]["colspan"], 2)
        self.assertIn("color:rgb(13, 71, 161);", cells["C1"]["style_css"])
        # Squished number run 1..4 and its current-format border.
        self.assertEqual(
            [cells[f"A{row}"]["display"] for row in range(2, 6)],
            ["1", "2", "3", "4"],
        )
        self.assertIn("border-bottom:2px solid #FF0000;", cells["A2"]["style_css"])
        # Formulas (full or squished) are honest live values.
        self.assertTrue(all(cells[f"B{row}"]["computed"] for row in range(2, 6)))
        # Row 6 is hidden by the author.
        self.assertEqual(len(report["rows"]), 5)
        self.assertNotIn(
            "confidential row",
            [cell["display"] for row in report["rows"] for cell in row["cells"]],
        )

    def test_legacy_fixture_still_renders(self):
        sheets = render_sheets(legacy_workbook())
        self.assertEqual(len(sheets), 1)
        cells = _cells_by_ref(sheets[0])
        self.assertEqual(cells["A1"]["display"], "Title")
        self.assertIn("font-weight:bold;", cells["A1"]["style_css"])
        self.assertIn("color:#123456;", cells["A1"]["style_css"])
        self.assertIn("border-top:1px solid #000000;", cells["A1"]["style_css"])
        self.assertTrue(cells["B1"]["computed"])
        self.assertEqual(cells["A2"]["display"], "Plain")
        self.assertEqual(cells["B2"]["display"], "")

    def test_skips_data_sheet(self):
        sheets = render_sheets(
            {
                "sheets": [
                    {"name": "Data", "cells": {"A1": {"content": "secret"}}},
                    {"name": "Report", "cells": {"A1": {"content": "Visible"}}},
                ]
            }
        )
        self.assertEqual([sheet["name"] for sheet in sheets], ["Report"])

    def test_merges_hide_covered_cells(self):
        sheets = render_sheets(
            {
                "sheets": [
                    {
                        "name": "Report",
                        "cells": {
                            "A1": {"content": "Title"},
                            "B1": {"content": "dropped"},
                        },
                        "merges": ["A1:B1"],
                    }
                ]
            }
        )
        first_row_cells = sheets[0]["rows"][0]["cells"]
        # B1 is hidden by the merge, so only the anchor cell remains.
        self.assertEqual(len(first_row_cells), 1)
        self.assertEqual(first_row_cells[0]["colspan"], 2)

    def test_hidden_rows_and_columns_are_skipped(self):
        sheets = render_sheets(
            {
                "version": "18.4.14",
                "sheets": [
                    {
                        "name": "Staff",
                        "cells": {
                            "A1": "Name",
                            "B1": "Salary",
                            "C1": "Team",
                            "A2": "Ann",
                            "B2": "5000",
                            "C2": "Sales",
                            "A3": "hidden row",
                            "A4": "folded row",
                            "A5": "Bob",
                        },
                        "cols": {"0": {"size": 150}, "1": {"isHidden": True}},
                        "rows": {"2": {"isHidden": True}},
                        "headerGroups": {
                            "ROW": [{"start": 3, "end": 3, "isFolded": True}],
                            "COL": [],
                        },
                    }
                ],
            }
        )
        sheet = sheets[0]
        displays = [[cell["display"] for cell in row["cells"]] for row in sheet["rows"]]
        self.assertEqual(displays, [["Name", "Team"], ["Ann", "Sales"], ["Bob", ""]])
        self.assertEqual(sheet["col_widths"], [150, 100])

    def test_merge_over_hidden_headers_keeps_the_grid_aligned(self):
        sheets = render_sheets(
            {
                "sheets": [
                    {
                        "name": "Merges",
                        "cells": {"A1": "Title", "A2": "left", "D2": "right"},
                        "merges": ["A1:C1"],
                        # Column A holds the merge content but is hidden.
                        "cols": {"0": {"isHidden": True}},
                    }
                ]
            }
        )
        rows = sheets[0]["rows"]
        # The merge is anchored on its first visible cell and still shows the
        # content of its top-left cell.
        self.assertEqual(rows[0]["cells"][0]["display"], "Title")
        self.assertEqual(rows[0]["cells"][0]["colspan"], 2)
        widths = sum(cell["colspan"] for cell in rows[0]["cells"])
        self.assertEqual(widths, len(sheets[0]["col_widths"]))
        self.assertEqual(
            [cell["display"] for cell in rows[1]["cells"]], ["", "", "right"]
        )

    def test_huge_numbers_never_break_the_page(self):
        self.assertIsNone(safe_number(10**400, 1, 400))
        self.assertIsNone(safe_number(float("inf"), 1, 400))
        self.assertEqual(safe_number(12, 1, 400), 12)
        sheets = render_sheets(
            {
                "styles": {"1": {"fontSize": 10**400, "bold": True}},
                "sheets": [
                    {
                        "name": "Huge",
                        "cells": {"A1": "x"},
                        "styles": {"A1": 1},
                        "cols": {"0": {"size": 10**400}},
                        "rows": {"0": {"size": -(10**400)}},
                    }
                ],
            }
        )
        self.assertNotIn("error", sheets[0])
        cell = sheets[0]["rows"][0]["cells"][0]
        self.assertEqual(cell["style_css"], "font-weight:bold;")
        self.assertEqual(sheets[0]["col_widths"], [100])
        self.assertIsNone(sheets[0]["rows"][0]["height"])

    def test_truncation_flag(self):
        # A cell far beyond the cap trips the truncation flag.
        big = render_sheets(
            {"sheets": [{"name": "Big", "cells": {"A1": "x", "AZ200": "y"}}]}
        )
        self.assertTrue(big[0]["truncated"])
        self.assertEqual(len(big[0]["rows"]), 100)
        self.assertEqual(len(big[0]["col_widths"]), 26)
        small = render_sheets({"sheets": [{"name": "Small", "cells": {"A1": "x"}}]})
        self.assertFalse(small[0]["truncated"])

    def test_malformed_parts_degrade_gracefully(self):
        errors = []
        sheets = render_sheets(
            {
                "sheets": [
                    # "cells" must be a mapping: this sheet cannot be previewed.
                    {"name": "Broken", "cells": ["A1"]},
                    # A malformed column entry is ignored (default width).
                    {"name": "Odd cols", "cells": {"A1": "x"}, "cols": {"0": 5}},
                    {"name": "Fine", "cells": {"A1": "ok"}},
                ]
            },
            on_error=lambda name, exc: errors.append(name),
        )
        self.assertEqual(
            [sheet["name"] for sheet in sheets], ["Broken", "Odd cols", "Fine"]
        )
        self.assertTrue(sheets[0]["error"])
        self.assertEqual(errors, ["Broken"])
        self.assertEqual(sheets[1]["col_widths"], [100])
        self.assertEqual(_cells_by_ref(sheets[2])["A1"]["display"], "ok")
        self.assertEqual(render_sheets("not a workbook"), [])
        self.assertEqual(render_sheets({"sheets": "nope"}), [])
