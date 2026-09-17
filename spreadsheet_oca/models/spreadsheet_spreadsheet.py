# Copyright 2022 CreuBlanca
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import zipfile
import zlib
from io import BytesIO

from odoo import api, fields, models
from odoo.exceptions import UserError

# Content types o-spreadsheet's XlsxReader accepts as the workbook part
# (CONTENT_TYPES in addons/spreadsheet/static/src/o_spreadsheet/o_spreadsheet.js).
# A ZIP without one of them in [Content_Types].xml (.docx, .odt, plain .zip)
# cannot be opened as a spreadsheet.
XLSX_WORKBOOK_CONTENT_TYPES = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml",
    "application/vnd.ms-excel.template.macroEnabled.main+xml",
    "application/vnd.ms-excel.addin.macroEnabled.main+xml",
)


class SpreadsheetSpreadsheet(models.Model):
    _name = "spreadsheet.spreadsheet"
    _inherit = ["spreadsheet.abstract", "mail.thread", "mail.activity.mixin"]
    _description = "Spreadsheet"

    filename = fields.Char(compute="_compute_filename")
    badge_image = fields.Image("Badge Background", max_width=1024, max_height=1024)
    owner_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda r: r.env.user.id,
        help="The user who owns this spreadsheet. The owner can always open, "
        "edit, share and delete it, as can Spreadsheet managers.",
    )
    contributor_ids = fields.Many2many(
        "res.users",
        relation="spreadsheet_contributor",
        column1="spreadsheet_id",
        column2="user_id",
        string="Contributors",
        help="Users who can open and edit this spreadsheet, but not delete it. "
        "They also need Spreadsheets access (User or Manager). Example: add "
        "the colleague who fills in the monthly figures.",
    )
    contributor_group_ids = fields.Many2many(
        "res.groups",
        relation="spreadsheet_group_contributor",
        column1="spreadsheet_id",
        column2="group_id",
        string="Contributors Groups",
        help="Every member of these groups can open and edit this spreadsheet, "
        "but not delete it, including users who receive the group through "
        "another group. Members also need Spreadsheets access (User or "
        "Manager). Example: share the forecast with the sales group so the "
        "whole sales team can update it.",
    )
    reader_ids = fields.Many2many(
        "res.users",
        relation="spreadsheet_reader",
        column1="spreadsheet_id",
        column2="user_id",
        string="Readers",
        help="Users who can open this spreadsheet in read-only mode. They also "
        "need Spreadsheets access (User or Manager).",
    )
    reader_group_ids = fields.Many2many(
        "res.groups",
        relation="spreadsheet_group_reader",
        column1="spreadsheet_id",
        column2="group_id",
        string="Readers Groups",
        help="Every member of these groups can open this spreadsheet in "
        "read-only mode, including users who receive the group through another "
        "group. Members also need Spreadsheets access (User or Manager). "
        "Example: share a report with a managers group so they can view it "
        "without changing it.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        help="If set, the spreadsheet will be available only"
        " if this company is in the current companies.",
    )

    spreadsheet_tag_ids = fields.Many2many(
        string="Tags", comodel_name="spreadsheet.spreadsheet.tag"
    )

    @api.depends("name")
    def _compute_filename(self):
        unnamed = self.env._("Unnamed")
        for record in self:
            record.filename = f"{record.name or unnamed}.json"

    def _invalid_workbook_error(self, attachment):
        return UserError(
            self.env._(
                'The file "%(file)s" could not be imported because it '
                "is not a valid Excel workbook (.xlsx), so no spreadsheet "
                "was created. Open it in Excel or LibreOffice, save it as "
                '"Excel Workbook (.xlsx)" and upload it again.',
                file=attachment.name,
            )
        )

    def _extract_xlsx_attachment(self, attachment):
        """Return ``{member name: xml text}`` for an .xlsx attachment.

        Raise a UserError (never a raw zipfile/decoding error) when the
        content is not a ZIP archive, cannot be read, or is a ZIP that is not
        an Excel workbook: importing it anyway would create a broken
        spreadsheet and delete the uploaded file.
        """
        try:
            with zipfile.ZipFile(BytesIO(bytes(attachment.raw or b"")), "r") as xlsx:
                extracted = {
                    name: xlsx.read(name).decode("UTF8")
                    for name in xlsx.namelist()
                    if name.endswith((".xml", ".rels"))
                }
        except (zipfile.BadZipFile, zlib.error, EOFError, UnicodeDecodeError) as error:
            raise self._invalid_workbook_error(attachment) from error
        content_types = extracted.get("[Content_Types].xml", "")
        if not any(ctype in content_types for ctype in XLSX_WORKBOOK_CONTENT_TYPES):
            raise self._invalid_workbook_error(attachment)
        return extracted

    def create_document_from_attachment(self, attachment_ids):
        attachments = self.env["ir.attachment"].browse(attachment_ids)
        spreadsheets = self.env["spreadsheet.spreadsheet"]
        for attachment in attachments:
            spreadsheets |= self.create(
                {
                    "spreadsheet_raw": self._extract_xlsx_attachment(attachment),
                    "name": attachment.name,
                }
            )
        attachments.unlink()
        if len(spreadsheets) == 1:
            # saas-19.4: get_formview_action() was renamed
            # get_record_default_action() (base/models/ir_ui_view.py).
            return spreadsheets.get_record_default_action()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "spreadsheet_oca.spreadsheet_spreadsheet_act_window"
        )
        action["domain"] = [("id", "in", spreadsheets.ids)]
        return action
