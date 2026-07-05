# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet PDF Report OCA",
    "summary": "Professional PDF export for spreadsheets with company branding",
    "version": "saas~19.4.1.0.0",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_oca",
    ],
    "data": [
        "report/report_paperformat.xml",
        "report/spreadsheet_pdf_report.xml",
    ],
    "assets": {
        "spreadsheet.o_spreadsheet": [
            (
                "after",
                "spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js",
                "spreadsheet_pdf_report_oca/static/src/spreadsheet/bundle/*.js",
            ),
        ],
    },
}
