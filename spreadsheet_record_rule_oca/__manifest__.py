# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Record Rule Filter OCA",
    "summary": "Apply user-based record rules to spreadsheet dashboard data sources",
    "version": "saas~19.2.1.0.0",
    "license": "AGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca", "spreadsheet_dashboard"],
    "data": [
        "security/ir.model.access.csv",
        "views/dashboard_rule_views.xml",
    ],
}
