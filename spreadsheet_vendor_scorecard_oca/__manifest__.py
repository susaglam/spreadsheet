# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Vendor Scorecard OCA",
    "summary": "Supplier performance scorecard with delivery, quality and lead time metrics",
    "version": "saas~19.2.1.0.0",
    "license": "AGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_dashboard",
        "spreadsheet_oca",
        "purchase_stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/dashboards.xml",
        "views/vendor_scorecard_views.xml",
    ],
    "installable": True,
}
