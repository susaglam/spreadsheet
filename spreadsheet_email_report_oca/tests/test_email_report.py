# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSpreadsheetEmailReport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Report = cls.env["spreadsheet.email.report"]
        cls.spreadsheet = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Test Sheet"}
        )
        cls.partner_with_email = cls.env["res.partner"].create(
            {"name": "Alice", "email": "alice@example.com"}
        )
        cls.partner_no_email = cls.env["res.partner"].create({"name": "Bob"})
        # saas-19.4 mail.template.auto_delete defaults to True, which unlinks the
        # mail.mail right after sending; disable it so tests can assert the sent
        # record exists.
        cls.template = cls.env.ref(
            "spreadsheet_email_report_oca.spreadsheet_email_report_template"
        )
        cls.template.auto_delete = False

    def _make_report(self, **overrides):
        vals = {
            "name": "Weekly Report",
            "spreadsheet_id": self.spreadsheet.id,
            "recipient_ids": [(6, 0, [self.partner_with_email.id])],
            "interval_number": 2,
            "interval_type": "weeks",
        }
        vals.update(overrides)
        return self.Report.create(vals)

    def test_create_sets_next_send(self):
        report = self._make_report()
        self.assertTrue(report.next_send, "create() should seed next_send")

    def test_get_all_email_addresses_parses_extra(self):
        report = self._make_report(extra_emails=" a@b.com, c@d.com ,")
        addrs = report._get_all_email_addresses()
        self.assertIn("alice@example.com", addrs)
        self.assertIn("a@b.com", addrs)
        self.assertIn("c@d.com", addrs)
        # empty fragment after the trailing comma is dropped
        self.assertNotIn("", addrs)

    def test_build_attachment_is_valid_json(self):
        report = self._make_report()
        attachment = report._build_attachment()
        self.assertEqual(attachment.mimetype, "application/json")
        decoded = base64.b64decode(attachment.datas)
        # Must round-trip through json without raising.
        json.loads(decoded.decode("utf-8"))

    def test_send_advances_schedule(self):
        report = self._make_report()
        previous_next = report.next_send
        sent = report._send_report()
        self.assertEqual(sent, 1)
        self.assertEqual(report.send_count, 1)
        self.assertTrue(report.last_sent)
        self.assertGreater(report.next_send, previous_next)
        mails = self.env["mail.mail"].search(
            [("model", "=", report._name), ("res_id", "=", report.id)]
        )
        self.assertTrue(mails, "send_mail should create a mail.mail")

    def test_no_valid_email_does_not_advance(self):
        report = self._make_report(
            recipient_ids=[(6, 0, [self.partner_no_email.id])],
            extra_emails=False,
        )
        sent = report._send_report()
        self.assertEqual(sent, 0)
        self.assertEqual(report.send_count, 0)
        self.assertFalse(report.last_sent)

    def test_missing_template_does_not_mark_sent(self):
        report = self._make_report()
        template = self.env.ref(
            "spreadsheet_email_report_oca.spreadsheet_email_report_template"
        )
        template.unlink()
        sent = report._send_report()
        self.assertEqual(sent, 0)
        self.assertEqual(report.send_count, 0)
        self.assertFalse(report.last_sent)

    def test_action_send_now_warns_without_email(self):
        report = self._make_report(
            recipient_ids=[(6, 0, [self.partner_no_email.id])],
            extra_emails=False,
        )
        result = report.action_send_now()
        self.assertEqual(result["params"]["type"], "warning")

    def test_action_send_now_success(self):
        report = self._make_report()
        result = report.action_send_now()
        self.assertEqual(result["params"]["type"], "success")

    def test_cron_isolates_failing_report(self):
        good = self._make_report(name="Good")
        bad = self._make_report(name="Bad")
        original = type(self.Report)._send_report

        def side_effect(records, *args, **kwargs):
            if records.id == bad.id:
                raise ValueError("boom")
            return original(records, *args, **kwargs)

        with patch.object(
            type(self.Report), "_send_report", autospec=True, side_effect=side_effect
        ):
            # Must not raise even though 'bad' blows up.
            self.Report._cron_send_email_reports()
        self.assertEqual(good.send_count, 1)
