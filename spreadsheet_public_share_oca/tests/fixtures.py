# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Workbook fixtures in both JSON formats the public preview must understand."""


def export_data_workbook():
    """Current format, as produced by ``Model.exportData()`` in saas-19.4.

    Cells are plain strings (possibly squished into zones / number offsets),
    styles and borders are per-sheet zone maps pointing at top-level ids.
    """
    return {
        "version": "18.4.14",
        "revisionId": "START_REVISION",
        "sheets": [
            {
                "id": "sheet1",
                "name": "Report",
                "colNumber": 26,
                "rowNumber": 100,
                "isVisible": True,
                # Row 6 is hidden by the author: it never reaches the preview.
                "rows": {"0": {"size": 30}, "5": {"isHidden": True}},
                "cols": {"0": {"size": 180}, "1": {"size": 90}},
                "merges": ["C1:D1"],
                "cells": {
                    "A1": "Quarter",
                    "B1": "Revenue",
                    "C1": '=_t("Notes")',
                    # A2..A5 hold 1, 2, 3, 4: exportData squishes the run into a
                    # base number followed by a "+1" offset zone.
                    "A2": "1",
                    "A3:A5": {"N": "+1"},
                    "B2": "=SUM(Data!A1:A9)",
                    "B3:B5": {"R": "+R1"},
                    "A6": "confidential row",
                },
                "styles": {"A1:B1": 1, "C1": 2},
                "formats": {},
                "borders": {"A2": 1},
                "conditionalFormats": [],
                "dataValidationRules": [],
                "figures": [],
                "tables": [],
                "areGridLinesVisible": True,
                "headerGroups": {},
                "comments": {},
            },
            {
                "id": "sheet2",
                "name": "Hidden notes",
                "isVisible": False,
                "cells": {"A1": "internal only"},
                "styles": {},
                "borders": {},
            },
            {
                "id": "sheet3",
                "name": "Data",
                "isVisible": True,
                "cells": {"A1": "42"},
                "styles": {},
                "borders": {},
            },
        ],
        "styles": {
            "1": {
                "bold": True,
                "fillColor": "#875a7b",
                "textColor": "#FFFFFF",
                "fontSize": 13,
                "align": "center",
            },
            "2": {"italic": True, "textColor": "rgb(13, 71, 161)"},
        },
        "formats": {},
        "borders": {"1": {"bottom": {"style": "medium", "color": "#FF0000"}}},
        "settings": {},
        "pivots": {},
        "lists": {},
    }


def legacy_workbook():
    """Legacy format (integer version): cells are dicts carrying style ids."""
    return {
        "version": 12,
        "sheets": [
            {
                "id": "sheet1",
                "name": "Legacy",
                "cells": {
                    "A1": {"content": "Title", "style": 1, "border": 1},
                    "B1": {"content": "=A1"},
                    "A2": {"content": "Plain"},
                },
                "merges": [],
                "cols": {},
                "rows": {},
            }
        ],
        "styles": {"1": {"bold": True, "textColor": "#123456"}},
        "borders": {"1": {"top": ["thin", "#000000"]}},
    }
