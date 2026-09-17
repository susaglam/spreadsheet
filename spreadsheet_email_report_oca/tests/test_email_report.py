# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


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
        cls.user_a = new_test_user(
            cls.env,
            login="sheet_report_user_a",
            groups="base.group_user,spreadsheet_oca.group_user",
            email="user.a@example.com",
        )
        cls.user_b = new_test_user(
            cls.env,
            login="sheet_report_user_b",
            groups="base.group_user,spreadsheet_oca.group_user",
            email="user.b@example.com",
        )
        cls.sheet_a = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Sheet of A", "owner_id": cls.user_a.id}
        )
        cls.sheet_b = cls.env["spreadsheet.spreadsheet"].create(
            {"name": "Private sheet of B", "owner_id": cls.user_b.id}
        )

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

    def _mails_of(self, report):
        return self.env["mail.mail"].search(
            [("model", "=", report._name), ("res_id", "=", report.id)]
        )

    # ------------------------------------------------------------------
    # Basics
    # ------------------------------------------------------------------

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

    def test_build_attachment_has_raw_content(self):
        """[DATAS] saas-19.4 drops 'datas': the attachment must carry raw bytes."""
        report = self._make_report()
        attachment = report._build_attachment()
        self.assertEqual(attachment.mimetype, "application/json")
        self.assertGreater(
            attachment.file_size, 0, "the emailed attachment must not be empty"
        )
        payload = json.loads(bytes(attachment.raw).decode("utf-8"))
        self.assertIn("sheets", payload)

    def test_send_advances_schedule(self):
        report = self._make_report()
        previous_next = report.next_send
        sent = report._send_report()
        self.assertEqual(sent, 1)
        self.assertEqual(report.send_count, 1)
        self.assertTrue(report.last_sent)
        self.assertGreater(report.next_send, previous_next)
        mails = self._mails_of(report)
        self.assertTrue(mails, "send_mail should create a mail.mail")
        self.assertTrue(mails.attachment_ids)
        self.assertTrue(all(att.file_size > 0 for att in mails.attachment_ids))

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
        self.template.unlink()
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

    # ------------------------------------------------------------------
    # [TPL] / [FROM] mail template
    # ------------------------------------------------------------------

    def test_rendered_body_has_no_literal_placeholders(self):
        report = self._make_report()
        body = str(self.template._render_field("body_html", report.ids)[report.id])
        self.assertNotIn("{{", body)
        self.assertNotIn("}}", body)
        self.assertIn("Weekly Report", body)
        self.assertIn("Test Sheet", body)

    def test_email_from_is_rendered(self):
        report = self._make_report(
            spreadsheet_id=self.sheet_a.id, owner_id=self.user_a.id
        )
        email_from = self.template._render_field("email_from", report.ids)[report.id]
        self.assertIn("user.a@example.com", email_from)

    # ------------------------------------------------------------------
    # [VAL] validation
    # ------------------------------------------------------------------

    def test_interval_zero_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_report(interval_number=0)
        report = self._make_report()
        with self.assertRaises(ValidationError):
            report.interval_number = -1
            report.flush_recordset()

    def test_invalid_extra_email_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_report(extra_emails="ok@example.com, not-an-address")

    # ------------------------------------------------------------------
    # [H1] access control
    # ------------------------------------------------------------------

    def test_user_cannot_create_report_on_unreadable_spreadsheet(self):
        with self.assertRaises(AccessError):
            self.Report.with_user(self.user_a).create(
                {
                    "name": "Exfiltrate",
                    "spreadsheet_id": self.sheet_b.id,
                    "recipient_ids": [(6, 0, [self.partner_with_email.id])],
                    "extra_emails": "outsider@example.org",
                }
            )

    def test_user_cannot_switch_report_to_unreadable_spreadsheet(self):
        report = self.Report.with_user(self.user_a).create(
            {
                "name": "Mine",
                "spreadsheet_id": self.sheet_a.id,
                "recipient_ids": [(6, 0, [self.partner_with_email.id])],
            }
        )
        with self.assertRaises(AccessError):
            report.write({"spreadsheet_id": self.sheet_b.id})

    def test_user_cannot_assign_report_to_colleague(self):
        report = self.Report.with_user(self.user_a).create(
            {
                "name": "Mine",
                "spreadsheet_id": self.sheet_a.id,
                "recipient_ids": [(6, 0, [self.partner_with_email.id])],
            }
        )
        self.assertEqual(report.owner_id, self.user_a)
        with self.assertRaises(AccessError):
            report.write({"owner_id": self.user_b.id})

    def test_user_cannot_see_or_edit_colleague_report(self):
        report_b = self._make_report(
            name="B's report", spreadsheet_id=self.sheet_b.id, owner_id=self.user_b.id
        )
        visible = self.Report.with_user(self.user_a).search([("id", "=", report_b.id)])
        self.assertFalse(visible)
        with self.assertRaises(AccessError):
            report_b.with_user(self.user_a).write(
                {"extra_emails": "outsider@example.org"}
            )

    def test_owner_must_be_able_to_read_spreadsheet(self):
        with self.assertRaises(ValidationError):
            self._make_report(spreadsheet_id=self.sheet_b.id, owner_id=self.user_a.id)

    def test_cron_skips_report_when_owner_lost_access(self):
        report = self._make_report(
            spreadsheet_id=self.sheet_a.id, owner_id=self.user_a.id
        )
        report.next_send = fields.Datetime.now() - timedelta(hours=1)
        # Revoke: the spreadsheet now belongs to B and is not shared with A.
        self.sheet_a.owner_id = self.user_b
        self.env.flush_all()
        # The read-access cache lives for the whole transaction; a real cron run
        # starts a fresh one.
        self.env.transaction.invalidate_access_cache()

        self.Report._cron_send_email_reports()

        self.assertEqual(report.send_count, 0)
        self.assertFalse(report.last_sent)
        self.assertFalse(self._mails_of(report), "no email may leave")
        self.assertGreater(
            report.next_send,
            fields.Datetime.now(),
            "the skipped occurrence moves to the next slot (no hourly note spam)",
        )
        notes = report.message_ids.filtered(
            lambda m: "can no longer open" in (m.body or "")
        )
        self.assertTrue(notes, "the owner-lost-access skip is noted on the report")

    def test_send_now_warns_when_owner_lost_access(self):
        report = self._make_report(
            spreadsheet_id=self.sheet_a.id, owner_id=self.user_a.id
        )
        self.sheet_a.owner_id = self.user_b
        self.env.flush_all()
        self.env.transaction.invalidate_access_cache()
        result = report.action_send_now()
        self.assertEqual(result["params"]["type"], "warning")
        self.assertEqual(report.send_count, 0)
        self.assertFalse(self._mails_of(report))

    def test_manager_can_reassign_owner(self):
        manager = new_test_user(
            self.env,
            login="sheet_report_manager",
            groups="base.group_user,spreadsheet_oca.group_manager",
        )
        report = self._make_report(
            spreadsheet_id=self.sheet_a.id, owner_id=self.user_a.id
        )
        # B cannot read sheet A -> refused by the owner constraint.
        with self.assertRaises(ValidationError):
            report.with_user(manager).write({"owner_id": self.user_b.id})
        self.sheet_a.reader_ids = [(4, self.user_b.id)]
        self.env.transaction.invalidate_access_cache()
        report.with_user(manager).write({"owner_id": self.user_b.id})
        self.assertEqual(report.owner_id, self.user_b)
