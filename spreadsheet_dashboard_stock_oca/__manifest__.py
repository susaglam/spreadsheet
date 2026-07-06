# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Dashboard for Inventory",
    "summary": "Pre-built inventory and stock dashboard",
    "category": "Hidden",
    "version": "saas~19.4.1.0.1",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_dashboard", "stock"],
    "data": ["data/dashboards.xml"],
    "installable": True,
    "auto_install": ["stock"],
}
