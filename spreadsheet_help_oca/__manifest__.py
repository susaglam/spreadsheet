# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Help & Examples OCA",
    "summary": "In-app help, formula reference, tutorials, sample data loader, interactive tour",
    "version": "saas~19.2.1.0.0",
    "license": "AGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_oca",
        "web_tour",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/help_spreadsheets.xml",
        "data/web_tours.xml",
        "data/tutorials.xml",
        "wizards/sample_data_loader.xml",
        "views/tutorial_views.xml",
        "views/help_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "spreadsheet_help_oca/static/src/js/*.js",
        ],
    },
}
