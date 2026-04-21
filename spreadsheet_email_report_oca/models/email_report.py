# Copyright 2026 Badkamertien
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

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        required=True,
        ondelete="cascade",
    )
    recipient_ids = fields.Many2many(
        "res.partner",
        string="Recipients",
        required=True,
    )
    extra_emails = fields.Char(
        string="Extra Emails",
        help="Comma-separated additional email addresses.",
    )
    format = fields.Selection(
        [
            ("xlsx", "Excel (XLSX)"),
            ("json", "JSON Data"),
        ],
        default="xlsx",
        required=True,
    )
    interval_number = fields.Integer(default=1)
    interval_type = fields.Selection(
        [
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        default="weeks",
        required=True,
    )
    last_sent = fields.Datetime(readonly=True)
    next_send = fields.Datetime()
    send_count = fields.Integer(readonly=True, default=0)

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
                report._send_report()
            except Exception as e:
                _logger.error(
                    "Failed to send spreadsheet email report '%s': %s", report.name, e
                )

    def _send_report(self):
        self.ensure_one()
        emails = self._get_all_email_addresses()
        if not emails:
            return

        attachment = self._build_attachment()
        template = self.env.ref(
            "spreadsheet_email_report_oca.spreadsheet_email_report_template",
            raise_if_not_found=False,
        )
        if template:
            mail_values = template.generate_email(self.id, ["subject", "body_html"])
            mail_values["email_to"] = ",".join(emails)
            mail_values["attachment_ids"] = [(4, attachment.id)]
            mail = self.env["mail.mail"].sudo().create(mail_values)
            mail.send()

        delta = {self.interval_type: self.interval_number}
        self.write(
            {
                "last_sent": fields.Datetime.now(),
                "next_send": fields.Datetime.now() + relativedelta(**delta),
                "send_count": self.send_count + 1,
            }
        )

    def _build_attachment(self):
        self.ensure_one()
        if self.format == "json":
            data = self.spreadsheet_id.spreadsheet_raw or {}
            content = base64.b64encode(
                json.dumps(data, indent=2, default=str).encode("utf-8")
            )
            filename = f"{self.spreadsheet_id.name}.json"
            mimetype = "application/json"
        else:
            content = self.spreadsheet_id.spreadsheet_binary_data or b""
            filename = f"{self.spreadsheet_id.name}.xlsx"
            mimetype = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

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
        self._send_report()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Report Sent"),
                "message": _("Report '%s' has been sent to recipients.") % self.name,
                "type": "success",
            },
        }
