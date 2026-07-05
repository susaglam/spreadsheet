# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Period Comparison OCA",
    "summary": "Period-over-period comparison functions (ODOO.COMPARE_PERIOD, ODOO.PERCENT_CHANGE)",
    "version": "saas~19.4.1.0.0",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca"],
    "assets": {
        "spreadsheet.o_spreadsheet": [
            (
                "after",
                "spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js",
                "spreadsheet_period_comparison_oca/static/src/spreadsheet/bundle/*.js",
            ),
        ],
    },
}
