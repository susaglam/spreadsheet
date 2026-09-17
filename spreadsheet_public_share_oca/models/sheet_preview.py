# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Engine-less HTML preview of an o-spreadsheet workbook.

The server has no o-spreadsheet engine, so the public page renders a static
table from the stored JSON. Two JSON shapes must be understood:

* LEGACY (integer ``version``): every cell is a dict
  ``{"content": "...", "style": 3, "border": 1}``; the ids point at the
  top-level ``styles`` / ``borders`` maps.
* CURRENT (``Model.exportData()`` of the saas-19.4 editor, string ``version``
  such as ``"18.4.14"``): cells are plain strings, possibly *squished* - a key
  can be a zone (``"B2:B9"``) and a value can be an offset object
  (``{"N": "+1"}``) relative to the previous cell in column-major order. Styles
  and borders live in per-sheet zone maps (``sheet["styles"] = {"A1:B2": 5}``)
  pointing at the top-level ``styles`` / ``borders`` definitions.

Every value that ends up in an HTML ``style`` attribute is whitelisted (hex /
rgb colours, bounded numbers, enumerated keywords) so a crafted workbook cannot
inject CSS such as ``url(...)``.
"""

import math
import re

PREVIEW_MAX_COLS = 26
PREVIEW_MAX_ROWS = 100
DEFAULT_COL_WIDTH = 100

# Dashboard exports keep their pivot source data on a helper sheet named "Data"
# that feeds the scorecards. Its `isVisible` flag is unreliable across legacy
# exports (False / True / absent), so the name is the stable marker.
HIDDEN_HELPER_SHEET_NAMES = frozenset({"Data"})

_REF_RE = re.compile(r"^\$?([A-Z]{1,4})\$?(\d{1,7})$", re.IGNORECASE)
_T_LITERAL_RE = re.compile(r'^=_t\(\s*(["\'])(.*?)\1\s*\)$', re.DOTALL)
_INTEGER_LITERAL_RE = re.compile(r"^\s*([+-]?\d{1,15})(?:\.0*)?\s*$")
_OFFSET_RE = re.compile(r"^\s*[+-]?\d{1,15}(?:\.\d+)?\s*$")
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$", re.I)
_RGB_COLOR_RE = re.compile(
    r"^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*"
    r"(?:,\s*(?:0|1|0?\.\d{1,4})\s*)?\)$",
    re.I,
)
_NUMBER_STRING_RE = re.compile(r"^\s*\d{1,6}(?:\.\d{1,4})?\s*$")

_ALIGNMENTS = frozenset({"left", "center", "right"})
_VERTICAL_ALIGNMENTS = frozenset({"top", "middle", "bottom"})
_BORDER_STYLES = {
    "thin": ("1px", "solid"),
    "medium": ("2px", "solid"),
    "thick": ("3px", "solid"),
    "dashed": ("1px", "dashed"),
    "dotted": ("1px", "dotted"),
}
_BORDER_SIDES = ("top", "right", "bottom", "left")
_SQUISH_OFFSET_KEYS = frozenset({"N", "S", "R"})


# ---------------------------------------------------------------------------
# References and zones
# ---------------------------------------------------------------------------


def _parse_ref_strict(ref):
    """Return ``(col, row)`` (0-based) for an A1 reference, or None."""
    match = _REF_RE.match(ref.strip()) if isinstance(ref, str) else None
    if not match:
        return None
    col = 0
    for char in match.group(1).upper():
        col = col * 26 + (ord(char) - 64)
    row = int(match.group(2))
    if row < 1:
        return None
    return col - 1, row - 1


def _parse_ref(ref):
    """Lenient variant kept for backward compatibility: invalid -> (0, 0)."""
    return _parse_ref_strict(ref) or (0, 0)


def _col_letter(col):
    result = ""
    col += 1
    while col > 0:
        col -= 1
        result = chr(65 + (col % 26)) + result
        col //= 26
    return result


def _parse_zone(key):
    """Return ``(left, top, right, bottom)`` for ``"A1"`` / ``"A1:B3"``."""
    if not isinstance(key, str):
        return None
    parts = key.split(":")
    if len(parts) > 2:
        return None
    start = _parse_ref_strict(parts[0])
    end = _parse_ref_strict(parts[1]) if len(parts) == 2 else start
    if start is None or end is None:
        return None
    left, right = sorted((start[0], end[0]))
    top, bottom = sorted((start[1], end[1]))
    return left, top, right, bottom


def _iter_zone_positions(zone, max_col, max_row):
    """Yield ``(index, col, row)`` of a zone clipped to the preview window.

    ``index`` is the column-major position inside the full zone, which is the
    order o-spreadsheet uses when it squishes/unsquishes a range.
    """
    left, top, right, bottom = zone
    height = bottom - top + 1
    for col in range(left, min(right, max_col) + 1):
        for row in range(top, min(bottom, max_row) + 1):
            yield (col - left) * height + (row - top), col, row


# ---------------------------------------------------------------------------
# Display values
# ---------------------------------------------------------------------------


def _resolve_display(content):
    """Return (display_text, is_computed) for the engine-less HTML preview.

    Plain content shows verbatim; a pure translation label =_t("...") shows its
    literal text so header rows stay meaningful; any other formula is a value we
    cannot evaluate server-side (no o-spreadsheet engine), flagged so the
    template shows an honest em dash instead of a fake "f(x)".
    """
    if not content or not content.startswith("="):
        return content or "", False
    match = _T_LITERAL_RE.match(content)
    if match:
        return match.group(2), False
    return "", True


def _format_number(number):
    if isinstance(number, float) and number.is_integer():
        number = int(number)
    return str(number)


def _is_squish_offset(value):
    return isinstance(value, dict) and bool(_SQUISH_OFFSET_KEYS & set(value))


def _content_cell(content):
    display, computed = _resolve_display(content)
    return {"content": content, "display": display, "computed": computed}


def _computed_cell():
    """A value only the spreadsheet engine can produce (formula / offset)."""
    return {"content": "", "display": "", "computed": True}


def resolve_cells(cells, max_col, max_row):
    """Resolve a sheet's ``cells`` map into display values.

    :param cells: legacy ``{xc: {"content": ...}}`` or current (possibly
        squished) ``{xc_or_zone: str | {"N"|"S"|"R": ...}}`` map
    :param max_col: last 0-based column kept in the preview window
    :param max_row: last 0-based row kept in the preview window
    :return: ``(grid, legacy_ids, used_col, used_row)`` where ``grid`` maps
        ``(col, row)`` to ``{"content", "display", "computed"}``,
        ``legacy_ids`` maps ``(col, row)`` to the legacy ``{"style", "border"}``
        ids, and ``used_col`` / ``used_row`` are the highest 0-based indexes
        holding a cell (``-1`` when empty), unclipped.
    """
    entries = []
    for key, value in (cells or {}).items():
        zone = _parse_zone(key)
        if zone is not None:
            entries.append((zone, value))
    # o-spreadsheet (un)squishes column by column, top to bottom.
    entries.sort(key=lambda entry: (entry[0][0], entry[0][1]))

    grid = {}
    legacy_ids = {}
    used_col = used_row = -1
    # Mirror of the JS unsquisher strategy: "formula", "number" or "text".
    strategy = None
    previous_number = None
    for zone, value in entries:
        used_col = max(used_col, zone[2])
        used_row = max(used_row, zone[3])
        if value is None or value == "":
            continue
        if isinstance(value, dict) and not _is_squish_offset(value):
            # Legacy cell object: never squished, carries its own style ids.
            content = value.get("content")
            content = "" if content is None else str(content)
            for _index, col, row in _iter_zone_positions(zone, max_col, max_row):
                grid[(col, row)] = _content_cell(content)
                legacy_ids[(col, row)] = {
                    "style": value.get("style"),
                    "border": value.get("border"),
                }
            continue
        if isinstance(value, dict):
            offset = value.get("N")
            if (
                strategy == "number"
                and previous_number is not None
                and isinstance(offset, str)
                and _OFFSET_RE.match(offset)
                and not value.get("S")
                and not value.get("R")
            ):
                step = float(offset)
                for index, col, row in _iter_zone_positions(zone, max_col, max_row):
                    number = previous_number + step * (index + 1)
                    grid[(col, row)] = _content_cell(_format_number(number))
                size = (zone[2] - zone[0] + 1) * (zone[3] - zone[1] + 1)
                previous_number += step * size
            else:
                # A formula offset (or an offset we cannot rebuild safely):
                # only the engine knows the value.
                if strategy != "formula":
                    strategy = None
                for _index, col, row in _iter_zone_positions(zone, max_col, max_row):
                    grid[(col, row)] = _computed_cell()
            continue
        content = str(value)
        if content.startswith("="):
            strategy = "formula"
        else:
            integer = _INTEGER_LITERAL_RE.match(content)
            if integer:
                strategy = "number"
                previous_number = int(integer.group(1))
            else:
                strategy = "text"
                previous_number = None
        for _index, col, row in _iter_zone_positions(zone, max_col, max_row):
            grid[(col, row)] = _content_cell(content)
    return grid, legacy_ids, used_col, used_row


# ---------------------------------------------------------------------------
# Safe CSS
# ---------------------------------------------------------------------------


def safe_color(value):
    """Return ``value`` if it is a plain hex / rgb(a) colour, else None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if _HEX_COLOR_RE.match(value) or _RGB_COLOR_RE.match(value):
        return value
    return None


