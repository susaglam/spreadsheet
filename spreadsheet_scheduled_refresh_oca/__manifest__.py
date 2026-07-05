# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Scheduled Refresh OCA",
    "summary": "Periodically refresh open spreadsheets' data sources via the bus",
    "version": "saas~19.4.1.1.0",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca", "spreadsheet_kpi_alert_oca"],
    "data": [
        "security/ir.access.csv",
        "data/ir_cron.xml",
        "views/refresh_schedule_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "spreadsheet.o_spreadsheet": [
            (
                "after",
                "spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js",
                "spreadsheet_scheduled_refresh_oca/static/src/spreadsheet/bundle/*.js",
            ),
        ],
    },
}
