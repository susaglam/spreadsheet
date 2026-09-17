# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import zipfile
from io import BytesIO

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged

CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels"
 ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/{part}" ContentType="{content_type}"/>
</Types>"""

WORKBOOK_CT = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
)
DOCUMENT_CT = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)


def _zip_bytes(members):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return stream.getvalue()


@tagged("post_install", "-at_install")
class TestSpreadsheetUpload(TransactionCase):
    """Uploading a file that is not an .xlsx workbook must teach, not crash."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env,
            login="sheet_upload_user",
            groups="base.group_user,spreadsheet_oca.group_user",
        )

    def _upload(self, name, content):
        # saas-19.4: ir.attachment has no `datas` field any more; a `datas`
        # value is dropped with a warning and the attachment is stored EMPTY.
        attachment = (
            self.env["ir.attachment"]
            .with_user(self.user)
            .create({"name": name, "raw": content})
        )
        # The scenario only proves something if the content really got stored.
        self.assertEqual(attachment.file_size, len(content))
        self.assertEqual(bytes(attachment.raw), content)
        return attachment

    def _assert_invalid_workbook(self, attachment):
        spreadsheets = (
            self.env["spreadsheet.spreadsheet"]
            .with_user(self.user)
            .with_context(lang="en_US")
        )
        with self.assertRaises(UserError) as caught:
            spreadsheets.create_document_from_attachment(attachment.ids)
        # AccessError subclasses UserError: pin the exact type.
        self.assertIs(type(caught.exception), UserError)
        self.assertNotIsInstance(caught.exception, AccessError)
        message = str(caught.exception)
        self.assertIn(attachment.name, message)
        self.assertIn("not a valid Excel workbook", message)
        self.assertFalse(
            self.env["spreadsheet.spreadsheet"].search([("name", "=", attachment.name)])
        )

    def test_invalid_workbook_raises_teaching_user_error(self):
        attachment = self._upload("budget.xlsx", b"this is not a zip archive")
        self._assert_invalid_workbook(attachment)

    def test_zip_that_is_not_a_workbook_is_rejected(self):
        # A valid ZIP (here a Word document) without an Excel workbook part
        # must not be turned into a broken spreadsheet.
        docx = _zip_bytes(
            {
                "[Content_Types].xml": CONTENT_TYPES_XML.format(
                    part="word/document.xml", content_type=DOCUMENT_CT
                ),
                "word/document.xml": "<w:document/>",
            }
        )
        attachment = self._upload("minutes.xlsx", docx)
        self._assert_invalid_workbook(attachment)
        # The uploaded file is kept so the user can retry.
        self.assertTrue(attachment.exists())

    def test_valid_workbook_is_imported(self):
        xlsx = _zip_bytes(
            {
                "[Content_Types].xml": CONTENT_TYPES_XML.format(
                    part="xl/workbook.xml", content_type=WORKBOOK_CT
                ),
                "xl/workbook.xml": "<workbook/>",
                "_rels/.rels": "<Relationships/>",
                "docProps/thumbnail.jpeg": "not extracted",
            }
        )
        attachment = self._upload("forecast.xlsx", xlsx)
        action = (
            self.env["spreadsheet.spreadsheet"]
            .with_user(self.user)
            .create_document_from_attachment(attachment.ids)
        )
        sheet = self.env["spreadsheet.spreadsheet"].browse(action["res_id"])
        self.assertEqual(sheet.name, "forecast.xlsx")
        self.assertEqual(sheet.owner_id, self.user)
        self.assertEqual(
            set(sheet.spreadsheet_raw),
            {"[Content_Types].xml", "xl/workbook.xml", "_rels/.rels"},
        )
        self.assertFalse(attachment.exists())
