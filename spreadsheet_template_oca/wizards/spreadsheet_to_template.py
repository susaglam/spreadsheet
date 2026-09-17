# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.exceptions import UserError


class SpreadsheetToTemplate(models.TransientModel):
    _name = "spreadsheet.to.template"
    _description = "Save Spreadsheet as Template"

    name = fields.Char(
        "Template Name",
        required=True,
        compute="_compute_name",
        store=True,
        readonly=False,
        precompute=True,
        help="Name of the template as it will appear in the template gallery. "
        "Defaults to the current spreadsheet name.",
    )
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        readonly=True,
        required=True,
        help="The spreadsheet whose current contents will be saved as a "
        "reusable template.",
    )
    description = fields.Text(
        help="What this template is for and when to use it — shown on the "
        "template's kanban card.",
    )
    category_id = fields.Many2one(
        "spreadsheet.template.category",
        string="Category",
        help="Optional grouping (Sales, Finance, HR...) used to organise "
        "templates in the gallery search panel.",
    )

    @api.depends("spreadsheet_id.name")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.spreadsheet_id.name

    def _check_template_create_access(self):
        """Raise a teaching UserError when the user may not create templates.

        The wizard itself stays accessible to every spreadsheet user (see
        security/ir.access.csv) on purpose: if its ACL were restricted, a
        plain user reaching it would get Odoo's raw AccessError from the
        form's onchange. Checking here turns that dead end into a message
        that says what is missing and who can grant it.
        """
        if self.env["spreadsheet.template"].has_access("create"):
            return
        raise UserError(
            self.env._(
                "You cannot save this spreadsheet as a template: creating "
                "templates is reserved for Template Managers, because a "
                "template is shared with every spreadsheet user. Ask an "
                "administrator to give you the 'Template Manager' access "
                "right for Spreadsheets (Settings > Users & Companies > "
                "Users, Access Rights tab), or ask a Template Manager to "
                "save this spreadsheet as a template for you."
            )
        )

    @api.model
    def default_get(self, fields_list):
        # Fail when the dialog opens, not after the user filled in the form.
        self._check_template_create_access()
        return super().default_get(fields_list)

    def create_template(self):
        self.ensure_one()
        # Authoritative check: the wizard can be reached without the dialog
        # (RPC, server action), so do not rely on default_get alone.
        self._check_template_create_access()
        spreadsheet_data = self.spreadsheet_id.get_spreadsheet_data()
        spreadsheet_raw = spreadsheet_data["spreadsheet_raw"]
        template = self.env["spreadsheet.template"].create(
            {
                "name": self.name,
                "description": self.description,
                "category_id": self.category_id.id if self.category_id else False,
                "spreadsheet_raw": spreadsheet_raw,
            }
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.name,
                "message": self.env._("Template created successfully."),
                "type": "success",
                "next": template.open_spreadsheet(),
            },
        }
