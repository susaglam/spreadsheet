# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import html
import json
from unittest.mock import patch
from urllib.parse import quote

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

from ..controllers import main as pdf_main

CONTROLLER = "odoo.addons.spreadsheet_pdf_report_oca.controllers.main"
INJECTED_BG = "red;background-image:url(http://10.0.0.5/)"
PLACEHOLDER_REPORT = "spreadsheet_pdf_report_oca.report_spreadsheet_pdf_placeholder"
# CSS that would break out of the @page rule if a request value reached the
# <style> block of the PDF template.
INJECTED_PAGE_OPTIONS = {
    "page_size": "A4}body{background:url(https://evil.example/x)}x{",
    "page_margin": "0}body::before{content:'evil.example'}x{",
}


def _stacked_span_payload(rows=5, cells=pdf_main.MAX_CELLS_PER_ROW):
    """Few cells on the wire, a huge table for the engine: every cell spans
    the maximum width and height the old per-cell clamps allowed."""
    cell = {
        "value": "",
        "colspan": pdf_main.MAX_CELLS_PER_ROW,
        "rowspan": pdf_main.MAX_ROWS_PER_SHEET,
    }
    return {"name": "Spans", "sheets": [{"name": "S", "rows": [[cell] * cells] * rows}]}


def _sample_payload(**cell_overrides):
    header = {"value": "Header", "bold": True}
    header.update(cell_overrides)
    return {
        "name": "Test Report",
        "report_date": "2026-07-05",
        "sheets": [
            {
                "name": "Sheet1",
                "rows": [
                    [header, {"value": "Value", "align": "right"}],
                    [{"value": "1"}, {"value": "2"}],
                ],
            }
        ],
    }


