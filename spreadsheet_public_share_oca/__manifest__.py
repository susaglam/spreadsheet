# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Public Share OCA",
    "summary": "Token-based read-only public share links for external users",
    "version": "saas~19.2.1.0.0",
    "license": "AGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca", "spreadsheet_kpi_alert_oca", "portal"],
    "data": [
        "security/ir.model.access.csv",
        "views/public_share_views.xml",
        "views/public_templates.xml",
        "views/res_config_settings_views.xml",
    ],
}
