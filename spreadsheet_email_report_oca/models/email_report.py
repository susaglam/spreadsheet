# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class SpreadsheetEmailReport(models.Model):
    _name = "spreadsheet.email.report"
    _description = "Scheduled Spreadsheet Email Report"

    name = fields.Char(
        required=True,
        help="A label for this scheduled report, e.g. 'Weekly Sales Dashboard'. "
        "It appears in the email subject.",
    )
    active = fields.Boolean(
        default=True,
        help="Untick to pause this schedule without deleting it; the cron "
        "ignores inactive reports.",
    )
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        required=True,
        ondelete="cascade",
        help="The spreadsheet whose data is exported as JSON and attached to "
        "each email.",
    )
    recipient_ids = fields.Many2many(
        "res.partner",
        string="Recipients",
        required=True,
        help="Partners who receive the email; only partners that have an email "
        "address are used. Add addresses without a partner via Extra Emails.",
    )
    extra_emails = fields.Char(
        string="Extra Emails",
        help="Comma-separated additional email addresses.",
    )
    format = fields.Selection(
        [
            ("json", "Spreadsheet data (JSON)"),
        ],
        default="json",
        required=True,
        help="Attachment format. The scheduler runs server-side with no "
        "o-spreadsheet JS engine, so it can only export the workbook as its "
        "native JSON; open the file in the Spreadsheets app to view it. "
        "(The old 'Excel (XLSX)' option was mislabelled — it attached JSON "
        "with a .xlsx extension that Excel could not open.)",
    )
    interval_number = fields.Integer(
        default=1,
        help="How often to resend, combined with the interval unit. "
        "Example: 2 + Weeks = every two weeks.",
    )
    interval_type = fields.Selection(
        [
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        default="weeks",
        required=True,
        help="The unit for the interval. Example: 2 + Weeks = every two weeks.",
    )
    last_sent = fields.Datetime(
        readonly=True,
        help="Read-only. When the last successful send happened. Empty until "
        "the first email goes out.",
    )
    next_send = fields.Datetime(
        help="When the next automatic send is due. Editable: set it in the "
        "future to pause, or to now to send on the next hourly cron run.",
    )
    send_count = fields.Integer(
        readonly=True,
        default=0,
        help="Read-only counter of how many times this report has been sent "
        "successfully.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.next_send:
                rec.next_send = fields.Datetime.now()
        return records

    def _get_all_email_addresses(self):
        self.ensure_one()
        addrs = [p.email for p in self.recipient_ids if p.email]
        if self.extra_emails:
            addrs.extend(e.strip() for e in self.extra_emails.split(",") if e.strip())
        return addrs

    @api.model
    def _cron_send_email_reports(self):
        now = fields.Datetime.now()
        reports = self.search(
            [
                ("active", "=", True),
                ("next_send", "<=", now),
            ]
        )
        for report in reports:
            try:
                # Isolate each report in a savepoint so a DB-level error in one
                # send cannot poison the shared cursor and abort the whole batch.
                with self.env.cr.savepoint():
                    report._send_report()
            except Exception as e:
                _logger.error(
                    "Failed to send spreadsheet email report '%s': %s", report.name, e
                )

    def _send_report(self):
        """Send the report to all resolved recipients.

        Returns the number of email addresses the report was actually sent to.
        Returns 0 (without advancing the schedule counters) when there is no
        valid recipient or the mail template is missing, so the report retries
        on the next cron run.
        """
        self.ensure_one()
        emails = self._get_all_email_addresses()
        if not emails:
            return 0

        template = self.env.ref(
            "spreadsheet_email_report_oca.spreadsheet_email_report_template",
            raise_if_not_found=False,
        )
        if not template:
            _logger.warning(
                "Spreadsheet email report '%s': mail template missing; skipping "
                "send, will retry on the next cron run.",
                self.name,
            )
            return 0

        attachment = self._build_attachment()
        # saas-19.4: mail.template.generate_email() was removed. send_mail
        # renders subject/body_html from the template on res_id=self.id and
        # sends immediately; email_values overrides the recipients + attachment.
        template.send_mail(
            self.id,
            force_send=True,
            email_values={
                "email_to": ",".join(emails),
                "attachment_ids": [(4, attachment.id)],
            },
        )

        delta = {self.interval_type: self.interval_number}
        self.write(
            {
                "last_sent": fields.Datetime.now(),
                "next_send": fields.Datetime.now() + relativedelta(**delta),
                "send_count": self.send_count + 1,
            }
        )
        return len(emails)

    def _build_attachment(self):
        self.ensure_one()
        # The scheduler runs server-side with no o-spreadsheet JS engine, so the
        # only artifact it can truthfully produce is the workbook JSON. (The old
        # "xlsx" branch attached base64-encoded JSON with a .xlsx name + OOXML
        # mimetype — a file Excel could not open. Removed; JSON is honest.)
        data = self.spreadsheet_id.spreadsheet_raw or {}
        content = base64.b64encode(
            json.dumps(data, indent=2, default=str).encode("utf-8")
        )
        filename = f"{self.spreadsheet_id.name}.json"
        mimetype = "application/json"

        return self.env["ir.attachment"].create(
            {
                "name": filename,
                "datas": content,
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": mimetype,
            }
        )

    def action_send_now(self):
        """Trigger an immediate send."""
        self.ensure_one()
        sent = self._send_report()
        if sent:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Report Sent"),
                    "message": _("Report '%s' has been sent to recipients.")
                    % self.name,
                    "type": "success",
                },
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Report Not Sent"),
                "message": _(
                    "Report '%s' was not sent: no recipient has a valid email "
                    "address, or the mail template is missing. Add an email to a "
                    "recipient partner or fill Extra Emails."
                )
                % self.name,
                "type": "warning",
            },
        }
