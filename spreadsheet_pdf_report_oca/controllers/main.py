# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging
import math
import re

import psycopg2

from odoo.exceptions import AccessError, ConcurrencyError, UserError
from odoo.http import Controller, request, route
from odoo.http.dispatcher import serialize_exception
from odoo.http.stream import content_disposition
from odoo.tools.misc import html_escape

_logger = logging.getLogger(__name__)

#: ir.actions.report carrying the paper format and (optionally, through its
#: report_type) the PDF engine used for the export. Admins can change both in
#: Settings > Technical > Actions > Reports.
REPORT_XMLID = "spreadsheet_pdf_report_oca.action_report_spreadsheet_pdf"

# ---------------------------------------------------------------------------
# Payload limits. The export runs server-side HTML -> PDF conversion, whose
# cost grows with the number of table slots; without caps a single request
# can pin a worker for minutes. Limits are enforced on the table the engine
# lays out, not only on the cells the client sends: a merged cell counts for
# every slot it covers (colspan x rowspan), and a row's width includes the
# columns still covered by rowspans started in the rows above.
#
# The JS client scans at most 200 columns x 1000 rows per sheet, so the
# per-row and per-sheet caps never refuse a genuine export. MAX_TOTAL_CELLS
# CAN refuse a genuine one (e.g. a value in AZ1000 is 52 x 1000 cells): the
# client checks the same total before uploading (download_pdf.esm.js
# MAX_TOTAL_CELLS) and explains it, the server check is the enforcement.
# MAX_PAYLOAD_BYTES stays below odoo.http's MAX_FORM_SIZE (10 MiB), above
# which werkzeug refuses the form field before this controller runs.
# ---------------------------------------------------------------------------
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_SHEETS = 50
MAX_ROWS_PER_SHEET = 1000
MAX_CELLS_PER_ROW = 200
MAX_TOTAL_CELLS = 50_000
MAX_CELL_TEXT = 5000
MAX_NAME_LENGTH = 200
MIN_FONT_SIZE = 1
#: Same bounds as the o-spreadsheet font size editor (min=1, max=400).
MAX_FONT_SIZE = 400
ALLOWED_ALIGNMENTS = frozenset({"left", "center", "right"})

#: Engine states in which a PDF can be produced. "workers" (Odoo running with
#: exactly one worker) is tolerated because this document is self-contained:
#: inline CSS, logo as data URI, no URL the engine would fetch back from Odoo.
USABLE_ENGINE_STATES = frozenset({"ok", "upgrade", "workers"})

# Strict colour grammar. re.ASCII keeps \d and \s to ASCII; values are always
# re-rendered from the parsed numbers, so nothing the client sent (";",
# "url(", comments...) can ever reach the style attribute.
_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})", re.IGNORECASE | re.ASCII)
_RGB_COLOR_RE = re.compile(
    r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)",
    re.IGNORECASE | re.ASCII,
)
_RGBA_COLOR_RE = re.compile(
    r"rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,"
    r"\s*(\d(?:\.\d+)?|\.\d+)\s*\)",
    re.IGNORECASE | re.ASCII,
)


class SpreadsheetPdfPayloadError(UserError):
    """The client payload was refused; carries the HTTP status to answer."""

    def __init__(self, message, http_status=400):
        super().__init__(message)
        self.http_status = http_status


def normalize_color(value):
    """Return a canonical CSS colour, or None when ``value`` is not one of
    ``#rgb``, ``#rrggbb``, ``rgb(r, g, b)`` or ``rgba(r, g, b, a)``."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    value = value.strip()
    if _HEX_COLOR_RE.fullmatch(value):
        return value.lower()
    match = _RGB_COLOR_RE.fullmatch(value)
    if match:
        red, green, blue = (int(part) for part in match.groups())
        if max(red, green, blue) <= 255:
            return f"rgb({red}, {green}, {blue})"
        return None
    match = _RGBA_COLOR_RE.fullmatch(value)
    if match:
        red, green, blue = (int(part) for part in match.groups()[:3])
        alpha = float(match.group(4))
        if max(red, green, blue) <= 255 and 0 <= alpha <= 1:
            return f"rgba({red}, {green}, {blue}, {alpha:g})"
    return None


def _is_number(value):
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _short(value):
    """Printable, bounded excerpt of a rejected client value."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= 80 else text[:77] + "..."


