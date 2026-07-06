# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Help & Examples OCA",
    "summary": "In-app help, formula reference, tutorials and sample data",
    "version": "saas~19.4.1.0.1",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_oca",
        "web_tour",
    ],
    "data": [
        "security/ir.access.csv",
        "data/help_spreadsheets.xml",
        "data/web_tours.xml",
        "data/tutorials.xml",
        "wizards/sample_data_loader.xml",
        "views/tutorial_views.xml",
        "views/help_menus.xml",
    ],
    "assets": {
        "web.assets_web": [
            "spreadsheet_help_oca/static/src/js/*.js",
        ],
    },
}
