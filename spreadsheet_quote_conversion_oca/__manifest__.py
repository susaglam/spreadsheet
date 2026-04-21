# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Quote-to-Order Conversion Dashboard",
    "summary": "Pre-built dashboard for quote-to-order conversion rate analysis",
    "category": "Hidden",
    "version": "saas~19.2.1.0.0",
    "license": "LGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_dashboard", "sale"],
    "data": ["data/dashboards.xml"],
    "installable": True,
    "auto_install": False,
}
