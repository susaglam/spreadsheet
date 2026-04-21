# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Contract & SLA Tracker OCA",
    "summary": "Contract renewal calendar and SLA compliance tracking in spreadsheets",
    "version": "saas~19.2.1.0.0",
    "license": "AGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_oca",
        "spreadsheet_kpi_alert_oca",
        "sale",
        "purchase",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "data/mail_template.xml",
        "views/contract_sla_views.xml",
        "views/res_config_settings_views.xml",
    ],
}
