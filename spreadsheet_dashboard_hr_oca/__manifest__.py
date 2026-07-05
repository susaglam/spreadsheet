# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Dashboard for HR",
    "summary": "Pre-built human resources dashboard",
    "category": "Hidden",
    "version": "saas~19.4.1.0.0",
    "license": "LGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_dashboard", "hr"],
    "data": ["data/dashboards.xml"],
    "installable": True,
    "auto_install": ["hr"],
}
