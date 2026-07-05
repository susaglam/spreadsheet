# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo.http import Controller, request, route
from odoo.http.stream import content_disposition


class SpreadsheetDownloadPDF(Controller):
    @route("/spreadsheet/pdf", type="http", auth="user", methods=["POST"])
    def download_spreadsheet_pdf(self, data, **kw):
        if hasattr(data, "read"):
            data = data.read().decode("utf-8")
        data = json.loads(data)

        report_name = data.get("name", "Spreadsheet")
        report_date = data.get("report_date", "")
        company = request.env.company

        # Prepare template values
        values = {
            "report_name": report_name,
            "sheets": data.get("sheets", []),
            "company": company,
        }

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

        # Convert HTML to PDF via wkhtmltopdf with UTF-8 encoding
        paperformat = request.env.ref(
            "spreadsheet_pdf_report_oca.paperformat_spreadsheet_landscape"
        )
        pdf_content = request.env["ir.actions.report"]._run_wkhtmltopdf(
            [body_html],
            report_paperformat_id=paperformat,
            specific_paperformat_args={
                "--encoding": "UTF-8",
            },
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
