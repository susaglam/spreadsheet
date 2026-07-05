# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Email Report OCA",
    "summary": "Scheduled email delivery of spreadsheet reports (JSON attached)",
    "version": "saas~19.4.1.1.0",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca", "spreadsheet_kpi_alert_oca", "mail"],
    "data": [
        "security/ir.access.csv",
        "data/ir_cron.xml",
        "data/mail_template.xml",
        "views/email_report_views.xml",
    ],
}