@tagged("post_install", "-at_install")
class TestDownloadSpreadsheetPDF(HttpCase):
    """End-to-end coverage for the /spreadsheet/pdf download controller.

    Tests that need a real PDF engine are skipped when none is usable; every
    security / validation test runs without any engine binary.
    """

    URL = "/spreadsheet/pdf"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal_user = new_test_user(
            cls.env, login="pdf_export_portal", groups="base.group_portal"
        )
        cls.report = cls.env.ref(pdf_main.REPORT_XMLID)
        cls.ReportModel = type(cls.env["ir.actions.report"])

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _post(self, payload, csrf=True, raw=None):
        data = {"data": raw if raw is not None else json.dumps(payload)}
        if csrf:
            data["csrf_token"] = self.csrf_token()
        return self.url_open(self.URL, data=data, allow_redirects=False)

    def _error(self, response):
        """Decode the JSON error body read by @web/core/network/download."""
        body = json.loads(html.unescape(response.text))
        return body["data"]

    def _skip_without_engine(self):
        Report = self.env["ir.actions.report"]
        engine = Report._get_pdf_engine(self.report)
        state = Report.get_pdf_engine_state(engine)
        if state not in pdf_main.USABLE_ENGINE_STATES:
            self.skipTest(f"PDF engine {engine!r} not usable here (state {state!r})")

    # ------------------------------------------------------------------
    # happy path (needs a real engine)
    # ------------------------------------------------------------------
    def test_pdf_valid_payload(self):
        """A well-formed authenticated request returns a real PDF."""
        self._skip_without_engine()
        self.authenticate("admin", "admin")
        response = self._post(_sample_payload(color="#FF0000", bg="rgb(1, 2, 3)"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Type"), "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_empty_sheets(self):
        """A sheet with no rows exercises the 'Empty sheet' branch."""
        self._skip_without_engine()
        self.authenticate("admin", "admin")
        payload = {
            "name": "Empty Report",
            "report_date": "2026-07-05",
            "sheets": [{"name": "Blank", "rows": []}],
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    # ------------------------------------------------------------------
    # engine selection [ENGINE14] / paper format [DEAD]
    # ------------------------------------------------------------------
    def test_pdf_uses_configured_engine_and_report_paperformat(self):
        """The configured default engine is used (not a hardcoded
        wkhtmltopdf), with the module's report as paper format carrier."""
        self.env["ir.config_parameter"].sudo().set_str(
            "report.pdf_engine_default", "paper-muncher"
        )
        self.authenticate("admin", "admin")
        with (
            patch.object(self.ReportModel, "get_pdf_engine_state", return_value="ok"),
            patch.object(
                self.ReportModel,
                "_run_pdf_engine_without_processing",
                autospec=True,
                return_value=b"%PDF-1.4 fake",
            ) as run_engine,
        ):
            response = self._post(_sample_payload())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        run_engine.assert_called_once()
        args, kwargs = run_engine.call_args
        self.assertEqual(args[1], "paper-muncher")
        self.assertEqual(kwargs["report_ref"].id, self.report.id)
        self.assertTrue(kwargs["landscape"])
        body = args[2][0]
        self.assertIn("size: 297mm 210mm", body)
        self.assertIn("font-weight:bold;", body)

    def test_pdf_engine_unavailable_explained(self):
        """No usable engine -> a teaching UserError, never a raw 500."""
        self.authenticate("admin", "admin")
        with (
            patch.object(
                self.ReportModel, "get_pdf_engine_state", return_value="install"
            ),
            patch.object(
                self.ReportModel, "_run_pdf_engine_without_processing"
            ) as run_engine,
        ):
            response = self._post(_sample_payload())
        self.assertEqual(response.status_code, 422)
        error = self._error(response)
        self.assertEqual(error["name"], "odoo.exceptions.UserError")
        self.assertIn("report.pdf_engine_default", error["arguments"][0])
        run_engine.assert_not_called()

    # ------------------------------------------------------------------
    # access & CSRF [M5]
    # ------------------------------------------------------------------
    def test_pdf_requires_auth(self):
        """Anonymous callers must not reach the PDF generation."""
        response = self._post(_sample_payload(), csrf=False)
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(response.content.startswith(b"%PDF"))

    def test_pdf_requires_csrf_token(self):
        """CSRF protection is active: a POST without token is refused."""
        self.authenticate("admin", "admin")
        with (
            patch.object(
                self.ReportModel, "_run_pdf_engine_without_processing"
            ) as run_engine,
            # core logs MISSING_CSRF_WARNING before refusing the request
            mute_logger("odoo.http"),
        ):
            response = self._post(_sample_payload(), csrf=False)
        self.assertEqual(response.status_code, 400)
        self.assertIn("CSRF", response.text)
        run_engine.assert_not_called()

    def test_pdf_portal_user_denied(self):
        """Portal users are authenticated but must not use the export."""
        self.authenticate(self.portal_user.login, self.portal_user.login)
        with patch.object(
            self.ReportModel, "_run_pdf_engine_without_processing"
        ) as run_engine:
            response = self._post(_sample_payload())
        self.assertEqual(response.status_code, 403)
        error = self._error(response)
        self.assertEqual(error["name"], "odoo.exceptions.AccessError")
        self.assertIn("Only internal users", error["arguments"][0])
        self.assertFalse(response.content.startswith(b"%PDF"))
        run_engine.assert_not_called()

    # ------------------------------------------------------------------
    # payload validation [M5]
    # ------------------------------------------------------------------
    def test_pdf_malformed_json(self):
        """Malformed JSON degrades gracefully to a 400, never a raw 500."""
        self.authenticate("admin", "admin")
        with mute_logger(CONTROLLER):
            response = self._post(None, raw="{not valid json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.content.startswith(b"%PDF"))
        self.assertIn("not in the expected format", self._error(response)["message"])

    def test_pdf_invalid_colour_rejected(self):
        """A CSS-injection attempt in a colour is refused before rendering."""
        self.authenticate("admin", "admin")
        with patch.object(
            self.ReportModel, "_run_pdf_engine_without_processing"
        ) as run_engine:
            response = self._post(_sample_payload(bg=INJECTED_BG))
        self.assertEqual(response.status_code, 400)
        error = self._error(response)
        self.assertEqual(error["name"], "odoo.exceptions.UserError")
        self.assertIn("invalid fill color", error["arguments"][0])
        self.assertFalse(response.content.startswith(b"%PDF"))
        run_engine.assert_not_called()

    def test_pdf_invalid_alignment_rejected(self):
        self.authenticate("admin", "admin")
        response = self._post(_sample_payload(align="left;background:url(x)"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid alignment", self._error(response)["arguments"][0])

    def test_pdf_oversized_payload_rejected(self):
        """More sheets than allowed -> 413 with a message that teaches."""
        self.authenticate("admin", "admin")
        payload = {
            "name": "Huge",
            "sheets": [
                {"name": f"S{index}", "rows": []}
                for index in range(pdf_main.MAX_SHEETS + 1)
            ],
        }
        with patch.object(
            self.ReportModel, "_run_pdf_engine_without_processing"
        ) as run_engine:
            response = self._post(payload)
        self.assertEqual(response.status_code, 413)
        message = self._error(response)["arguments"][0]
        self.assertIn(f"the limit is {pdf_main.MAX_SHEETS}", message)
        self.assertIn("XLSX", message)
        run_engine.assert_not_called()

    def test_pdf_too_many_cells_rejected(self):
        self.authenticate("admin", "admin")
        with patch(f"{CONTROLLER}.MAX_TOTAL_CELLS", 3):
            response = self._post(_sample_payload())  # 4 cells
        self.assertEqual(response.status_code, 413)
        self.assertIn("more than 3 cells", self._error(response)["arguments"][0])

    def test_pdf_payload_bytes_cap(self):
        self.authenticate("admin", "admin")
        with patch(f"{CONTROLLER}.MAX_PAYLOAD_BYTES", 64):
            response = self._post(_sample_payload())
        self.assertEqual(response.status_code, 413)
        self.assertIn("larger than", self._error(response)["arguments"][0])

    def test_pdf_stacked_spans_rejected(self):
        """Merge spans cannot turn a small payload into a huge PDF table."""
        self.authenticate("admin", "admin")
        with patch.object(
            self.ReportModel, "_run_pdf_engine_without_processing"
        ) as run_engine:
            response = self._post(_stacked_span_payload())
        self.assertEqual(response.status_code, 413)
        message = self._error(response)["arguments"][0]
        self.assertIn("cells wide", message)
        self.assertIn("XLSX", message)
        run_engine.assert_not_called()

    # ------------------------------------------------------------------
    # generic report route [DEAD follow-up]
    # ------------------------------------------------------------------
    def test_report_route_cannot_inject_css(self):
        """/report/html/<report> merges request "options" into the rendering
        values; none of them may reach a <style> block."""
        self.authenticate("admin", "admin")
        options = quote(json.dumps(INJECTED_PAGE_OPTIONS))
        response = self.url_open(f"/report/html/{PLACEHOLDER_REPORT}?options={options}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("File > Download PDF", response.text)
        self.assertNotIn("evil.example", response.text)


@tagged("post_install", "-at_install")
class TestSpreadsheetPdfPayload(TransactionCase):
    """Unit coverage of the payload validation (no HTTP, no engine)."""

    def test_normalize_color_accepts_strict_grammar(self):
        cases = {
            "#FFF": "#fff",
            "#A1b2C3": "#a1b2c3",
            "rgb(1, 2, 3)": "rgb(1, 2, 3)",
            "rgba(255,255,255,.5)": "rgba(255, 255, 255, 0.5)",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(pdf_main.normalize_color(raw), expected)

    def test_normalize_color_rejects_everything_else(self):
        for raw in (
            INJECTED_BG,
            "red",
            "#fff;",
            "#ffff",
            "rgb(256, 0, 0)",
            "rgba(0, 0, 0, 2)",
            "expression(alert(1))",
            "url(http://10.0.0.5/)",
            "#\u0661\u0662\u0663",  # Arabic-Indic digits must not match \d
            12,
            None,
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(pdf_main.normalize_color(raw))

    def test_normalize_payload_builds_safe_style(self):
        values = pdf_main.normalize_payload(
            self.env,
            _sample_payload(
                color="#FF0000",
                bg="rgba(0, 0, 0, 0.25)",
                align="center",
                fontSize=12,
                colspan=2,
                value="<b>x</b>",
            ),
        )
        cell = values["sheets"][0]["rows"][0][0]
        self.assertEqual(
            cell["style"],
            "font-weight:bold;color:#ff0000;"
            "background-color:rgba(0, 0, 0, 0.25);"
            "text-align:center;font-size:12px;",
        )
        self.assertEqual(cell["colspan"], 2)
        html_content = str(
            self.env["ir.qweb"]._render(
                "spreadsheet_pdf_report_oca.spreadsheet_pdf_content",
                {"sheets": values["sheets"]},
            )
        )
        self.assertIn("background-color:rgba(0, 0, 0, 0.25)", html_content)
        self.assertNotIn("<b>x</b>", html_content)  # cell text is escaped

    def test_normalize_payload_rejects_bad_values(self):
        for overrides in (
            {"bg": INJECTED_BG},
            {"color": "red"},
            {"align": "left;x:y"},
            {"align": ["left"]},
            {"fontSize": "12px;"},
            {"fontSize": True},
            {"fontSize": pdf_main.MAX_FONT_SIZE + 1},
            {"fontSize": 10_000},
            {"colspan": "2"},
            {"value": {"nested": "object"}},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(UserError) as caught:
                    pdf_main.normalize_payload(self.env, _sample_payload(**overrides))
                self.assertEqual(caught.exception.http_status, 400)

    def test_normalize_payload_font_size_bounds(self):
        """o-spreadsheet allows font sizes 1-400: all of them are exported."""
        for size in (1, 10.5, 400):
            with self.subTest(size=size):
                values = pdf_main.normalize_payload(
                    self.env, _sample_payload(fontSize=size)
                )
                self.assertIn(
                    f"font-size:{size:g}px;",
                    values["sheets"][0]["rows"][0][0]["style"],
                )

    def test_normalize_payload_span_grid_limits(self):
        """Limits apply to the laid-out table: colspan x rowspan slots, and a
        row width that includes rowspans still open from the rows above."""
        # Exploit shape from the review: 250 x 200 cells, each 200 x 1000.
        with self.assertRaises(UserError) as caught:
            pdf_main.normalize_payload(
                self.env, _stacked_span_payload(rows=250, cells=200)
            )
        self.assertEqual(caught.exception.http_status, 413)
        self.assertIn("cells wide", caught.exception.args[0])

        # One cell per row: the second row is pushed right by the rowspan.
        pushed = {
            "sheets": [
                {
                    "rows": [
                        [{"value": "a", "colspan": 150, "rowspan": 2}],
                        [{"value": "b", "colspan": 100}],
                    ]
                }
            ]
        }
        with self.assertRaises(UserError) as caught:
            pdf_main.normalize_payload(self.env, pushed)
        self.assertEqual(caught.exception.http_status, 413)
        self.assertIn("250 cells wide", caught.exception.args[0])

        # Slots, not cells, count against the total.
        one_big_cell = {
            "sheets": [
                {
                    "rows": [
                        [{"value": "x", "colspan": 4, "rowspan": 3}],
                        [],
                        [],
                    ]
                }
            ]
        }
        with (
            patch.object(pdf_main, "MAX_TOTAL_CELLS", 10),
            self.assertRaises(UserError) as caught,
        ):
            pdf_main.normalize_payload(self.env, one_big_cell)
        self.assertEqual(caught.exception.http_status, 413)
        self.assertIn("more than 10 cells", caught.exception.args[0])

    def test_normalize_payload_keeps_real_merges(self):
        """A genuine merge layout passes and rowspans are clipped to the table."""
        values = pdf_main.normalize_payload(
            self.env,
            {
                "sheets": [
                    {
                        "rows": [
                            [
                                {"value": "m", "colspan": 2, "rowspan": 2},
                                {"value": "c1"},
                            ],
                            [{"value": "c2", "rowspan": 1000}],
                        ]
                    }
                ]
            },
        )
        rows = values["sheets"][0]["rows"]
        self.assertEqual((rows[0][0]["colspan"], rows[0][0]["rowspan"]), (2, 2))
        self.assertEqual((rows[0][1]["colspan"], rows[0][1]["rowspan"]), (None, None))
        # Only one row left from row 2 on: the rowspan is dropped, not sent as 1000.
        self.assertIsNone(rows[1][0]["rowspan"])

    def test_normalize_payload_size_limits(self):
        with self.assertRaises(UserError) as caught:
            pdf_main.normalize_payload(
                self.env, {"sheets": [{}] * (pdf_main.MAX_SHEETS + 1)}
            )
        self.assertEqual(caught.exception.http_status, 413)
        long_row = [{"value": "x"}] * (pdf_main.MAX_CELLS_PER_ROW + 1)
        with self.assertRaises(UserError) as caught:
            pdf_main.normalize_payload(self.env, {"sheets": [{"rows": [long_row]}]})
        self.assertEqual(caught.exception.http_status, 413)

    def test_report_action_never_exposes_pdf_template(self):
        """The generic report route must not reach the controller template,
        whose <style> block takes page_size / page_margin from its values."""
        Report = self.env["ir.actions.report"]
        report = self.env.ref(pdf_main.REPORT_XMLID)
        self.assertEqual(report.report_name, PLACEHOLDER_REPORT)
        self.assertFalse(
            Report._get_report_from_name(
                "spreadsheet_pdf_report_oca.spreadsheet_pdf_main"
            )
        )
        html_content = Report._render_qweb_html(
            pdf_main.REPORT_XMLID, [], data=dict(INJECTED_PAGE_OPTIONS)
        )[0].decode()
        self.assertIn("<main>", html_content)
        self.assertNotIn("evil.example", html_content)

    def test_report_action_carries_paperformat(self):
        report = self.env.ref(pdf_main.REPORT_XMLID)
        paperformat = self.env.ref(
            "spreadsheet_pdf_report_oca.paperformat_spreadsheet_landscape"
        )
        self.assertEqual(report.paperformat_id, paperformat)
        self.assertEqual(report.get_paperformat(), paperformat)
        self.assertEqual(
            pdf_main.page_setup(paperformat),
            (True, "297mm 210mm", "15mm 7mm 15mm 7mm"),
        )
