# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Record Rule Filter OCA",
    "summary": "Apply user-based record rules to spreadsheet dashboard data sources",
    "version": "saas~19.4.1.0.0",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca", "spreadsheet_dashboard"],
    "data": [
        "security/ir.access.csv",
        "views/dashboard_rule_views.xml",
    ],
}
