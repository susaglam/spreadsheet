# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models
from odoo.api import SUPERUSER_ID
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.mail import email_normalize

_logger = logging.getLogger(__name__)

TEMPLATE_XMLID = "spreadsheet_email_report_oca.spreadsheet_email_report_template"
MANAGER_GROUP = "spreadsheet_oca.group_manager"


def _record_id(value):
    """Return the database id of a Many2one value given in create/write vals."""
    if isinstance(value, models.BaseModel):
        return value.id
    return value


class SpreadsheetEmailReport(models.Model):
    _name = "spreadsheet.email.report"
    _inherit = ["mail.thread"]
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
        "each email. You can only pick a spreadsheet you are allowed to open.",
    )
    owner_id = fields.Many2one(
        "res.users",
        string="Owner",
        required=True,
        default=lambda self: self.env.user,
        index=True,
        help="The user this report is sent on behalf of. Every send checks that "
        "the owner can still open the spreadsheet; if not, the send is skipped "
        "and a note is posted here. Only the owner and Spreadsheet managers can "
        "see the report, and only managers can hand it to another user.",
    )
    recipient_ids = fields.Many2many(
        "res.partner",
        string="Recipients",
        required=True,
        help="Partners who receive the email; only partners that have an email "
        "address are used. Add addresses without a partner via Extra Emails.",
    )
    extra_emails = fields.Char(
        help="Additional email addresses without a contact record, separated by "
        "commas. Example: finance@example.com, ceo@example.com",
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
        help="How often to resend, combined with the interval unit; must be 1 "
        "or more. Example: 2 + Weeks = every two weeks.",
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

    # ------------------------------------------------------------------
    # CRUD + security guards
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_writer_rights(vals)
        records = super().create(vals_list)
        for rec in records:
            if not rec.next_send:
                rec.next_send = fields.Datetime.now()
        return records

    def write(self, vals):
        self._check_writer_rights(vals)
        return super().write(vals)

    @api.model
    def _check_writer_rights(self, vals):
        """Refuse values a non-superuser writer is not entitled to set.

        This runs in create/write (not in an ``@api.constrains``) because
        constraints are evaluated in sudo mode and would no longer know whether
        the caller was a real user or trusted server code.
        """
        if self.env.su:
            return
        user = self.env.user
        sheet_id = _record_id(vals.get("spreadsheet_id"))
        if sheet_id:
            spreadsheet = self.env["spreadsheet.spreadsheet"].browse(sheet_id).exists()
            if spreadsheet and not spreadsheet.has_access("read"):
                raise AccessError(
                    self.env._(
                        "You cannot schedule an email report for spreadsheet "
                        "#%(spreadsheet_id)s because you are not allowed to open "
                        "it. The report attaches the complete workbook, so it may "
                        "only use spreadsheets you can read. Ask the spreadsheet "
                        "owner to add you as a reader or contributor, or pick "
                        "another spreadsheet.",
                        spreadsheet_id=spreadsheet.id,
                    )
                )
        if "owner_id" in vals:
            owner_id = _record_id(vals["owner_id"])
            if owner_id and owner_id != user.id and not user.has_group(MANAGER_GROUP):
                raise AccessError(
                    self.env._(
                        "You cannot hand a scheduled email report to another user. "
                        "Reports are sent with their owner's access rights, so "
                        "changing the owner could email data you are not allowed "
                        "to see. Keep yourself as owner, or ask a Spreadsheet "
                        "manager to reassign the report."
                    )
                )

    @api.constrains("owner_id", "spreadsheet_id")
    def _check_owner_can_read_spreadsheet(self):
        for report in self:
            if report.owner_id and report.spreadsheet_id:
                if not report._owner_can_read_spreadsheet():
                    raise ValidationError(
                        self.env._(
                            "%(owner)s cannot open the spreadsheet "
                            "'%(spreadsheet)s', so they cannot own the scheduled "
                            "report '%(report)s'. Reports are sent with their "
                            "owner's access rights, and emailing a workbook the "
                            "owner may not read would leak data. Share the "
                            "spreadsheet with %(owner)s (as reader or "
                            "contributor) or choose another owner.",
                            owner=report.owner_id.display_name,
                            spreadsheet=report.spreadsheet_id.display_name,
                            report=report.name,
                        )
                    )

    @api.constrains("interval_number")
    def _check_interval_number(self):
        for report in self:
            if report.interval_number < 1:
                raise ValidationError(
                    self.env._(
                        "The interval of report '%(report)s' must be at least 1 "
                        "(it is %(value)s). With 0 or a negative number the report "
                        "would be emailed again on every hourly scheduler run. "
                        "Enter 1 or more, e.g. 1 + Weeks for a weekly email.",
                        report=report.name,
                        value=report.interval_number,
                    )
                )

    @api.constrains("extra_emails")
    def _check_extra_emails(self):
        for report in self:
            invalid = [
                address
                for address in report._split_extra_emails()
                if not email_normalize(address)
            ]
            if invalid:
                raise ValidationError(
                    self.env._(
                        "Report '%(report)s' has invalid addresses in Extra "
                        "Emails: %(addresses)s. Mail to a malformed address is "
                        "never delivered, so those people would silently miss the "
                        "report. Separate addresses with commas and write each one "
                        "as name@example.com.",
                        report=report.name,
                        addresses=", ".join(invalid),
                    )
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _split_extra_emails(self):
        self.ensure_one()
        return [e.strip() for e in (self.extra_emails or "").split(",") if e.strip()]

    def _get_all_email_addresses(self):
        self.ensure_one()
        addrs = [p.email for p in self.recipient_ids if p.email]
        addrs.extend(self._split_extra_emails())
        return addrs

    def _spreadsheet_as_owner(self):
        """Return the spreadsheet in an environment of the report owner.

        ``allowed_company_ids`` is dropped from the context: it belongs to the
        user who triggered the call (e.g. a manager clicking Send Now) and would
        raise "Access to unauthorized or invalid companies" when evaluated for
        an owner who is not in those companies. Without it the owner's own
        companies are used, which is what the access rules should see.
        """
        self.ensure_one()
        context = dict(self.env.context)
        context.pop("allowed_company_ids", None)
        # Not with_context(context): it copies allowed_company_ids back from the
        # current context whenever the new context lacks that key.
        owner_env = self.env(context=context)
        return self.spreadsheet_id.with_env(owner_env).with_user(self.owner_id)

    def _owner_can_read_spreadsheet(self):
        self.ensure_one()
        if not self.owner_id or not self.spreadsheet_id:
            return False
        try:
            return self._spreadsheet_as_owner().has_access("read")
        except Exception:
            # Graceful degradation: an error while evaluating access rules must
            # never be read as "allowed", and must not crash the batch either.
            _logger.warning(
                "Spreadsheet email report %s: could not evaluate the owner's read "
                "access to the spreadsheet; treating it as denied.",
                self.id,
                exc_info=True,
            )
            return False

    def _get_send_blocker(self):
        """Return a user-facing reason why this report must not be sent now,
        or ``False`` when sending is allowed."""
        self.ensure_one()
        owner = self.owner_id
        if not owner:
            return self.env._(
                "The report has no owner, so nobody's access rights can be checked. "
                "A Spreadsheet manager must set an owner who can open the "
                "spreadsheet."
            )
        if owner.id != SUPERUSER_ID and not owner.active:
            return self.env._(
                "The owner %(owner)s is archived, so the report no longer runs on "
                "behalf of an active user. A Spreadsheet manager can assign an "
                "active owner who can open the spreadsheet.",
                owner=owner.display_name,
            )
        if not self._owner_can_read_spreadsheet():
            return self.env._(
                "The owner %(owner)s can no longer open the spreadsheet "
                "'%(spreadsheet)s', so the workbook was not emailed (sending it "
                "would leak data the owner may not see). Share the spreadsheet "
                "with %(owner)s again, or let a Spreadsheet manager assign another "
                "owner.",
                owner=owner.display_name,
                spreadsheet=self.spreadsheet_id.sudo().display_name,
            )
        return False

    def _skip_blocked_occurrence(self, reason):
        """Skip this occurrence: log, post a note and move to the next slot.

        Advancing ``next_send`` (without touching ``last_sent``/``send_count``)
        keeps the hourly cron from posting the same note every hour; the report
        retries on its next scheduled date.
        """
        self.ensure_one()
        _logger.warning(
            "Spreadsheet email report '%s' (id %s) skipped: %s",
            self.name,
            self.id,
            reason,
        )
        report = self.sudo()
        report.next_send = fields.Datetime.now() + report._get_interval_delta()
        try:
            report._message_log(
                body=Markup("<p>%s</p>")
                % self.env._(
                    "Scheduled send skipped. %(reason)s Next attempt: %(next_send)s "
                    "(UTC).",
                    reason=reason,
                    next_send=fields.Datetime.to_string(report.next_send),
                )
            )
        except Exception:
            _logger.warning(
                "Spreadsheet email report %s: could not post the skip note.",
                self.id,
                exc_info=True,
            )

    def _get_interval_delta(self):
        self.ensure_one()
        return relativedelta(**{self.interval_type: max(self.interval_number, 1)})

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    @api.model
    def _cron_send_email_reports(self):
        now = fields.Datetime.now()
        # sudo: this is a system pass over every user's schedules. Each report
        # is then gated on its OWNER's access to the spreadsheet below, so the
        # cron's own user (root) grants nobody anything.
        reports = self.sudo().search(
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
                    # The skip note is written for the owner: use their language.
                    owner_lang = report.owner_id.lang
                    report_in_lang = (
                        report.with_context(lang=owner_lang) if owner_lang else report
                    )
                    blocker = report_in_lang._get_send_blocker()
                    if blocker:
                        report_in_lang._skip_blocked_occurrence(blocker)
                        continue
                    report._send_report()
            except Exception as e:
                _logger.error(
                    "Failed to send spreadsheet email report '%s': %s", report.name, e
                )

    def _send_report(self):
        """Send the report to all resolved recipients.

        Returns the number of email addresses the report was actually sent to.
        Returns 0 (without advancing the schedule counters) when the owner may
        not read the spreadsheet, there is no valid recipient or the mail
        template is missing, so the report retries on the next cron run.
        """
        self.ensure_one()
        blocker = self._get_send_blocker()
        if blocker:
            _logger.warning(
                "Spreadsheet email report '%s' (id %s) not sent: %s",
                self.name,
                self.id,
                blocker,
            )
            return 0

        emails = self._get_all_email_addresses()
        if not emails:
            return 0

        template = self.env.ref(TEMPLATE_XMLID, raise_if_not_found=False)
        if not template:
            _logger.warning(
                "Spreadsheet email report '%s': mail template missing; skipping "
                "send, will retry on the next cron run.",
                self.name,
            )
            return 0

        now = fields.Datetime.now()
        attachment = self._build_attachment()
        # saas-19.4: mail.template.generate_email() was removed. send_mail
        # renders subject/body_html from the template on res_id=self.id and
        # sends immediately; email_values overrides the recipients + attachment.
        # sudo: the workbook content was already read with the OWNER's rights
        # in _build_attachment; the template/mail machinery itself is system
        # plumbing the owner does not need rights on.
        template.sudo().with_context(
            report_generated_at=fields.Datetime.to_string(now)
        ).send_mail(
            self.id,
            force_send=True,
            email_values={
                "email_to": ",".join(emails),
                "attachment_ids": [(4, attachment.id)],
            },
        )

        self.sudo().write(
            {
                "last_sent": now,
                "next_send": now + self._get_interval_delta(),
                "send_count": self.send_count + 1,
            }
        )
        return len(emails)

    def _build_attachment(self):
        self.ensure_one()
        # The scheduler runs server-side with no o-spreadsheet JS engine, so the
        # only artifact it can truthfully produce is the workbook JSON.
        # Security: the workbook is read in the OWNER's environment, so a
        # report can never export data its owner is not allowed to open.
        spreadsheet = self._spreadsheet_as_owner()
        spreadsheet.check_access("read")
        data = spreadsheet.spreadsheet_raw or {}
        content = json.dumps(data, indent=2, default=str).encode("utf-8")
        # saas-19.4: ir.attachment._check_contents() pops the removed 'datas'
        # key, so the content must be passed as raw bytes in 'raw' — with
        # 'datas' every emailed attachment was an empty 0-byte file.
        # sudo: attachment creation is plumbing; the content above is already
        # gated on the owner's read access.
        return (
            self.env["ir.attachment"]
            .sudo()
            .create(
                {
                    "name": f"{spreadsheet.sudo().name}.json",
                    "type": "binary",
                    "raw": content,
                    "res_model": self._name,
                    "res_id": self.id,
                    "mimetype": "application/json",
                }
            )
        )

    def _send_now_notification(self, title, message, notification_type):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": notification_type,
            },
        }

    def action_send_now(self):
        """Trigger an immediate send."""
        self.ensure_one()
        blocker = self._get_send_blocker()
        if blocker:
            return self._send_now_notification(
                self.env._("Report Not Sent"),
                blocker,
                "warning",
            )
        sent = self._send_report()
        if sent:
            return self._send_now_notification(
                self.env._("Report Sent"),
                self.env._(
                    "Report '%(report)s' has been sent to recipients.",
                    report=self.name,
                ),
                "success",
            )
        return self._send_now_notification(
            self.env._("Report Not Sent"),
            self.env._(
                "Report '%(report)s' was not sent: no recipient has a valid email "
                "address, or the mail template is missing. Add an email to a "
                "recipient partner or fill Extra Emails.",
                report=self.name,
            ),
            "warning",
        )
