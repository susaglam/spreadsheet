# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Multi-Company Consolidation OCA",
    "summary": "Consolidated multi-company spreadsheet reports with inter-company elimination",
    "version": "saas~19.2.1.0.0",
    "license": "AGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_oca",
        "account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/consolidation_views.xml",
    ],
}
