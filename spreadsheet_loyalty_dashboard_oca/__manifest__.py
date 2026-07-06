# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Loyalty Dashboard",
    "summary": "Pre-built loyalty program analytics dashboard",
    "category": "Hidden",
    "version": "saas~19.4.1.0.1",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_dashboard", "loyalty", "sales_team"],
    "data": ["data/dashboards.xml"],
    "installable": True,
    "auto_install": ["loyalty"],
}
