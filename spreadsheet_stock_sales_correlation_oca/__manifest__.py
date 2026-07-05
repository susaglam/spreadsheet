# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Stock-Sales Correlation Dashboard",
    "summary": "Pre-built dashboard for stock level vs sales velocity analysis",
    "category": "Hidden",
    "version": "saas~19.4.1.0.0",
    "license": "LGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_dashboard", "sale_stock"],
    "data": ["data/dashboards.xml"],
    "installable": True,
    "auto_install": ["sale_stock"],
}
