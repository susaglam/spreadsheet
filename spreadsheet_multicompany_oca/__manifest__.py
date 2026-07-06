# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Multi-Company Consolidation OCA",
    "summary": "Consolidated multi-company reports with inter-company elimination",
    "version": "saas~19.4.1.0.1",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_oca",
        "account",
    ],
    "data": [
        "security/ir.access.csv",
        "views/consolidation_views.xml",
    ],
}