def safe_number(value, minimum, maximum):
    """Return a finite number within bounds (int when integral), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and _NUMBER_STRING_RE.match(value):
        value = float(value)
    if not isinstance(value, int | float):
        return None
    # JSON integers are unbounded: math.isfinite(10**400) raises OverflowError,
    # so only floats go through it and the bounds are compared exactly.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if not minimum <= value <= maximum:
        return None
    if float(value).is_integer():
        return int(value)
    return round(value, 2)


def style_to_css(style):
    """Convert an o-spreadsheet style definition into whitelisted CSS."""
    if not isinstance(style, dict):
        return ""
    css = []
    if style.get("bold"):
        css.append("font-weight:bold")
    if style.get("italic"):
        css.append("font-style:italic")
    decorations = []
    if style.get("underline"):
        decorations.append("underline")
    if style.get("strikethrough"):
        decorations.append("line-through")
    if decorations:
        css.append("text-decoration:" + " ".join(decorations))
    text_color = safe_color(style.get("textColor"))
    if text_color:
        css.append(f"color:{text_color}")
    fill_color = safe_color(style.get("fillColor"))
    if fill_color:
        css.append(f"background-color:{fill_color}")
    # o-spreadsheet font sizes are expressed in points.
    font_size = safe_number(style.get("fontSize"), 1, 400)
    if font_size:
        css.append(f"font-size:{font_size}pt")
    if style.get("align") in _ALIGNMENTS:
        css.append(f"text-align:{style['align']}")
    if style.get("verticalAlign") in _VERTICAL_ALIGNMENTS:
        css.append(f"vertical-align:{style['verticalAlign']}")
    if style.get("wrapping") == "wrap":
        css.append("white-space:normal")
    return "".join(f"{rule};" for rule in css)


def border_to_css(border):
    """Convert a border definition (legacy list or current dict) into CSS."""
    if not isinstance(border, dict):
        return ""
    css = ""
    for side in _BORDER_SIDES:
        spec = border.get(side)
        if isinstance(spec, dict):
            line_style, line_color = spec.get("style"), spec.get("color")
        elif isinstance(spec, list | tuple) and spec:
            line_style = spec[0]
            line_color = spec[1] if len(spec) > 1 else None
        else:
            continue
        width, line = _BORDER_STYLES.get(line_style, ("1px", "solid"))
        color = safe_color(line_color) or "#000"
        css += f"border-{side}:{width} {line} {color};"
    return css


def _zone_item_ids(zone_map, max_col, max_row):
    """Expand a per-sheet ``{zone: item_id}`` map inside the preview window."""
    result = {}
    if not isinstance(zone_map, dict):
        return result
    for key, item_id in zone_map.items():
        zone = _parse_zone(key)
        if zone is None or item_id in (None, "", False):
            continue
        for _index, col, row in _iter_zone_positions(zone, max_col, max_row):
            result[(col, row)] = item_id
    return result


def _lookup(definitions, item_id):
    if item_id in (None, "", False) or not isinstance(definitions, dict):
        return None
    return definitions.get(str(item_id))


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------


def is_previewable_sheet(sheet):
    """Hidden sheets and dashboard helper sheets never reach the preview.

    Rows and columns hidden inside a visible sheet are left out by
    ``render_sheet`` (see ``_hidden_headers``).
    """
    return (
        isinstance(sheet, dict)
        and sheet.get("isVisible", True) is not False
        and sheet.get("name") not in HIDDEN_HELPER_SHEET_NAMES
    )


def _header_size(headers, index):
    if not isinstance(headers, dict):
        return None
    header = headers.get(str(index)) or headers.get(index)
    if not isinstance(header, dict):
        return None
    return safe_number(header.get("size"), 1, 2000)


def _header_index(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _hidden_headers(headers, groups, last):
    """Return the 0-based indexes (up to ``last``) the author hid.

    ``exportData()`` flags a hidden row/column with ``isHidden`` in the
    ``rows`` / ``cols`` header maps; a folded row/column group
    (``headerGroups[dim] = [{"start", "end", "isFolded"}]``) hides its range
    as well, as it does in the editor.
    """
    hidden = set()
    if isinstance(headers, dict):
        for key, header in headers.items():
            index = _header_index(key)
            if (
                index is not None
                and 0 <= index <= last
                and isinstance(header, dict)
                and header.get("isHidden") is True
            ):
                hidden.add(index)
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict) or group.get("isFolded") is not True:
            continue
        start = _header_index(group.get("start"))
        end = _header_index(group.get("end"))
        if start is None or end is None:
            continue
        hidden.update(range(max(start, 0), min(end, last) + 1))
    return hidden


def _merge_spans(merges, max_col, max_row, hidden_cols=(), hidden_rows=()):
    """Return ``(spans, covered)`` for the merges inside the preview window.

    ``spans`` maps the rendered anchor of a merge (its first visible cell) to
    its ``colspan`` / ``rowspan`` over the visible rows and columns, and to the
    ``source`` cell holding the merge content (the top-left cell). ``covered``
    holds every other cell of the merges, which is not rendered.
    """
    spans = {}
    covered = set()
    for merge in merges:
        zone = _parse_zone(merge)
        if zone is None or zone[0] > max_col or zone[1] > max_row:
            continue
        left, top, right, bottom = zone
        right = min(right, max_col)
        bottom = min(bottom, max_row)
        cols = [col for col in range(left, right + 1) if col not in hidden_cols]
        rows = [row for row in range(top, bottom + 1) if row not in hidden_rows]
        for row in range(top, bottom + 1):
            for col in range(left, right + 1):
                covered.add((col, row))
        if not cols or not rows:
            continue
        anchor = (cols[0], rows[0])
        covered.discard(anchor)
        spans[anchor] = {
            "colspan": len(cols),
            "rowspan": len(rows),
            "source": (left, top),
        }
    return spans, covered


def render_sheet(sheet, styles, borders):
    """Return the template-ready structure of one sheet."""
    name = sheet.get("name")
    window_col = PREVIEW_MAX_COLS - 1
    window_row = PREVIEW_MAX_ROWS - 1
    grid, legacy_ids, used_col, used_row = resolve_cells(
        sheet.get("cells"), window_col, window_row
    )
    if used_col < 0:
        return {"name": name, "rows": [], "col_widths": [], "truncated": False}
    # A merged title keeps its full width even when only its anchor has content.
    merges = sheet.get("merges") if isinstance(sheet.get("merges"), list) else []
    for zone in filter(None, map(_parse_zone, merges)):
        used_col = max(used_col, zone[2])
        used_row = max(used_row, zone[3])

    truncated = used_col > window_col or used_row > window_row
    max_col = min(used_col, window_col)
    max_row = min(used_row, window_row)
    style_ids = _zone_item_ids(sheet.get("styles"), max_col, max_row)
    border_ids = _zone_item_ids(sheet.get("borders"), max_col, max_row)

    cols = sheet.get("cols")
    sheet_rows = sheet.get("rows")
    groups = sheet.get("headerGroups")
    groups = groups if isinstance(groups, dict) else {}
    # Rows and columns the author hid never reach the public page.
    hidden_cols = _hidden_headers(cols, groups.get("COL"), max_col)
    hidden_rows = _hidden_headers(sheet_rows, groups.get("ROW"), max_row)
    visible_cols = [col for col in range(max_col + 1) if col not in hidden_cols]
    visible_rows = [row for row in range(max_row + 1) if row not in hidden_rows]
    spans, covered = _merge_spans(merges, max_col, max_row, hidden_cols, hidden_rows)

    col_widths = [_header_size(cols, col) or DEFAULT_COL_WIDTH for col in visible_cols]
    rows_out = []
    for row in visible_rows:
        row_cells = []
        for col in visible_cols:
            if (col, row) in covered:
                continue
            span = spans.get((col, row))
            position = span["source"] if span else (col, row)
            cell = grid.get(position) or {
                "content": "",
                "display": "",
                "computed": False,
            }
            legacy = legacy_ids.get(position, {})
            style_id = style_ids.get(position, legacy.get("style"))
            border_id = border_ids.get(position, legacy.get("border"))
            style_css = style_to_css(_lookup(styles, style_id)) + border_to_css(
                _lookup(borders, border_id)
            )
            row_cells.append(
                dict(
                    cell,
                    style_css=style_css,
                    colspan=span["colspan"] if span else 1,
                    rowspan=span["rowspan"] if span else 1,
                )
            )
        rows_out.append({"height": _header_size(sheet_rows, row), "cells": row_cells})
    return {
        "name": name,
        "rows": rows_out,
        "col_widths": col_widths,
        "truncated": truncated,
    }


def render_sheets(raw, on_error=None):
    """Render every previewable sheet of a workbook.

    A sheet whose structure cannot be understood is returned with
    ``error=True`` (and reported through ``on_error``) instead of breaking the
    whole public page.
    """
    if not isinstance(raw, dict):
        return []
    styles = raw.get("styles") if isinstance(raw.get("styles"), dict) else {}
    borders = raw.get("borders") if isinstance(raw.get("borders"), dict) else {}
    sheets = raw.get("sheets") if isinstance(raw.get("sheets"), list) else []
    result = []
    for sheet in sheets:
        if not is_previewable_sheet(sheet):
            continue
        try:
            result.append(render_sheet(sheet, styles, borders))
        except (
            ArithmeticError,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            if on_error:
                on_error(sheet.get("name"), exc)
            result.append(
                {
                    "name": sheet.get("name"),
                    "rows": [],
                    "col_widths": [],
                    "truncated": False,
                    "error": True,
                }
            )
    return result
