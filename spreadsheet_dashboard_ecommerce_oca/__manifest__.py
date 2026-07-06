# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Dashboard for E-commerce",
    "summary": "E-commerce analytics dashboard (revenue, orders, basket)",
    "category": "Hidden",
    "version": "saas~19.4.1.0.1",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_dashboard", "website_sale"],
    "data": ["data/dashboards.xml"],
    "installable": True,
    "auto_install": ["website_sale"],
}
