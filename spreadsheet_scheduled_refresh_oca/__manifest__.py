# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Scheduled Refresh OCA",
    "summary": "Bump spreadsheet revision periodically to refresh data sources",
    "version": "saas~19.4.1.0.0",
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
}
