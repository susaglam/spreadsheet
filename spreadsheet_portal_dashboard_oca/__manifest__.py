# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Portal Dashboard OCA",
    "summary": "Share spreadsheet dashboards with portal users (dealers/distributors)",
    "version": "saas~19.4.1.1.0",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_dashboard_oca",
        "portal",
    ],
    "data": [
        "security/security.xml",
        "security/ir.access.csv",
        "views/spreadsheet_portal_dashboard_views.xml",
        "views/portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "spreadsheet_portal_dashboard_oca/static/src/spreadsheet/bundle/*.js",
            "spreadsheet_portal_dashboard_oca/static/src/spreadsheet/bundle/*.scss",
        ],
    },
}
