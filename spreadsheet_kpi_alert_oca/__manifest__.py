# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet KPI Alert OCA",
    "summary": "Set threshold alerts on spreadsheet cells with cron-based notifications",
    "version": "saas~19.2.1.0.0",
    "license": "AGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_oca",
        "mail",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "data/mail_template.xml",
        "views/spreadsheet_kpi_alert_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "spreadsheet.o_spreadsheet": [
            (
                "after",
                "spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js",
                "spreadsheet_kpi_alert_oca/static/src/spreadsheet/bundle/*.js",
            ),
        ],
    },
}