def _location(env, where):
    """Human-readable position; only built when a cell is refused, so the
    happy path does not pay one translation lookup per cell."""
    sheet_name, row_index, cell_index = where
    return env._(
        'sheet "%(sheet)s", row %(row)s, cell %(cell)s',
        sheet=sheet_name,
        row=row_index + 1,
        cell=cell_index + 1,
    )


def _format_error(env):
    return SpreadsheetPdfPayloadError(
        env._(
            "The spreadsheet data sent for the PDF export is not in the "
            "expected format, so it was refused. Reload the spreadsheet and "
            "use File > Download PDF again; if the problem persists, contact "
            "your administrator."
        )
    )


def _cell_format_error(env, where):
    return SpreadsheetPdfPayloadError(
        env._(
            "The PDF export was refused because %(location)s contains data in "
            "an unexpected format. Reload the spreadsheet and use File > "
            "Download PDF again; if the problem persists, contact your "
            "administrator.",
            location=_location(env, where),
        )
    )


def _too_large_error(message):
    return SpreadsheetPdfPayloadError(message, http_status=413)


def _row_too_wide_error(env, sheet_name, row_index, width):
    return _too_large_error(
        env._(
            'Row %(row)s of sheet "%(sheet)s" is %(count)s cells wide in the '
            "PDF export (merged cells count for every column they cover), but "
            "the limit is %(limit)s cells per row. Very large exports take "
            "minutes to render and block the server for other users. Remove "
            "the columns you do not need, or use File > Download XLSX to get "
            "the full data.",
            row=row_index + 1,
            sheet=sheet_name,
            count=width,
            limit=MAX_CELLS_PER_ROW,
        ),
    )


def _too_many_cells_error(env):
    return _too_large_error(
        env._(
            "This spreadsheet sends more than %(limit)s cells to the PDF export "
            "(merged cells count for every cell they cover). Very large exports "
            "take minutes to render and block the server for other users. "
            "Remove unused rows and columns, hide the sheets you do not need in "
            "the PDF, or use File > Download XLSX to get the full data.",
            limit=MAX_TOTAL_CELLS,
        ),
    )


def _cell_style(env, cell, where):
    """Build the validated inline style of one cell."""
    declarations = []
    if cell.get("bold"):
        declarations.append("font-weight:bold")
    if cell.get("italic"):
        declarations.append("font-style:italic")
    for key, css_property in (("color", "color"), ("bg", "background-color")):
        raw = cell.get(key)
        if raw in (None, ""):
            continue
        color = normalize_color(raw)
        if color is None:
            label = env._("text color") if key == "color" else env._("fill color")
            raise SpreadsheetPdfPayloadError(
                env._(
                    "The PDF export was refused because %(location)s has an "
                    'invalid %(property)s "%(value)s". Only colors written as '
                    "#rgb, #rrggbb, rgb(r, g, b) or rgba(r, g, b, a) are "
                    "accepted, because any other text could inject styling "
                    "that makes the PDF engine load external resources. "
                    "Reload the spreadsheet and export again; if the value "
                    "comes from an integration or a script, change it to one "
                    "of those formats.",
                    location=_location(env, where),
                    property=label,
                    value=_short(raw),
                )
            )
        declarations.append(f"{css_property}:{color}")
    align = cell.get("align")
    if align not in (None, ""):
        if not isinstance(align, str) or align not in ALLOWED_ALIGNMENTS:
            raise SpreadsheetPdfPayloadError(
                env._(
                    "The PDF export was refused because %(location)s has an "
                    'invalid alignment "%(value)s". Only left, center and right '
                    "are accepted, because the value is written into the PDF "
                    "styling. Reload the spreadsheet and export again.",
                    location=_location(env, where),
                    value=_short(align),
                )
            )
        declarations.append(f"text-align:{align}")
    font_size = cell.get("fontSize")
    if font_size not in (None, ""):
        if not _is_number(font_size) or not (
            MIN_FONT_SIZE <= font_size <= MAX_FONT_SIZE
        ):
            raise SpreadsheetPdfPayloadError(
                env._(
                    "The PDF export was refused because %(location)s has an "
                    'invalid font size "%(value)s". The font size must be a '
                    "number between %(min)s and %(max)s, because it is written "
                    "into the PDF styling. Reload the spreadsheet and export "
                    "again.",
                    location=_location(env, where),
                    value=_short(font_size),
                    min=MIN_FONT_SIZE,
                    max=MAX_FONT_SIZE,
                )
            )
        declarations.append(f"font-size:{font_size:g}px")
    return ";".join(declarations) + ";" if declarations else None


