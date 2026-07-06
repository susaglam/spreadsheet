# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Vendor Scorecard OCA",
    "summary": "Supplier scorecard: delivery, lead time and quality metrics",
    "version": "saas~19.4.1.0.1",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_dashboard",
        "spreadsheet_oca",
        "purchase_stock",
    ],
    "data": [
        "security/ir.access.csv",
        "data/dashboards.xml",
        "views/vendor_scorecard_views.xml",
    ],
    "installable": True,
}
