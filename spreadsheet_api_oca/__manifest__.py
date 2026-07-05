# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet REST API OCA",
    "summary": "REST API for spreadsheets — enable Power BI, Google Sheets, webhooks",
    "version": "saas~19.4.1.0.1",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca", "spreadsheet_kpi_alert_oca"],
    "data": [
        "security/ir.access.csv",
        "data/ir_cron.xml",
        "views/api_token_views.xml",
        "views/res_config_settings_views.xml",
    ],
}