def _span(env, value, where):
    """Return a validated colspan/rowspan (1 when absent). Bounds are applied
    by :func:`_normalize_rows`, which knows the table layout."""
    if value in (None, ""):
        return 1
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _cell_format_error(env, where)
    return value


def _cell_text(env, value, where):
    if value is None:
        return ""
    if isinstance(value, bool | int | float | str):
        return str(value)[:MAX_CELL_TEXT]
    raise _cell_format_error(env, where)


def _normalize_rows(env, sheet_name, rows, total_slots):
    """Validate the rows of one sheet against the table the engine lays out.

    Returns ``(clean_rows, total_slots)``. ``total_slots`` counts the table
    slots of all sheets so far: a cell covers ``colspan x rowspan`` slots, and
    a row is as wide as its own cells plus the columns still covered by
    rowspans started in the rows above (HTML table model).
    """
    row_count = len(rows)
    # Column index -> first row index no longer covered by a rowspan started
    # in an earlier row. Only columns below MAX_CELLS_PER_ROW are ever stored.
    covered_until = {}
    clean_rows = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, list):
            raise _format_error(env)
        # Cheap early guard before looking at any cell of a huge row.
        if len(row) > MAX_CELLS_PER_ROW:
            raise _row_too_wide_error(env, sheet_name, row_index, len(row))
        clean_row = []
        column = 0
        for cell_index, cell in enumerate(row):
            where = (sheet_name, row_index, cell_index)
            if not isinstance(cell, dict):
                raise _cell_format_error(env, where)
            # A cell starts at the first slot not covered by a rowspan from the
            # rows above. Each skipped slot is already counted in total_slots,
            # so this loop stays bounded by MAX_TOTAL_CELLS.
            while covered_until.get(column, 0) > row_index:
                column += 1
            colspan = _span(env, cell.get("colspan"), where)
            end_column = column + colspan
            if end_column > MAX_CELLS_PER_ROW:
                raise _row_too_wide_error(env, sheet_name, row_index, end_column)
            # A rowspan never reaches past the last row sent.
            rowspan = min(_span(env, cell.get("rowspan"), where), row_count - row_index)
            total_slots += colspan * rowspan
            if total_slots > MAX_TOTAL_CELLS:
                raise _too_many_cells_error(env)
            if rowspan > 1:
                for spanned in range(column, end_column):
                    covered_until[spanned] = row_index + rowspan
            column = end_column
            clean_row.append(
                {
                    "value": _cell_text(env, cell.get("value"), where),
                    "style": _cell_style(env, cell, where),
                    "colspan": colspan if colspan > 1 else None,
                    "rowspan": rowspan if rowspan > 1 else None,
                }
            )
        clean_rows.append(clean_row)
    return clean_rows, total_slots


def normalize_payload(env, payload):
    """Validate the client payload and return clean template values.

    Every value that ends up in the PDF is rebuilt here from validated
    primitives: the QWeb template never concatenates client strings into
    attributes. Raises :class:`SpreadsheetPdfPayloadError` (a ``UserError``)
    with a message that explains what was refused, why and how to fix it.
    """
    if not isinstance(payload, dict):
        raise _format_error(env)
    sheets = payload.get("sheets") or []
    if not isinstance(sheets, list):
        raise _format_error(env)
    if len(sheets) > MAX_SHEETS:
        raise _too_large_error(
            env._(
                "This spreadsheet sends %(count)s sheets to the PDF export, but "
                "the limit is %(limit)s. Very large exports take minutes to "
                "render and block the server for other users. Hide the sheets "
                "you do not need in the PDF, split the spreadsheet, or use File "
                "> Download XLSX to get the whole workbook.",
                count=len(sheets),
                limit=MAX_SHEETS,
            ),
        )

    name = payload.get("name")
    report_name = (
        name.strip()[:MAX_NAME_LENGTH]
        if isinstance(name, str) and name.strip()
        else env._("Spreadsheet")
    )
    report_date = payload.get("report_date")
    report_date = report_date[:MAX_NAME_LENGTH] if isinstance(report_date, str) else ""

    # Table slots the engine has to lay out, over all sheets.
    total_slots = 0
    clean_sheets = []
    for sheet in sheets:
        if not isinstance(sheet, dict):
            raise _format_error(env)
        sheet_name = sheet.get("name")
        sheet_name = (
            sheet_name[:MAX_NAME_LENGTH]
            if isinstance(sheet_name, str) and sheet_name
            else env._("Sheet")
        )
        rows = sheet.get("rows") or []
        if not isinstance(rows, list):
            raise _format_error(env)
        if len(rows) > MAX_ROWS_PER_SHEET:
            raise _too_large_error(
                env._(
                    'Sheet "%(sheet)s" sends %(count)s rows to the PDF export, '
                    "but the limit is %(limit)s rows per sheet. Very large "
                    "exports take minutes to render and block the server for "
                    "other users. Remove the rows you do not need, split the "
                    "sheet, or use File > Download XLSX to get the full data.",
                    sheet=sheet_name,
                    count=len(rows),
                    limit=MAX_ROWS_PER_SHEET,
                ),
            )
        clean_rows, total_slots = _normalize_rows(env, sheet_name, rows, total_slots)
        clean_sheets.append({"name": sheet_name, "rows": clean_rows})

    return {
        "report_name": report_name,
        "report_date": report_date,
        "sheets": clean_sheets,
    }


