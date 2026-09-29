# Copyright 2022 CreuBlanca
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class SpreadsheetSpreadsheetImport(models.TransientModel):
    _name = "spreadsheet.spreadsheet.import"
    _description = "Import data to spreadsheet"

    @api.model
    def _default_mode_id(self):
        return self.env["spreadsheet.spreadsheet.import.mode"].search([], limit=1).id

    name = fields.Char(
        help="Name of the spreadsheet created for this data. "
        "Example: Sales analysis 2026.",
    )
    datasource_name = fields.Char(
        help="Name of the inserted pivot, list or chart inside the spreadsheet. "
        "It also titles the chart, and names the new sheet when adding to an "
        "existing spreadsheet. Example: Sales by salesperson.",
    )
    mode_id = fields.Many2one(
        "spreadsheet.spreadsheet.import.mode",
        required=True,
        default=lambda r: r._default_mode_id(),
        help="Where the data goes: a new spreadsheet created for it, or a new "
        "sheet of an existing spreadsheet, whose current sheets stay untouched.",
    )
    mode = fields.Char(related="mode_id.code")
    import_data = fields.Serialized()
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        help="The existing spreadsheet receiving the data on a new sheet. Only "
        "spreadsheets you own or contribute to are listed.",
    )
    can_be_dynamic = fields.Boolean()
    is_tree = fields.Boolean()
    dynamic = fields.Boolean(
        "Dynamic Rows",
        help="Checked: insert a single formula (=PIVOT or =ODOO.LIST) whose rows "
        "and columns follow new records and the spreadsheet filters. Unchecked: "
        "insert one formula per cell, so the table layout stays exactly as it "
        "is now. Example: keep it checked for a monthly sales pivot that must "
        "show new salespeople automatically.",
    )
    number_of_rows = fields.Integer(
        help="How many records the inserted list shows, starting from the first "
        "one in the list order. Example: 20 for a top-20 of the latest orders.",
    )

    def insert_pivot(self):
        self.ensure_one()
        # The editor (spreadsheet_action.esm.js) reads the insertion mode from
        # the import data. Stored before dispatching so that every
        # _insert_pivot_<mode> variant, including those of other modules,
        # forwards it.
        self.import_data = dict(self.import_data or {}, dynamic=self.dynamic)
        return getattr(self, f"_insert_pivot_{self.mode_id.code}")()

    def _create_spreadsheet_vals(self):
        return {"name": self.name}

    def _insert_pivot_new(self):
        spreadsheet = self.env["spreadsheet.spreadsheet"].create(
            self._create_spreadsheet_vals()
        )
        import_data = self.import_data
        import_data["name"] = self.datasource_name
        import_data["new"] = 1
        if self.dynamic:
            import_data["dyn_number_of_rows"] = self.number_of_rows
        return {
            "type": "ir.actions.client",
            "tag": "action_spreadsheet_oca",
            "params": {
                "model": spreadsheet._name,
                "spreadsheet_id": spreadsheet.id,
                "import_data": import_data,
            },
        }

    def _insert_pivot_add(self):
        import_data = self.import_data
        import_data["name"] = self.datasource_name
        if self.dynamic:
            import_data["dyn_number_of_rows"] = self.number_of_rows
        return {
            "type": "ir.actions.client",
            "tag": "action_spreadsheet_oca",
            "params": {
                "model": "spreadsheet.spreadsheet",
                "spreadsheet_id": self.spreadsheet_id.id,
                "import_data": import_data,
            },
        }
