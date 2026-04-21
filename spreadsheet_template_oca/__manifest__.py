# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Template OCA",
    "summary": "Create and use spreadsheet templates",
    "version": "saas~19.2.1.0.0",
    "license": "AGPL-3",
    "author": "Badkamertien,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_oca",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/spreadsheet_template_category.xml",
        "views/spreadsheet_template_category_views.xml",
        "views/spreadsheet_template_views.xml",
        "views/spreadsheet_template_menus.xml",
        "wizards/spreadsheet_to_template.xml",
        "wizards/spreadsheet_from_template.xml",
    ],
    "assets": {
        "spreadsheet.o_spreadsheet": [
            (
                "after",
                "spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js",
                "spreadsheet_template_oca/static/src/spreadsheet/bundle/*.js",
            ),
        ],
    },
}