def page_setup(paperformat):
    """Return (landscape, page_size_css, page_margin_css) for a paperformat.

    The engines take size/orientation/margins from the paperformat through
    their command line; the @page rule mirrors the same values for engines
    that honour CSS paged media (Paper Muncher runs with ``--margins none``).
    """
    if not paperformat:
        return True, "A4 landscape", "15mm 7mm 15mm 7mm"
    landscape = paperformat.orientation != "Portrait"
    if paperformat.print_page_width and paperformat.print_page_height:
        page_size = (
            f"{paperformat.print_page_width:g}mm {paperformat.print_page_height:g}mm"
        )
    else:
        page_size = "A4 landscape" if landscape else "A4 portrait"
    page_margin = (
        f"{paperformat.margin_top:g}mm {paperformat.margin_right:g}mm "
        f"{paperformat.margin_bottom:g}mm {paperformat.margin_left:g}mm"
    )
    return landscape, page_size, page_margin


class SpreadsheetDownloadPDF(Controller):
    @route(
        "/spreadsheet/pdf",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def download_spreadsheet_pdf(self, data=None, **kw):
        env = request.env
        try:
            if not env.user._is_internal():
                raise AccessError(
                    env._(
                        "Only internal users can export spreadsheets to PDF. "
                        "Your account is a portal or public account, and the "
                        "export renders documents on the server with the "
                        "company letterhead. Ask an administrator for an "
                        "internal user account, or ask a colleague to export "
                        "the PDF for you."
                    )
                )
            payload = self._read_payload(env, data)
            values = normalize_payload(env, payload)
            pdf_content = self._render_pdf(env, values)
        except UserError as exc:
            if not isinstance(exc, SpreadsheetPdfPayloadError | AccessError):
                _logger.info("Spreadsheet PDF: export refused: %s", exc)
            return self._error_response(exc, getattr(exc, "http_status", 422))
        except (ConcurrencyError, psycopg2.IntegrityError, psycopg2.OperationalError):
            # Serialization failures and friends: odoo.http.retrying() rolls
            # back and retries the whole request, so they must not be turned
            # into a final error answer here.
            raise
        except Exception:
            _logger.exception("Spreadsheet PDF: rendering/conversion failed")
            return self._error_response(
                UserError(
                    env._(
                        "The PDF could not be generated because the PDF engine "
                        "reported an unexpected error. Try again; if it keeps "
                        "failing, ask an administrator to check the server log "
                        "(logger odoo.addons.spreadsheet_pdf_report_oca) for "
                        "the details."
                    )
                ),
                500,
            )

        filename = f"{values['report_name']}.pdf"
        return request.make_response(
            pdf_content,
            [
                ("Content-Length", len(pdf_content)),
                ("Content-Type", "application/pdf"),
                ("X-Content-Type-Options", "nosniff"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _read_payload(self, env, data):
        if hasattr(data, "read"):
            data = data.read(MAX_PAYLOAD_BYTES + 1)
        if isinstance(data, bytes):
            size = len(data)
        elif isinstance(data, str):
            size = len(data.encode("utf-8"))
        else:
            raise _format_error(env)
        if size > MAX_PAYLOAD_BYTES:
            raise _too_large_error(
                env._(
                    "The spreadsheet data sent to the PDF export is larger than "
                    "%(limit)s MB. Very large exports take minutes to render and "
                    "block the server for other users. Remove unused rows and "
                    "columns, hide the sheets you do not need in the PDF, or use "
                    "File > Download XLSX to get the full data.",
                    limit=MAX_PAYLOAD_BYTES // (1024 * 1024),
                ),
            )
        try:
            return json.loads(data)
        # JSONDecodeError is a ValueError; absurdly nested arrays raise
        # RecursionError, which must not end up as an "engine error".
        except (TypeError, ValueError, RecursionError) as exc:
            _logger.warning("Spreadsheet PDF: malformed JSON payload")
            raise _format_error(env) from exc

    def _render_pdf(self, env, values):
        """Render the QWeb document and convert it with the configured engine.

        The engine is resolved exactly like core reports do
        (``ir.actions.report._get_pdf_engine``): the report's own
        ``qweb-pdf-<engine>`` type when an admin picked one, otherwise the
        ``report.pdf_engine_default`` system parameter, otherwise wkhtmltopdf.
        """
        Report = env["ir.actions.report"]
        report = env.ref(REPORT_XMLID, raise_if_not_found=False)
        report_sudo = (
            report.sudo()
            if report is not None and report._name == "ir.actions.report"
            else Report.sudo().browse()
        )
        if not report_sudo:
            _logger.warning(
                "Spreadsheet PDF: report %s is missing (module not upgraded?); "
                "falling back to the company paper format.",
                REPORT_XMLID,
            )
        engine_name = Report._get_pdf_engine(report_sudo or None)
        engine_state = Report.get_pdf_engine_state(engine_name)
        if engine_state not in USABLE_ENGINE_STATES:
            raise self._engine_error(env, engine_name, engine_state)
        if engine_state == "workers":
            _logger.info(
                "Spreadsheet PDF: engine %s reports too few workers; the "
                "self-contained spreadsheet document is rendered anyway.",
                engine_name,
            )

        # Empty recordset -> the company paper format (core fallback).
        paperformat = (report_sudo or Report.sudo()).get_paperformat()
        landscape, page_size, page_margin = page_setup(paperformat)
        company = env.company
        content = env["ir.qweb"]._render(
            "spreadsheet_pdf_report_oca.spreadsheet_pdf_content",
            {"sheets": values["sheets"]},
        )
        body_html = env["ir.qweb"]._render(
            "spreadsheet_pdf_report_oca.spreadsheet_pdf_main",
            {
                "company": company,
                "report_name": values["report_name"],
                "report_date": values["report_date"],
                "page_size": page_size,
                "page_margin": page_margin,
                "content": content,
            },
        )
        if isinstance(body_html, bytes):
            body_html = body_html.decode("utf-8")
        try:
            return Report._run_pdf_engine_without_processing(
                engine_name,
                [str(body_html)],
                report_ref=report_sudo or False,
                landscape=landscape,
            )
        except NotImplementedError as exc:
            raise self._engine_error(env, engine_name, "install") from exc

    def _engine_error(self, env, engine_name, engine_state):
        if engine_state == "broken":
            message = env._(
                'The PDF engine "%(engine)s" is installed but does not respond, '
                "so the spreadsheet cannot be converted to PDF. Ask an "
                "administrator to check the engine installation on the server, "
                "or to switch to another engine with the system parameter "
                "report.pdf_engine_default (Settings > Technical > Parameters > "
                "System Parameters).",
                engine=engine_name,
            )
        else:
            message = env._(
                'The PDF engine "%(engine)s" is not available on this server, '
                "so the spreadsheet cannot be converted to PDF (all Odoo PDF "
                "reports need an engine). Ask an administrator to install the "
                '"Report Engine: wkhtmltopdf/wkhtmltoimage" module together '
                'with the wkhtmltopdf program, or the "Report Engine: Paper '
                'Muncher" module, and to select it with the system parameter '
                "report.pdf_engine_default (Settings > Technical > Parameters > "
                "System Parameters).",
                engine=engine_name,
            )
        return UserError(message)

    def _error_response(self, exc, status):
        """Answer in the JSON shape ``@web/core/network/download`` decodes, so
        the browser shows the message in a regular warning dialog."""
        exposed = AccessError if isinstance(exc, AccessError) else UserError
        message = exc.args[0] if exc.args else str(exc)
        data = serialize_exception(exposed(message))
        data["debug"] = ""  # never leak server internals to the browser
        error = {"code": status, "message": "Odoo Server Error", "data": data}
        return request.make_response(
            html_escape(json.dumps(error)),
            headers=[("Content-Type", "text/html; charset=utf-8")],
            status=status,
        )
