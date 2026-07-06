# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import shutil
import unittest

from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestDownloadSpreadsheetPDF(HttpCase):
    """End-to-end coverage for the /spreadsheet/pdf download controller."""

    URL = "/spreadsheet/pdf"

    def _sample_payload(self):
        return {
            "name": "Test Report",
            "report_date": "2026-07-05",
            "sheets": [
                {
                    "name": "Sheet1",
                    "rows": [
                        [
                            {"value": "Header", "bold": True},
                            {"value": "Value", "align": "right"},
                        ],
                        [
                            {"value": "1"},
                            {"value": "2"},
                        ],
                    ],
                }
            ],
        }

    @unittest.skipUnless(
        shutil.which("wkhtmltopdf"),
        "wkhtmltopdf binary not installed in this environment",
    )
    def test_pdf_valid_payload(self):
        """A well-formed authenticated request returns a real PDF."""
        self.authenticate("admin", "admin")
        response = self.url_open(
            self.URL,
            data={"data": json.dumps(self._sample_payload())},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Type"), "application/pdf")
        self.assertTrue(
            response.content.startswith(b"%PDF"),
            "Response body should be a PDF document",
        )

    @unittest.skipUnless(
        shutil.which("wkhtmltopdf"),
        "wkhtmltopdf binary not installed in this environment",
    )
    def test_pdf_empty_sheets(self):
        """A sheet with no rows exercises the 'Empty sheet' branch."""
        self.authenticate("admin", "admin")
        payload = {
            "name": "Empty Report",
            "report_date": "2026-07-05",
            "sheets": [{"name": "Blank", "rows": []}],
        }
        response = self.url_open(self.URL, data={"data": json.dumps(payload)})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_malformed_json(self):
        """Malformed JSON degrades gracefully to a 400, never a raw 500."""
        self.authenticate("admin", "admin")
        response = self.url_open(self.URL, data={"data": "{not valid json"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.content.startswith(b"%PDF"))

    def test_pdf_requires_auth(self):
        """Anonymous callers must not reach the PDF generation."""
        response = self.url_open(
            self.URL,
            data={"data": json.dumps(self._sample_payload())},
            allow_redirects=False,
        )
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(response.content.startswith(b"%PDF"))
