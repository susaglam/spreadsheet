# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Spreadsheet Forecast Functions OCA",
    "summary": "ODOO.FORECAST() and ODOO.TREND() spreadsheet functions",
    "version": "saas~19.4.1.0.1",
    "license": "AGPL-3",
    "author": "Codesnap,Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/spreadsheet",
    "depends": ["spreadsheet_oca"],
    "data": [],
    "assets": {
        "spreadsheet.o_spreadsheet": [
            (
                "after",
                "spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js",
                "spreadsheet_forecast_oca/static/src/spreadsheet/bundle/*.js",
            ),
        ],
    },
}
