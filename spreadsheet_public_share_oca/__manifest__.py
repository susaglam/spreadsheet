# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Public Share OCA",
    "summary": "Token-based read-only public share links for external users",
    "version": "saas~19.4.1.1.1",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca", "spreadsheet_kpi_alert_oca", "portal"],
    "data": [
        "security/ir.access.csv",
        "views/public_share_views.xml",
        "views/public_templates.xml",
        "views/res_config_settings_views.xml",
    ],
}
