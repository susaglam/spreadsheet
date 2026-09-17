# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Read the cell contents of a stored o-spreadsheet workbook.

Two storage layouts reach the version history:

* legacy (o-spreadsheet < 18.1, older snapshots, hand-written demo JSON):
  ``sheet["cells"]["A1"]`` is an object ``{"content": "...", "style": 3}``;
* current (what the saas-19.4 editor saves through ``model.exportData()``):
  ``sheet["cells"]`` maps a cell, or a vertical run such as ``"B2:B9"``, to a
  bare string. Formatting lives in per-sheet zone maps (``sheet["styles"]``,
  ``sheet["formats"]``, ``sheet["borders"]``), not in the cells. The export is
  also "squished": a run of similar formulas or consecutive integers is stored
  as its first value followed by offset objects such as
  ``{"N": "=", "R": "+R1"}`` or ``{"N": "+1"}``.

:func:`workbook_cell_contents` turns both layouts into plain
``{"A1": "content"}`` maps. The squished part mirrors the ``Unsquisher``,
tokenizer and reference helpers of the o-spreadsheet library shipped with Odoo
saas-19.4 (``addons/spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js``).
A cell that cannot be expanded exactly is returned in its stored form and its
sheet is reported as partial, so callers can warn instead of crashing.

Expansion is bounded by an :class:`ExpansionBudget` shared by every sheet of a
workbook: a 20-byte key such as ``"A1:A500000"`` stands for half a million
cells, so without one budget a few such sheets would exhaust the worker. The
budget is charged BEFORE any costly step (tokenizing a formula, rebuilding a
pre-0.9 formula object, expanding a run), never after it, and every pattern
used here runs in linear time, so a small crafted payload cannot tie up the
worker either.
"""

import json
import logging
import re
from decimal import Decimal

_logger = logging.getLogger(__name__)

# Upper bounds for expanding ONE workbook, over all of its sheets. Entries
# beyond them are kept in their stored form (partial). Cells counts single
# cells and range keys alike; work counts, per expanded cell, the characters
# produced plus the formula tokens and offset characters processed, because
# one stored offset is re-applied to every cell of its range.
MAX_EXPANDED_CELLS = 250000
MAX_EXPANSION_WORK = 10000000
# Work charged per character of a formula before it is tokenized. Tokenizing
# runs in pure Python: measured at 0.6 to 2.4 microseconds per character
# depending on the formula shape, against about 0.15 per unit of rendering
# work. At 16 the most expensive shape costs about the same per unit, so the
# whole budget stays in the order of 1.5 s of CPU per workbook whatever it
# is spent on, and it still covers about 600 KB of stored formulas (the
# largest dashboard shipped with saas-19.4 holds 28 KB).
_TOKENIZE_WORK_PER_CHAR = 16

_MAX_ROW = 9999998  # o-spreadsheet: toCartesian() rejects row > 9999998
_OFFSET_KEYS = ("N", "S", "R")

# --------------------------------------------------------------------------
# References (helpers/references.ts)
# --------------------------------------------------------------------------
# The library writes the prefix as ^\s*('.+'!|[^']+!)? . Both match exactly
# the same strings (\s*[^']+ and [^']+ are the same language), but there the
# leading \s* and [^']+ can split a run of spaces in O(n) ways, each followed
# by an O(n) scan: quadratic on a stored reference offset such as
# "     ...a!a!a!". JS "." never matches a line terminator.
_JS_DOT = r"[^\n\r\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}]"
_SHEET_PREFIX = r"^(?:\s*'" + _JS_DOT + r"+'!|[^']+!|\s*)"
_RANGE_REFERENCE = re.compile(
    _SHEET_PREFIX + r"("
    r"\$?([A-Z]{1,3})\$?([0-9]{1,7})"
    r"|(\$?[A-Z]{1,3})?\$?[0-9]{1,7}\s*:\s*(\$?[A-Z]{1,3})?\$?[0-9]{1,7}\s*"
    r"|\$?[A-Z]{1,3}(\$?[0-9]{1,7})?\s*:\s*\$?[A-Z]{1,3}(\$?[0-9]{1,7})?\s*"
    r")\Z",
    re.IGNORECASE,
)
_COL_REFERENCE = re.compile(_SHEET_PREFIX + r"\$?([A-Z]{1,3})\Z", re.IGNORECASE)
_ROW_REFERENCE = re.compile(_SHEET_PREFIX + r"\$?([0-9]{1,7})\Z", re.IGNORECASE)
_SINGLE_CELL_REFERENCE = re.compile(r"^\$?([A-Z]{1,3})\$?([0-9]{1,7})\Z", re.I)
# The library writes these as ([A-Z]{1,3})+ / ([0-9]{1,7})+, which accept
# exactly the same strings; the flat form avoids exponential backtracking.
_COL_HEADER = re.compile(r"^\$?[A-Z]+\Z", re.IGNORECASE)
_ROW_HEADER = re.compile(r"^\$?[0-9]+\Z", re.IGNORECASE)
_CELL_PART = re.compile(r"(\$?)([A-Za-z]{1,3})(\$?)([0-9]{1,7})\Z")
_KEY_PART = re.compile(r"\s*([A-Za-z]{1,3})([0-9]{1,7})\s*\Z")

# --------------------------------------------------------------------------
# Tokenizer (formulas/tokenizer.ts, en_US formula locale)
# --------------------------------------------------------------------------
_OPERATORS = (
    "+",
    "-",
    "*",
    "/",
    ":",
    "=",
    "<>",
    ">=",
    ">",
    "<=",
    "<",
    "^",
    "&",
    "#",
    "%",
)
_SPECIAL_SPACES = frozenset(
    "\t\f\v\u00a0\u1680\u2000\u200a\u2028\u2029\u202f\u205f\u3000\ufeff "
)
_DIGIT_RUN = re.compile(r"[0-9]*")
_ASCII_WORD_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)
_PLAIN_NUMBER = re.compile(
    r"-?(?:\d+(?:,\d{3,})*(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?\Z", re.ASCII
)
_INVALID_REFERENCE = "#REF"
_NEW_LINE = "\n"
_BACKSLASH = "\\"
_NEW_LINES = re.compile(r"\r\n|\r")


class Unresolvable(Exception):
    """A stored cell whose value cannot be rebuilt exactly on the server."""


class CompressedCell(str):
    """Content kept as the JSON of a stored object that could not be expanded.

    It compares and hashes like the plain JSON text (so a diff still notices
    when the stored object changes), but lets a UI show a friendly
    placeholder instead of internal storage syntax such as ``{"N": "+1"}``.
    """

    __slots__ = ()


class ExpansionBudget:
    """Cells and work still allowed. Share one across a whole workbook."""

    def __init__(self, cells=MAX_EXPANDED_CELLS, work=MAX_EXPANSION_WORK):
        self.cells = cells
        self.work = work
        self.exhausted = False  # True once at least one entry was refused

    def take(self, cells=0, work=0):
        """Reserve ``cells`` and ``work``; False (and ``exhausted``) if over."""
        if cells > self.cells or work > self.work:
            self.exhausted = True
            return False
        self.cells -= cells
        self.work -= work
        return True


def _is_symbol_char(char):
    return char.isalnum() or char in "_.!$"


_SINGLE_CHAR_TOKENS = {
    ";": "ARRAY_ROW_SEPARATOR",
    ",": "ARG_SEPARATOR",
    "{": "LEFT_BRACE",
    "}": "RIGHT_BRACE",
    "(": "LEFT_PAREN",
    ")": "RIGHT_PAREN",
    "?": "DEBUGGER",
}


def tokenize(formula):
    """Split a formula into ``(type, value)`` tokens like ``tokenize()``."""
    text = _NEW_LINES.sub(_NEW_LINE, formula or "")
    tokens = []
    i = 0
    while i < len(text):
        token, i = _next_token(text, i)
        tokens.append(token)
    return tokens


def _next_token(text, i):
    char = text[i]
    if char == _NEW_LINE:
        return _tokenize_run(text, i, _NEW_LINE)
    if char in _SPECIAL_SPACES:
        return _tokenize_run(text, i, _SPECIAL_SPACES)
    if char in _SINGLE_CHAR_TOKENS:
        return (_SINGLE_CHAR_TOKENS[char], char), i + 1
    if text.startswith(_INVALID_REFERENCE, i):
        return ("INVALID_REFERENCE", _INVALID_REFERENCE), i + len(_INVALID_REFERENCE)
    operator = next((op for op in _OPERATORS if text.startswith(op, i)), None)
    if operator:
        return ("OPERATOR", operator), i + len(operator)
    if char == '"':
        return _tokenize_string(text, i)
    if char in "0123456789.":
        end = formula_number_end(text, i)
        if end is not None:
            return ("NUMBER", text[i:end]), end
    token, end = _tokenize_symbol(text, i)
    if token:
        return token, end
    return ("UNKNOWN", char), i + 1


def formula_number_end(text, i):
    """End of the number token starting at ``text[i]``, or ``None``.

    Gives the match of the library's formula number regex (en_US,
    ``getFormulaNumberRegex(".")``) anchored at ``i``::

        (?:^-?\\d+(?:\\.?\\d*(?:(E|e)(\\+|-)?\\d+)?)?|^-?\\.\\d+)(?!\\w|!)

    That regex backtracks through every split of a digit run when its final
    lookahead fails (``"1111…1a"``): quadratic time. This scanner walks the
    same alternatives in the same order, but only tries the ends that can
    pass the lookahead (an end inside a digit run is always followed by a
    digit), so it runs in linear time and returns the same end.
    """
    length = len(text)

    def free(end):  # (?!\w|!) with ASCII \w, as in JS
        return end >= length or (
            text[end] not in _ASCII_WORD_CHARS and text[end] != "!"
        )

    def exponent_end(pos):  # [Ee][+-]?\d+ then the lookahead, or None
        if pos >= length or text[pos] not in "Ee":
            return None
        start = pos + 1
        if start < length and text[start] in "+-":
            start += 1  # without the sign, \d+ would start on the sign: no match
        end = _DIGIT_RUN.match(text, start).end()
        return end if end > start and free(end) else None

    if i < length and text[i] == "-":
        i += 1
    if i >= length:
        return None
    if text[i] in "0123456789":
        integer_end = _DIGIT_RUN.match(text, i).end()
        if integer_end < length and text[integer_end] == ".":
            decimals_end = _DIGIT_RUN.match(text, integer_end + 1).end()
            end = exponent_end(decimals_end)
            if end is not None:
                return end
            if free(decimals_end):
                return decimals_end
        end = exponent_end(integer_end)
        if end is not None:
            return end
        return integer_end if free(integer_end) else None
    if text[i] == ".":
        end = _DIGIT_RUN.match(text, i + 1).end()
        if end > i + 1 and free(end):
            return end
    return None


def _tokenize_run(text, i, chars):
    end = i
    while end < len(text) and text[end] in chars:
        end += 1
    return ("SPACE", text[i:end]), end


def _tokenize_string(text, i):
    end = i + 1
    while end < len(text) and (text[end] != '"' or text[end - 1] == _BACKSLASH):
        end += 1
    if end < len(text):
        end += 1  # closing quote
    return ("STRING", text[i:end]), end


def _tokenize_symbol(text, i):
    start = i
    length = len(text)
    if text[i] == "'":
        last = text[i]
        i += 1
        while i < length:
            last = text[i]
            i += 1
            if last == "'":
                if i < length and text[i] == "'":
                    last = text[i]
                    i += 1
                else:
                    break
        if last != "'":
            return ("UNKNOWN", text[start:i]), i
    while i < length and _is_symbol_char(text[i]):
        i += 1
    value = text[start:i]
    if not value:
        return None, start
    if _RANGE_REFERENCE.match(value):
        return ("REFERENCE", value), i
    return ("SYMBOL", value), i


def _is_colon(value):
    return value == ":"


def _is_col_or_row_header(value):
    return bool(_COL_HEADER.match(value) or _ROW_HEADER.match(value))


# matchReference() state machine (range_tokenizer.ts):
# {state: {token type: [(next state, guard or None), ...]}}; 7 = matched.
_REFERENCE_MACHINE = {
    0: {
        "REFERENCE": [(2, None)],
        "NUMBER": [(4, None)],
        "SYMBOL": [(3, _COL_REFERENCE.match), (4, _ROW_REFERENCE.match)],
    },
    1: {
        "SPACE": [(1, None)],
        "NUMBER": [(7, None)],
        "REFERENCE": [(7, _SINGLE_CELL_REFERENCE.match)],
        "SYMBOL": [(7, _is_col_or_row_header)],
    },
    2: {"SPACE": [(2, None)], "OPERATOR": [(1, _is_colon)]},
    3: {"SPACE": [(3, None)], "OPERATOR": [(5, _is_colon)]},
    4: {"SPACE": [(4, None)], "OPERATOR": [(6, _is_colon)]},
    5: {
        "SPACE": [(5, None)],
        "SYMBOL": [(7, _COL_HEADER.match)],
        "REFERENCE": [(7, _SINGLE_CELL_REFERENCE.match)],
    },
    6: {
        "SPACE": [(6, None)],
        "NUMBER": [(7, None)],
        "REFERENCE": [(7, _SINGLE_CELL_REFERENCE.match)],
        "SYMBOL": [(7, _ROW_HEADER.match)],
    },
}


def _reference_transition(state, token_type, value):
    for next_state, guard in _REFERENCE_MACHINE[state].get(token_type, ()):
        if guard is None or guard(value):
            return next_state
    return None


def range_tokenize(formula):
    """Tokenize and merge ``A1`` ``:`` ``B2`` into one reference token."""
    tokens = tokenize(formula)
    result = []
    index = 0
    while index < len(tokens):
        state = 0
        head = index
        matched = ""
        merged = None
        while head < len(tokens):
            token_type, value = tokens[head]
            head += 1
            state = _reference_transition(state, token_type, value)
            if state is None:
                break
            matched += value
            if state == 7:
                merged = ("REFERENCE", matched)
                break
        if merged:
            result.append(merged)
            index = head
        else:
            result.append(tokens[index])
            index += 1
    return result


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------
def js_number_to_string(value):
    """``Number.prototype.toString()`` for a float."""
    try:
        value = float(value)
    except (OverflowError, TypeError, ValueError):
        return str(value)
    if value != value:
        return "NaN"
    if value in (float("inf"), float("-inf")):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "0"
    # repr() gives the same shortest round-trip digits as JS. Without an
    # exponent it is plain notation, which JS also uses in that range; only
    # the ".0" of an integral float differs. Fast path for the common case.
    text = repr(value)
    if "e" not in text:
        return text[:-2] if text.endswith(".0") else text
    # Shortest round-trip digits (same as the JS algorithm), then JS layout:
    # 12345678901234567890.0 -> "12345678901234567000", 1e21 -> "1e+21".
    sign = "-" if value < 0 else ""
    _sign, digit_tuple, exponent = Decimal(repr(abs(value))).normalize().as_tuple()
    digits = "".join(str(d) for d in digit_tuple)
    k = len(digits)
    n = k + exponent
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        exp = n - 1
        exp_str = ("+" if exp >= 0 else "-") + str(abs(exp))
        mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
        body = mantissa + "e" + exp_str
    return sign + body


def _js_parse_float(text):
    if isinstance(text, int | float) and not isinstance(text, bool):
        return float(text)  # parseFloat(5) === 5
    if not isinstance(text, str):
        raise Unresolvable(f"not a number offset: {text!r}")
    match = re.match(r"\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", text)
    if not match:
        raise Unresolvable(f"not a number offset: {text!r}")
    return float(match.group(1))


def _js_truthy(value):
    if value is None or value is False:
        return False
    if isinstance(value, int | float):
        return value == value and value != 0
    if isinstance(value, str):
        return value != ""
    return True


def _squishable_integer(content):
    """Base value of a squished integer run, as ``parseSquishableLiteral``.

    Returns ``None`` for content the library does not treat as an integer.
    Raises :class:`Unresolvable` for integers the library would re-format
    (currency, percentage, dates): their offsets cannot be rebuilt here.
    """
    if not content or content.startswith("'") or "\n" in content:
        return None
    stripped = content.strip()
    if _PLAIN_NUMBER.match(stripped):
        value = float(stripped.replace(",", ""))
        return value if value.is_integer() else None
    if any(char.isdigit() for char in stripped):
        # "$5", "100%", "2024-01-31"... may be an integer for the library,
        # displayed through a format this module does not reproduce.
        raise Unresolvable(f"formatted literal: {content!r}")
    return None


# --------------------------------------------------------------------------
# Ranges (helpers/range.ts)
# --------------------------------------------------------------------------
def _letters_to_col(letters):
    col = 0
    for char in letters.upper():
        col = col * 26 + (ord(char) - 64)
    return col - 1


def _col_to_letters(col):
    if col < 26:
        return chr(65 + col)
    return _col_to_letters(col // 26 - 1) + chr(65 + col % 26)


def _xc(col, row):
    return f"{_col_to_letters(col)}{row + 1}"


def _parse_reference(text):
    """Parse a reference string into a mutable range, like ``createRange``.

    Unbounded (``A:A``) and invalid references are kept verbatim: the
    squisher never emits row/column offsets for them.
    """
    if not isinstance(text, str) or not _RANGE_REFERENCE.match(text):
        return {"raw": text if isinstance(text, str) else _INVALID_REFERENCE}
    prefix = ""
    xc = text
    if "!" in text:
        sheet, xc = text.rsplit("!", 1)
        prefix = sheet + "!"
    parts = []
    for part in xc.replace(" ", "").split(":"):
        match = _CELL_PART.match(part)
        if not match:
            return {"raw": text}
        parts.append(match.groups())
    cols = [_letters_to_col(p[1]) for p in parts]
    rows = [int(p[3]) - 1 for p in parts]
    fixed = [(p[0] == "$", p[2] == "$") for p in parts]
    reference = {
        "prefix": prefix.lstrip(),
        "left": min(cols),
        "right": max(cols),
        "top": min(rows),
        "bottom": max(rows),
        "fixed": fixed,
    }
    if len(fixed) == 2 and reference["left"] == reference["right"]:
        if reference["top"] == reference["bottom"]:
            reference["fixed"] = fixed[:1]
    return reference


def _render_reference(reference):
    """``getRangeString()`` for a range produced by :func:`_parse_reference`."""
    if "raw" in reference:
        return reference["raw"]
    left, right = reference["left"], reference["right"]
    top, bottom = reference["top"], reference["bottom"]
    if bottom < top or right < left or left < 0 or top < 0:
        return _INVALID_REFERENCE
    fixed = reference["fixed"]

    def part(index, col, row):
        col_fixed, row_fixed = fixed[index]
        return (
            ("$" if col_fixed else "")
            + _col_to_letters(col)
            + ("$" if row_fixed else "")
            + str(row + 1)
        )

    text = part(0, left, top)
    if len(fixed) == 2:
        single = top == bottom and left == right
        if not single or any(col or row for col, row in fixed):
            text += ":" + part(1, right, bottom)
    return reference["prefix"] + text


# --------------------------------------------------------------------------
# Formulas (CompiledFormula)
# --------------------------------------------------------------------------
class _Formula:
    """The pieces of a formula the squisher works on, in token order."""

    def __init__(self, text):
        self.tokens = range_tokenize(text)
        self.numbers = []
        self.strings = []
        self.references = []
        for token_type, value in self.tokens:
            if token_type in ("REFERENCE", "INVALID_REFERENCE"):
                self.references.append(_parse_reference(value))
            elif token_type == "STRING":
                self.strings.append(_unquote(value))
            elif token_type == "NUMBER":
                self.numbers.append(float(value.replace(",", "")))

    def render(self, numbers, strings, references):
        """``toFormulaString()``: substitute values, drop whitespace tokens."""
        out = []
        counters = {"n": 0, "s": 0, "r": 0}

        def take(values, key):
            index = counters[key]
            if index >= len(values):
                raise Unresolvable("offset does not match the formula")
            counters[key] += 1
            return values[index]

        for token_type, value in self.tokens:
            if token_type == "SPACE":
                continue
            if token_type in ("REFERENCE", "INVALID_REFERENCE"):
                out.append(_render_reference(take(references, "r")))
            elif token_type == "NUMBER":
                out.append(js_number_to_string(take(numbers, "n")))
            elif token_type == "STRING":
                out.append(f'"{take(strings, "s")}"')
            else:
                out.append(value)
        return "".join(out)


def _unquote(value, quote='"'):
    if value.startswith(quote):
        value = value[1:]
    if value.endswith(quote):
        value = value[:-1]
    return value


# --------------------------------------------------------------------------
# Unsquisher (plugins/core/unsquisher.ts)
# --------------------------------------------------------------------------
def _offset_size(offset):
    """Characters of the offset strings the unsquisher parses per position."""
    if not isinstance(offset, dict):
        return 0
    size = 0
    for key in _OFFSET_KEYS:
        item = offset.get(key)
        if isinstance(item, str):
            size += len(item)
        elif isinstance(item, list):
            size += len(item) + sum(len(x) for x in item if isinstance(x, str))
    return size


class _Unsquisher:
    def __init__(self):
        self.strategy = None
        self.rebase()

    def rebase(self):
        self.formula = None
        self.number_values = []
        self.previous_strings = []
        self.reference_values = []
        self.previous_offset = None
        self.previous_number = None

    def choose_strategy(self, current):
        if isinstance(current, str):
            if current.startswith("="):
                self.rebase()
                self.formula = _Formula(current)
                self.number_values = list(self.formula.numbers)
                self.previous_strings = list(self.formula.strings)
                self.reference_values = [dict(r) for r in self.formula.references]
                self.strategy = "NEW_FORMULA"
                return
            self.rebase()
            try:
                number = _squishable_integer(current)
            except Unresolvable:
                # The literal itself is shown as stored; a run continuing it
                # cannot be rebuilt, so any offset that follows is refused.
                self.strategy = "BROKEN"
                return
            if number is None:
                self.strategy = "NOT_A_FORMULA"
            else:
                self.previous_number = number
                self.strategy = "NEW_NUMBER"
            return
        if not any(_js_truthy(current.get(key)) for key in _OFFSET_KEYS):
            raise Unresolvable("object cell without offsets")
        transitions = {
            "NEW_FORMULA": "FIRST_OFFSET",
            "FIRST_OFFSET": "COMBINE_OFFSET",
            "COMBINE_OFFSET": "COMBINE_OFFSET",
            "NEW_NUMBER": "OFFSET_NUMBER",
            "OFFSET_NUMBER": "OFFSET_NUMBER",
        }
        if self.strategy not in transitions:
            raise Unresolvable(f"offset after {self.strategy}")
        if self.strategy in ("NEW_NUMBER", "OFFSET_NUMBER") and (
            _js_truthy(current.get("R")) or _js_truthy(current.get("S"))
        ):
            raise Unresolvable("reference offset on a number")
        self.strategy = transitions[self.strategy]

    def position_cost(self, current):
        """Work done for each position of ``current`` besides the text produced.

        Call after :meth:`choose_strategy`. Repeated values cost nothing per
        position; offsets re-render the base formula and re-read the offsets.
        """
        if self.strategy in ("FIRST_OFFSET", "COMBINE_OFFSET") and self.formula:
            return (
                len(self.formula.tokens)
                + _offset_size(current)
                + _offset_size(self.previous_offset)
            )
        if self.strategy == "OFFSET_NUMBER":
            return _offset_size(current)
        return 0

    def apply(self, positions, current):
        """Yield the plain content of each position of a stored entry."""
        strategy = self.strategy
        if strategy == "NEW_FORMULA":
            text = self.formula.render(
                self.formula.numbers, self.formula.strings, self.formula.references
            )
            for _position in positions:
                yield text
        elif strategy in ("NOT_A_FORMULA", "NEW_NUMBER") or (
            strategy == "BROKEN" and isinstance(current, str)
        ):
            for _position in positions:
                yield current
        elif strategy == "FIRST_OFFSET":
            self.previous_offset = dict(current)
            for _position in positions:
                yield self._unsquish_formula()
        elif strategy == "COMBINE_OFFSET":
            if self.previous_offset is None:
                raise Unresolvable("no previous offset to combine with")
            for key in _OFFSET_KEYS:
                if current.get(key) is not None:
                    self.previous_offset[key] = current[key]
            for _position in positions:
                yield self._unsquish_formula()
        elif strategy == "OFFSET_NUMBER":
            if self.previous_number is None or current.get("N") is None:
                raise Unresolvable("number offset without a base number")
            offset = _js_parse_float(current["N"])
            for _position in positions:
                self.previous_number += offset
                if not self.previous_number.is_integer():
                    raise Unresolvable("non-integer number run")
                yield js_number_to_string(self.previous_number)
        else:
            raise Unresolvable(f"cannot apply {current!r} after {strategy}")

    def _unsquish_formula(self):
        offset = self.previous_offset
        formula = self.formula
        if formula is None:
            raise Unresolvable("offset without a base formula")
        numbers_offset = offset.get("N")
        if isinstance(numbers_offset, str) and numbers_offset:
            numbers = []
            for index, item in enumerate(numbers_offset.split("|")):
                if index >= len(self.number_values):
                    raise Unresolvable("number offset does not match the formula")
                if item != "=":
                    self.number_values[index] += _js_parse_float(item[1:])
                numbers.append(self.number_values[index])
        else:
            numbers = formula.numbers
        strings_offset = offset.get("S")
        if isinstance(strings_offset, list) and strings_offset:
            strings = []
            for index, item in enumerate(strings_offset):
                if index >= len(self.previous_strings):
                    raise Unresolvable("string offset does not match the formula")
                if item != "=":
                    self.previous_strings[index] = item
                strings.append(self.previous_strings[index])
        else:
            strings = formula.strings
        references_offset = offset.get("R")
        if references_offset is not None:
            if isinstance(references_offset, str):
                references_offset = references_offset.split("|")
            if not isinstance(references_offset, list):
                raise Unresolvable("malformed reference offset")
            references = [
                self._adjust_reference(index, item)
                for index, item in enumerate(references_offset)
            ]
        else:
            references = formula.references
        return formula.render(numbers, strings, references)

    def _adjust_reference(self, index, item):
        if index >= len(self.reference_values):
            raise Unresolvable("reference offset does not match the formula")
        if not isinstance(item, str):
            raise Unresolvable("malformed reference offset")
        current = self.reference_values[index]
        if item == "=":
            return dict(current)
        if item[:1] in "+-" and item[1:2] in ("R", "C"):
            if "raw" in current:
                raise Unresolvable("offset on an unbounded reference")
            try:
                amount = int(item[2:]) * (1 if item[0] == "+" else -1)
            except ValueError as error:
                raise Unresolvable("malformed reference offset") from error
            updated = dict(current)
            if item[1] == "R":
                updated["top"] = updated["bottom"] = current["top"] + amount
            else:
                updated["left"] = updated["right"] = current["left"] + amount
            self.reference_values[index] = updated
            return updated
        if item[:1] in "+-":
            raise Unresolvable("malformed reference offset")
        self.reference_values[index] = _parse_reference(item)
        return self.reference_values[index]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def _parse_key(key):
    """``"B2:B9"`` -> ``(left, top, right, bottom)``, or ``None`` if invalid.

    Only the bounds are returned: the positions are materialized by
    :func:`_key_positions` once the budget has accepted their number.
    """
    if not isinstance(key, str):
        return None
    bounds = []
    for part in key.split(":"):
        match = _KEY_PART.match(part)
        if not match:
            return None
        row = int(match.group(2)) - 1
        if row < 0 or row > _MAX_ROW:
            return None
        bounds.append((_letters_to_col(match.group(1)), row))
    if len(bounds) == 1:
        (col, row) = bounds[0]
        return (col, row, col, row)
    if len(bounds) != 2:
        return None
    (col1, row1), (col2, row2) = bounds
    return (min(col1, col2), min(row1, row2), max(col1, col2), max(row1, row2))


def _key_size(bounds):
    left, top, right, bottom = bounds
    return (right - left + 1) * (bottom - top + 1)


def _key_positions(bounds):
    """(col, row) of every cell of a key, column by column (``expandRange``)."""
    left, top, right, bottom = bounds
    return [
        (col, row) for col in range(left, right + 1) for row in range(top, bottom + 1)
    ]


def stored_repr(value):
    """Show a stored value that could not be expanded, as it is stored.

    Non-string values come back as :class:`CompressedCell` (their JSON).
    """
    if isinstance(value, str):
        return value
    try:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError, RecursionError):
        text = repr(value)
    return CompressedCell(text)


_REPLACEMENT_PATTERN = re.compile(r"\$([$&`'])")


def _legacy_formula_text(formula, budget):
    """Content of an o-spreadsheet < 0.9 formula object, or ``None``.

    ``{"formula": {"text": "=|0|+|1|", "dependencies": ["A1", "B2"]}}`` is
    migrated by the library (``migrate`` 0.9) with, for each dependency in
    turn, ``text.replace(/\\|i\\|/g, d)``. A dependency may itself contain
    markers of later ones, so the text can grow as a product of the
    dependencies. Every step is therefore charged to ``budget`` before it
    runs: the scan of the current text, then the exact length it would
    reach. ``None`` (kept as stored) when that does not fit, or when the
    object is malformed or a dependency cannot be converted exactly.
    """
    text = formula.get("text")
    dependencies = formula.get("dependencies") or []
    if not isinstance(text, str) or not isinstance(dependencies, list):
        return None
    if not budget.take(work=len(text) + len(dependencies)):
        return None
    for index, dependency in enumerate(dependencies):
        if not budget.take(work=len(text)):  # scanning for the marker
            return None
        marker = f"|{index}|"
        count = text.count(marker)
        if not count:
            continue
        replacement = _js_replacement(dependency, marker)
        if replacement is None:
            return None
        new_length = len(text) + count * (len(replacement) - len(marker))
        if not budget.take(work=new_length + len(replacement)):
            return None
        text = text.replace(marker, replacement)
    return text


def _js_replacement(dependency, marker):
    """The text ``String.prototype.replace`` inserts for ``dependency``.

    ``$$`` and ``$&`` are special in a JS replacement string; ``$``` and
    ``$'`` (text around the match) never occur in a real dependency and are
    refused, like any dependency that is not a string: ``None``.
    """
    if not isinstance(dependency, str):
        return None
    if "$" not in dependency:
        return dependency

    def substitute(match):
        char = match.group(1)
        if char == "$":
            return "$"
        if char == "&":
            return marker
        raise Unresolvable("context pattern in a legacy formula dependency")

    try:
        return _REPLACEMENT_PATTERN.sub(substitute, dependency)
    except Unresolvable:
        return None


def _plain_value(value, budget):
    """Collapse a legacy object cell to its content; keep offsets as-is.

    Anything that is not recognizable content is returned unchanged, so the
    caller keeps it in its stored form instead of guessing. ``budget`` bounds
    the rebuilding of pre-0.9 formula objects.
    """
    if isinstance(value, dict):
        if "content" not in value and any(key in value for key in _OFFSET_KEYS):
            return value  # squished offset
        formula = value.get("formula")
        if "content" not in value and isinstance(formula, dict):
            # o-spreadsheet < 0.9: {"formula": {"text": "=|0|+1", "dependencies": [..]}}
            text = _legacy_formula_text(formula, budget)
            return value if text is None else text  # None: kept as stored
        value = value.get("content")  # legacy {"content": ..., "style": ...}
    if value is None or isinstance(value, str | dict):
        return value
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return js_number_to_string(value)
    return stored_repr(value)


def sheet_cell_contents(sheet, budget=None):
    """Return ``({xc: content}, partial)`` for one stored sheet.

    ``partial`` is True when at least one entry was kept in its stored form,
    under its stored key, because it could not be expanded exactly or did not
    fit in ``budget`` (an :class:`ExpansionBudget`, one per workbook; a fresh
    default one when omitted).
    """
    if budget is None:
        budget = ExpansionBudget()
    cells = sheet.get("cells") if isinstance(sheet, dict) else None
    if not isinstance(cells, dict):
        return {}, False
    entries = []
    for key, raw in cells.items():
        value = _plain_value(raw, budget)
        if value is None or value == "":
            continue
        bounds = _parse_key(key)
        order = bounds[:2] if bounds else (float("inf"), float("inf"))
        entries.append((order, str(key), bounds, value))
    entries.sort(key=lambda entry: (entry[0], entry[1]))

    contents = {}
    partial = False
    unsquisher = _Unsquisher()
    for _order, key, bounds, value in entries:
        if bounds is None or not budget.take(cells=_key_size(bounds)):
            # Invalid key, or too many cells: keep the entry as stored. A run
            # continuing it cannot be rebuilt either.
            contents[key] = stored_repr(value)
            unsquisher.strategy = "BROKEN"
            partial = True
            continue
        positions = _key_positions(bounds)
        try:
            _charge_formula_parse(value, budget)
            unsquisher.choose_strategy(value)
            values = _expand_entry(unsquisher, positions, value, budget)
        except Unresolvable as error:
            _logger.debug("Kept stored cell %s as is: %s", key, error)
            unsquisher.strategy = "BROKEN"  # the rest of this run is unknown too
            partial = True
            text = stored_repr(value)
            if not budget.take(work=len(text) * len(positions)):
                contents[key] = text  # once, under its stored key
                continue
            values = [text] * len(positions)
        for (col, row), content in zip(positions, values, strict=True):
            contents[_xc(col, row)] = content
    return contents, partial


def _charge_formula_parse(value, budget):
    """Charge tokenizing a stored formula to ``budget`` before it happens.

    :meth:`_Unsquisher.choose_strategy` tokenizes every formula entry once,
    whatever the size of its key. Raises :class:`Unresolvable` (the entry is
    then kept as stored) when the budget cannot pay for it.
    """
    if isinstance(value, str) and value.startswith("="):
        if not budget.take(work=len(value) * _TOKENIZE_WORK_PER_CHAR):
            raise Unresolvable("expansion budget exhausted")


def _expand_entry(unsquisher, positions, value, budget):
    """Expand one stored entry, charging the work it causes to ``budget``.

    Every position is charged the length of its content (callers compare and
    render it, even when several positions share one string) plus
    :meth:`_Unsquisher.position_cost`. Raises :class:`Unresolvable` as soon
    as the budget runs out.
    """
    weight = unsquisher.position_cost(value)
    values = []
    for content in unsquisher.apply(positions, value):
        if not budget.take(work=weight + len(content)):
            raise Unresolvable("expansion budget exhausted")
        values.append(content)
    return values


def _stored_entries(cells, budget):
    """Fallback for a sheet that could not be read: its entries as stored."""
    contents = {}
    for key, raw in cells.items() if isinstance(cells, dict) else ():
        try:
            value = _plain_value(raw, budget)
            if value is None or value == "":
                continue
            contents[str(key)] = stored_repr(value)
        except Exception as error:  # one bad entry must not hide the whole sheet
            _logger.debug("Skipped unreadable stored cell %r: %s", key, error)
    return contents


def workbook_cell_contents(data, budget=None):
    """Return ``({sheet name: {xc: content}}, partial sheet names)``.

    Never raises on malformed data: a sheet that cannot be read cell by cell
    falls back to its stored entries and is reported as partial. ``budget``
    (an :class:`ExpansionBudget`) caps the cells expanded over all sheets;
    pass one to learn afterwards whether it ran out (``budget.exhausted``).
    """
    if budget is None:
        budget = ExpansionBudget()
    sheets = data.get("sheets") if isinstance(data, dict) else None
    result = {}
    partial = set()
    for index, sheet in enumerate(sheets if isinstance(sheets, list) else []):
        if not isinstance(sheet, dict):
            continue
        name = str(sheet.get("name") or sheet.get("id") or f"#{index + 1}")
        try:
            contents, is_partial = sheet_cell_contents(sheet, budget)
        except Exception as error:  # a malformed sheet must not break the diff
            _logger.warning(
                "Could not expand the cells of sheet %r; showing stored values: %s",
                name,
                error,
            )
            contents = _stored_entries(sheet.get("cells"), budget)
            is_partial = True
        result[name] = contents
        if is_partial:
            partial.add(name)
    return result, partial


def xc_sort_key(xc):
    """Sort cell references row first, then column (A1, B1, A2...)."""
    match = _KEY_PART.match(xc) if isinstance(xc, str) else None
    if not match:
        return (1, 0, 0, str(xc))
    return (0, int(match.group(2)), _letters_to_col(match.group(1)), "")
