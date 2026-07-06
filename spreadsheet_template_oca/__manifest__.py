# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Template OCA",
    "summary": "Create and use spreadsheet templates",
    "version": "saas~19.4.1.0.2",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": [
        "spreadsheet_oca",
    ],
    "data": [
        "security/security.xml",
        "security/ir.access.csv",
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
