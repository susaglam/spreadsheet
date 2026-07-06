# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging

from odoo.http import Controller, request, route
from odoo.http.stream import content_disposition

_logger = logging.getLogger(__name__)


class SpreadsheetDownloadPDF(Controller):
    @route(
        "/spreadsheet/pdf",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def download_spreadsheet_pdf(self, data, **kw):
        if hasattr(data, "read"):
            data = data.read().decode("utf-8")

        # Parse the incoming payload; malformed JSON must not cascade to a 500.
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            _logger.warning("Spreadsheet PDF: malformed JSON payload")
            return request.make_response(
                "The spreadsheet data could not be read. "
                "Please reopen the spreadsheet and try downloading again.",
                headers=[("Content-Type", "text/plain; charset=utf-8")],
                status=400,
            )

        report_name = data.get("name", "Spreadsheet")
        report_date = data.get("report_date", "")
        company = request.env.company

        # Prepare template values
        values = {
            "report_name": report_name,
            "sheets": data.get("sheets", []),
            "company": company,
        }

        try:
            # Render QWeb HTML
            html = request.env["ir.qweb"]._render(
                "spreadsheet_pdf_report_oca.spreadsheet_pdf_content", values
            )

            # Wrap in the main report layout and convert to PDF
            body_html = request.env["ir.qweb"]._render(
                "spreadsheet_pdf_report_oca.spreadsheet_pdf_main",
                {
                    "company": company,
                    "report_name": report_name,
                    "report_date": report_date,
                    "content": html,
                },
            )

            # Ensure body_html is a proper UTF-8 string
            if isinstance(body_html, bytes):
                body_html = body_html.decode("utf-8")

            # Convert HTML to PDF via wkhtmltopdf. UTF-8 is guaranteed by the
            # template's <meta charset="UTF-8">; landscape + margins by its
            # @page CSS. (specific_paperformat_args is ignored by
            # _build_wkhtmltopdf_args in saas-19.4, so it is not passed.)
            pdf_content = request.env[
                "ir.actions.report"
            ]._run_pdf_engine_without_processing(
                "wkhtmltopdf",
                [body_html],
                landscape=True,
            )
        except Exception:
            _logger.exception("Spreadsheet PDF: rendering/conversion failed")
            return request.make_response(
                "The PDF could not be generated. Please try again; "
                "if the problem persists, contact your administrator.",
                headers=[("Content-Type", "text/plain; charset=utf-8")],
                status=500,
            )

        filename = f"{report_name}.pdf"
        return request.make_response(
            pdf_content,
            [
                ("Content-Length", len(pdf_content)),
                ("Content-Type", "application/pdf"),
                ("X-Content-Type-Options", "nosniff"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )
