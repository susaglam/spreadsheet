# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Version History OCA",
    "summary": "Snapshot, diff and rollback spreadsheet versions with full audit trail",
    "version": "saas~19.2.1.0.0",
    "license": "AGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca"],
    "data": [
        "security/ir.model.access.csv",
        "views/version_views.xml",
    ],
}
