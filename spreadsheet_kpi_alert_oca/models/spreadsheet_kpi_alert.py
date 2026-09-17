# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import operator as op

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)

# A JS-synced last_value older than this is treated as stale (the cron ignores
# it) so alerts never fire on data a browser last evaluated days ago.
KPI_VALUE_MAX_AGE_HOURS = 24

OPERATOR_MAP = {
    ">": op.gt,
    "<": op.lt,
    ">=": op.ge,
    "<=": op.le,
    "=": op.eq,
    "!=": op.ne,
}


class SpreadsheetKpiAlert(models.Model):
    _name = "spreadsheet.kpi.alert"
    _description = "Spreadsheet KPI Alert"
    _order = "name"

    name = fields.Char(
        required=True,
        help="Short label for this alert, used in the notification and the email "
        "subject. Example: 'Revenue below monthly target'.",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to pause this alert without deleting it: the scheduled "
        "check skips archived alerts.",
    )
    spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        required=True,
        ondelete="cascade",
        index=True,
        help="The spreadsheet holding the cell to watch. You can only pick a "
        "spreadsheet you are allowed to open. The scheduled check reads the cell "
        "with the access rights of the user who created the alert, and skips the "
        "alert if that user can no longer open the spreadsheet.",
    )
    sheet_name = fields.Char(
        required=True,
        default="Sheet1",
        help="Name of the sheet containing the cell to monitor.",
    )
    cell_ref = fields.Char(
        string="Cell Reference",
        required=True,
        help="Cell reference (e.g., B2, C10) to monitor.",
    )
    operator = fields.Selection(
        [
            (">", "Greater than (>)"),
            ("<", "Less than (<)"),
            (">=", "Greater or equal (>=)"),
            ("<=", "Less or equal (<=)"),
            ("=", "Equal (=)"),
            ("!=", "Not equal (!=)"),
        ],
        required=True,
        default=">",
        help="How the cell value is compared to the threshold. Example: "
        "'Less than (<)' fires when the value falls below the threshold.",
    )
    threshold_value = fields.Float(
        string="Threshold",
        required=True,
        help="The number the cell value is compared against. Example: with "
        "operator '<' and threshold 1000, the alert fires when the cell drops "
        "below 1000.",
    )
    last_value = fields.Float(
        string="Last Known Value",
        readonly=True,
        copy=False,
        help="Last evaluated cell value, pushed by the JS client while a "
        "browser has the spreadsheet open.",
    )
    value_synced_at = fields.Datetime(
        readonly=True,
        copy=False,
        help="When the JS client last pushed an evaluated value for this cell. "
        "Distinguishes a never-synced cell from a genuine 0, and lets the cron "
        "ignore values older than the staleness window so alerts don't fire on "
        "data a browser evaluated days ago. Not needed for cells holding a "
        "literal number — those the cron reads directly from the stored sheet.",
    )
    last_checked = fields.Datetime(
        readonly=True,
        copy=False,
        help="When the scheduled check last evaluated this alert, whether or not "
        "it fired. It stops moving when the alert is skipped, for example because "
        "the user who created it can no longer open the spreadsheet.",
    )
    last_triggered = fields.Datetime(
        readonly=True,
        copy=False,
        help="When this alert last sent a notification. The cooldown is counted "
        "from this moment; empty means the alert has never fired.",
    )
    cooldown_hours = fields.Integer(
        string="Cooldown (hours)",
        default=lambda self: (
            self.env["ir.config_parameter"]
            .sudo()
            .get_int("spreadsheet_kpi_alert_oca.default_cooldown_hours", 24)
        ),
        help="Minimum hours between repeated alert notifications.",
    )
    notify_user_ids = fields.Many2many(
        "res.users",
        string="Notify Users",
        help="Users to notify when the threshold is breached. They can see this "
        "alert (read-only) and receive the cell value in the notification even if "
        "they cannot open the spreadsheet, so only add people allowed to see it.",
    )
    send_email = fields.Boolean(
        default=lambda self: (
            self.env["ir.config_parameter"]
            .sudo()
            .get_bool("spreadsheet_kpi_alert_oca.default_send_email", False)
        ),
        help="Also email the notified users (those with an email address) when "
        "the alert fires, in addition to the Discuss notification.",
    )

    # Computed display fields
    alert_condition = fields.Char(
        compute="_compute_alert_condition",
        string="Condition",
        help="Summary of what is watched, for example 'Sheet1!B2 < 1000.0': the "
        "alert fires when that cell's value meets this condition.",
    )
    can_manage = fields.Boolean(
        compute="_compute_can_manage",
        help="Whether you may edit, test or delete this alert: its creator, the "
        "spreadsheet's owner and contributors, and spreadsheet managers can. A "
        "user who is only notified by the alert sees it read-only.",
    )
    owner_access_lost = fields.Boolean(
        compute="_compute_owner_access_lost",
        string="Owner Lost Access",
        help="Set when the user who created this alert is archived or can no "
        "longer open its spreadsheet. The scheduled check then skips the alert "
        "and nobody is notified, until that user's access is restored or someone "
        "who can open the spreadsheet duplicates the alert.",
    )

    @api.depends("sheet_name", "cell_ref", "operator", "threshold_value")
    def _compute_alert_condition(self):
        for rec in self:
            rec.alert_condition = (
                f"{rec.sheet_name}!{rec.cell_ref} {rec.operator} {rec.threshold_value}"
            )

    @api.depends_context("uid")
    def _compute_can_manage(self):
        manageable = self._filtered_access("write")
        for rec in self:
            rec.can_manage = rec in manageable

    @api.depends("create_uid", "spreadsheet_id")
    def _compute_owner_access_lost(self):
        for rec in self:
            origin = rec._origin
            rec.owner_access_lost = bool(
                origin and origin._kpi_owner_access_problem() is not None
            )

    # --- access guards -------------------------------------------------------
    #
    # An alert copies a cell value into notifications, so whoever sets or moves
    # it must be allowed to open the watched spreadsheet. This cannot be an
    # @api.constrains: 19.4 runs constraint methods on self.sudo()
    # (BaseModel._validate_fields), so the caller's rights are gone by then.
    # write() also checks ir.access only BEFORE writing, i.e. against the old
    # spreadsheet, hence the explicit checks below.

    def _check_kpi_spreadsheet_readable(self, spreadsheet_values):
        """Raise when the current user cannot open one of the spreadsheets
        (ids or records) an alert is about to be attached to."""
        if self.env.su:
            return
        ids = set()
        for value in spreadsheet_values:
            if isinstance(value, models.BaseModel):
                ids.update(value._origin.ids)
            elif isinstance(value, int) and not isinstance(value, bool) and value:
                ids.add(value)
        spreadsheets = self.env["spreadsheet.spreadsheet"].browse(sorted(ids)).exists()
        for spreadsheet in spreadsheets:
            if not spreadsheet.has_access("read"):
                raise ValidationError(
                    self.env._(
                        "You cannot set a KPI alert on spreadsheet #%(spreadsheet_id)s "
                        "because you are not allowed to open it. An alert sends the "
                        "watched cell's value to its notified users, so it may only "
                        "watch a spreadsheet you can read. Ask the spreadsheet owner "
                        "to add you as a reader or contributor, or choose another "
                        "spreadsheet.",
                        spreadsheet_id=spreadsheet.id,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        # The ir.access create check after insert refuses an unreadable
        # spreadsheet too, but with a generic message; this one teaches.
        if not self.env.su:
            default_spreadsheet = self.env.context.get("default_spreadsheet_id")
            self._check_kpi_spreadsheet_readable(
                [vals.get("spreadsheet_id", default_spreadsheet) for vals in vals_list]
            )
        return super().create(vals_list)

    def write(self, vals):
        if "spreadsheet_id" not in vals or self.env.su or not self:
            return super().write(vals)
        self._check_kpi_spreadsheet_readable([vals["spreadsheet_id"]])
        # Savepoint: the check below runs after the write, so a caller that
        # catches the error must not be left with the refused move in place.
        with self.env.cr.savepoint():
            result = super().write(vals)
            # Re-evaluate the manage permission against the NEW spreadsheet,
            # like create() does after insert: an editor of spreadsheet A must
            # not re-point someone else's alert at a spreadsheet B they may
            # only read.
            for alert in self:
                if not alert.has_access("write"):
                    raise AccessError(
                        self.env._(
                            "You cannot move the KPI alert %(alert)s to spreadsheet "
                            "%(spreadsheet)s. On that spreadsheet only the alert's "
                            "creator, the spreadsheet's owner and contributors, and "
                            "spreadsheet managers may manage alerts, because an "
                            "alert sends the spreadsheet's values on their behalf. "
                            "Ask the spreadsheet owner to add you as a contributor, "
                            "or create a new alert of your own on that spreadsheet.",
                            alert=alert.sudo().name,
                            spreadsheet=alert.sudo().spreadsheet_id.display_name,
                        )
                    )
        return result

    def _filter_kpi_value_writers(self):
        """Return the alerts whose last_value the current user may feed.

        A value pushed from the browser decides whether the cron fires, so only
        a user who could change the spreadsheet itself (owner, contributor,
        manager), or the alert's own creator while they can still open the
        spreadsheet, may push it. A notified user only reads the alert.
        """
        if self.env.su:
            return self
        uid = self.env.uid
        return self._filtered_access("write").filtered(
            lambda alert: (
                alert.spreadsheet_id.has_access("write")
                or (
                    alert.create_uid.id == uid
                    and alert.spreadsheet_id.has_access("read")
                )
            )
        )

    def update_cell_values(self, values):
        """Update last_value for multiple alerts at once.

        Called by the JS client via RPC. `values` is a dict mapping
        alert IDs to their evaluated cell values.

        Args:
            values: dict of {alert_id: float_value}
        """
        # JS sends dict keys as strings; cast to int so Odoo's bulk-update
        # SQL generator doesn't emit text='integer comparisons (Postgres
        # rejects them with "operator does not exist: integer = text").
        try:
            id_value_map = {int(k): v for k, v in values.items()}
        except (AttributeError, TypeError, ValueError) as exc:
            _logger.debug("Invalid alert id in update_cell_values payload: %s", exc)
            return
        # search() applies the ir.access domains, so a user only reaches alerts
        # they may read — no sudo. Reading is not enough to feed a value though.
        alerts = self.search([("id", "in", list(id_value_map))])
        writable = alerts._filter_kpi_value_writers()
        if alerts - writable:
            _logger.debug(
                "User %s may not sync KPI values for alerts %s (needs edit access "
                "to the spreadsheet, or to be the alert's creator); skipped",
                self.env.uid,
                (alerts - writable).ids,
            )
        # An alert whose owner lost access is skipped by the cron; stop feeding
        # it too, or its notified users would keep reading live values through
        # last_value while the alert itself is dead.
        orphaned = writable.filtered(
            lambda alert: alert._kpi_owner_access_problem() is not None
        )
        if orphaned:
            _logger.debug(
                "KPI alerts %s: owner lost access to the spreadsheet; value sync "
                "skipped",
                orphaned.ids,
            )
            writable -= orphaned
        now = fields.Datetime.now()
        for alert in writable:
            val = id_value_map.get(alert.id)
            if val is None:
                continue
            try:
                number = float(val)
            except (ValueError, TypeError) as exc:
                _logger.debug(
                    "Skipping non-numeric KPI value for alert %s: %s",
                    alert.id,
                    exc,
                )
                continue
            alert.write({"last_value": number, "value_synced_at": now})

    def _kpi_owner_access_problem(self):
        """Return None when the alert's owner may still read it and its
        spreadsheet, else a short (log-only, untranslated) reason.

        The owner is the user who created the alert; the superuser (OdooBot,
        e.g. for alerts created by data files) always qualifies.
        """
        self.ensure_one()
        alert_sudo = self.sudo()
        owner = alert_sudo.create_uid
        if owner and owner._is_superuser():
            return None
        if not owner or not owner.active:
            return "its creator is archived or unknown"
        alert_as_owner = alert_sudo.with_user(owner)
        spreadsheet_as_owner = alert_sudo.spreadsheet_id.with_user(owner)
        if alert_as_owner.has_access("read") and spreadsheet_as_owner.has_access(
            "read"
        ):
            return None
        return f"its creator ({owner.login}) can no longer open the spreadsheet"

    def _kpi_as_owner(self):
        """Return this alert bound to its owner's access rights, or an empty
        recordset when the alert must be skipped.

        The cron runs as the superuser so it sees every alert, but the watched
        cell is read with the owner's rights: an alert must never become a way
        to read a spreadsheet its owner cannot open. An archived owner, or one
        who lost read access to the spreadsheet, makes the alert skip (with a
        logged reason) instead of leaking the value.
        """
        self.ensure_one()
        alert_sudo = self.sudo()
        reason = self._kpi_owner_access_problem()
        if reason is None:
            owner = alert_sudo.create_uid
            return alert_sudo if owner._is_superuser() else alert_sudo.with_user(owner)
        _logger.warning(
            "KPI alert %s (%r) skipped: %s. Alerts are evaluated with the access "
            "rights of the user who created them, so the cell was not read and "
            "nobody was notified. Fix: restore that user's access, or let a user "
            "who can open spreadsheet %s duplicate the alert (becoming its owner) "
            "and archive this one.",
            alert_sudo.id,
            alert_sudo.name,
            reason,
            alert_sudo.spreadsheet_id.id,
        )
        return self.browse()

    def _resolve_current_value(self):
        """Return a trustworthy current value for the watched cell, or None.

        Runs with the access rights of the environment user — the cron calls it
        on the alert bound to its owner (see ``_kpi_as_owner``).

        The server has no o-spreadsheet JS engine, so it cannot evaluate
        formulas. Strategy:
          (a) LITERAL read — if the watched cell holds a plain number in the
              stored spreadsheet_raw, read it directly (works fully unattended,
              the common KPI case).
          (b) FRESH SYNC — else, if the JS client pushed a value recently
              (value_synced_at within the staleness window), trust last_value.
          (c) None — otherwise (formula cell never synced, or a stale sync):
              the caller skips, so the cron never fires on 0.0-default or old
              data.
        Any parse failure degrades gracefully to (b)/(c) — never crashes the
        cron batch. An access error returns None outright: a user who may not
        read the spreadsheet gets no value at all, not even a synced one.
        """
        self.ensure_one()
        # (a) server-side literal read
        try:
            raw = self.spreadsheet_id.spreadsheet_raw or {}
            sheets = raw.get("sheets") or []
            sheet = next((s for s in sheets if s.get("name") == self.sheet_name), None)
            # The empty-sheet default name _('Sheet1') is translated on write
            # (Blad1 / Sayfa1), so a name mismatch with a single-sheet workbook
            # still points at the only sheet.
            if sheet is None and len(sheets) == 1:
                sheet = sheets[0]
            if sheet is not None:
                cell = (sheet.get("cells") or {}).get(self.cell_ref)
                # Cells are bare strings in the current native format and
                # {"content": ...} objects in the legacy format — handle both.
                content = cell.get("content") if isinstance(cell, dict) else cell
                if content is not None:
                    content = str(content).strip()
                    if content and not content.startswith("="):
                        return float(content)
        except AccessError as exc:
            _logger.info(
                "Alert %s: user %s may not read the spreadsheet (%s); no value",
                self.id,
                self.env.uid,
                exc,
            )
            return None
        except Exception as exc:  # noqa: BLE001 - never let the cron crash
            _logger.debug(
                "Alert %s: literal cell read failed (%s); falling back to sync",
                self.id,
                exc,
            )
        # (b) fresh JS-synced value
        if self.value_synced_at:
            age_hours = (
                fields.Datetime.now() - self.value_synced_at
            ).total_seconds() / 3600
            if age_hours <= KPI_VALUE_MAX_AGE_HOURS:
                return self.last_value
        # (c) nothing trustworthy
        return None

    @api.model
    def _cron_check_kpi_thresholds(self):
        """Cron job: check all active alerts and trigger notifications."""
        # sudo: a system pass over every alert. The ir.access permissions would
        # otherwise hide other users' alerts from a non-root scheduler user.
        # Each cell is still read with its alert owner's rights (_kpi_as_owner).
        alerts = self.sudo().search([("active", "=", True)])
        now = fields.Datetime.now()

        for alert in alerts:
            # Resolve who the alert is evaluated for FIRST: an alert whose owner
            # lost access to the spreadsheet is skipped (and its last_checked
            # stops moving, which makes the stall visible in the list).
            try:
                alert_as_owner = alert._kpi_as_owner()
            except Exception as exc:  # noqa: BLE001 - never cascade a batch fail
                _logger.warning("KPI alert %s: owner check failed: %s", alert.id, exc)
                continue
            if not alert_as_owner:
                continue

            # Keep the check timestamp outside the savepoint so it records even
            # if the compare/trigger below fails for this one alert.
            alert.last_checked = now

            # Check cooldown
            if alert.last_triggered and alert.cooldown_hours:
                hours_since = (now - alert.last_triggered).total_seconds() / 3600
                if hours_since < alert.cooldown_hours:
                    continue

            # Compare threshold
            compare_fn = OPERATOR_MAP.get(alert.operator)
            if not compare_fn:
                continue

            # Per-alert savepoint: one bad alert (e.g. a template rendering
            # error) must not roll back the whole batch or block the remaining
            # alerts — graceful degradation.
            try:
                with self.env.cr.savepoint():
                    # Resolve a TRUSTWORTHY current value with the OWNER's
                    # rights: prefer a server-side literal read from the stored
                    # sheet (works fully unattended), else a fresh JS-synced
                    # value; skip when neither exists. This removes both the
                    # 0.0-default false positive AND the stale-synced false
                    # trigger.
                    current_value = alert_as_owner._resolve_current_value()
                    if current_value is None:
                        _logger.debug(
                            "Alert %s: no fresh KPI value (cell is a formula and "
                            "no recent client sync); skipping",
                            alert.id,
                        )
                        continue

                    if compare_fn(current_value, alert.threshold_value):
                        # Notify as the system (OdooBot), the owner check above
                        # already authorised reading the value.
                        alert._trigger_alert(now, current_value)
            except Exception as exc:  # noqa: BLE001 - never cascade a batch fail
                _logger.warning("KPI alert %s failed: %s", alert.id, exc)

    def _trigger_alert(self, now, value=None, test_recipient=None):
        """Send notifications for a breached threshold.

        `value` is the value the cron actually compared (a server-side literal
        read or a fresh sync); it falls back to last_value for manual test
        triggers so the message never shows a misleading stale number.

        `test_recipient` (a res.users record) turns this into a private test:
        only that user is notified (Discuss inbox, plus email when the alert
        sends emails), nothing is posted in the spreadsheet discussion, and the
        cooldown does not start, because the real recipients were not notified.
        """
        self.ensure_one()
        # Only a user allowed to manage this alert may fire it (no-op for the
        # cron's superuser): a notified user has read-only access and is
        # refused here, before anything is posted or sent.
        self.check_access("write")
        self.spreadsheet_id.check_access("read")
        current = value if value is not None else self.last_value
        if not test_recipient:
            vals = {"last_triggered": now}
            # Persist the compared value so an unattended (literal-read) trigger
            # emails/renders the real triggering number instead of a stale 0.0.
            # Deliberately NOT touching value_synced_at: that timestamp governs
            # the formula-cell staleness window and must not be advanced by a
            # literal read.
            if value is not None:
                vals["last_value"] = value
            self.write(vals)

        # Build notification message. message_post escapes a plain str body, so
        # the HTML wrapper is Markup and every user value is escaped into it.
        subject = self.env._("KPI Alert: %(name)s", name=self.name)
        body = Markup("<p><strong>%s</strong></p><p>%s</p>") % (
            subject,
            self.env._(
                "Cell %(cell)s = %(value)s (threshold: %(operator)s %(threshold)s)",
                cell=Markup("<code>%s</code>") % f"{self.sheet_name}!{self.cell_ref}",
                value=Markup("<strong>%s</strong>") % current,
                operator=self.operator,
                threshold=self.threshold_value,
            ),
        )

        if test_recipient:
            # message_notify creates a user_notification: it is linked to the
            # spreadsheet but not shown in its discussion. sudo: same reason as
            # below, authorised by the checks above.
            self.spreadsheet_id.sudo().message_notify(
                body=body,
                subject=subject,
                partner_ids=test_recipient.partner_id.ids,
            )
        else:
            # Post to spreadsheet chatter (visible to followers + specified
            # users). sudo: posting requires WRITE access to the spreadsheet,
            # but an alert owner may only be a reader. The checks above (write
            # on this alert, read on its spreadsheet) authorise this post.
            partner_ids = self.sudo().notify_user_ids.partner_id.ids
            self.spreadsheet_id.sudo().message_post(
                body=body,
                subtype_xmlid="mail.mt_comment",
                partner_ids=partner_ids,
                message_type="comment",
            )

        # Optionally send email
        if self.send_email:
            self._send_alert_email(test_recipient=test_recipient)

        _logger.info(
            "KPI Alert %s: %s (cell %s!%s = %s, threshold %s %s)",
            "tested privately" if test_recipient else "triggered",
            self.name,
            self.sheet_name,
            self.cell_ref,
            current,
            self.operator,
            self.threshold_value,
        )

    def _send_alert_email(self, test_recipient=None):
        """Queue the alert email for the notified users (or only for
        `test_recipient`); return the mail id or False when nothing could be
        queued (logged, never raised)."""
        self.ensure_one()
        template = self.env.ref(
            "spreadsheet_kpi_alert_oca.kpi_alert_email_template",
            raise_if_not_found=False,
        )
        if not template:
            _logger.warning(
                "KPI alert %s: 'Send Email' is enabled but the email template "
                "spreadsheet_kpi_alert_oca.kpi_alert_email_template is missing, so "
                "only the Discuss notification was sent. Fix: upgrade the module "
                "to restore the template.",
                self.id,
            )
            return False
        email_values = None
        if test_recipient:
            if not test_recipient.email:
                _logger.info(
                    "KPI alert %s: private test by user %s, who has no email "
                    "address; only the Discuss notification was sent.",
                    self.id,
                    test_recipient.id,
                )
                return False
            email_values = {"email_to": test_recipient.email_formatted}
        elif not self.sudo().notify_user_ids.filtered("email"):
            _logger.info(
                "KPI alert %s: 'Send Email' is enabled but no notified user has an "
                "email address; only the Discuss notification was sent.",
                self.id,
            )
            return False
        # sudo: outside superuser mode, rendering template expressions such as
        # the email_to join is reserved to Mail Template Editors, so a manual
        # test by a plain spreadsheet user raised AccessError. This is the
        # module's own template and _trigger_alert authorised the caller.
        # Queue instead of force_send: an SMTP hiccup must not slow down or
        # break the per-alert loop, and a rolled-back savepoint then also drops
        # the unsent mail.
        mail_id = template.sudo().send_mail(
            self.id, force_send=False, email_values=email_values
        )
        # The email queue cron runs hourly by default; wake it so the alert
        # leaves within a minute instead of up to an hour later.
        queue_cron = self.env.ref(
            "mail.ir_cron_mail_scheduler_action", raise_if_not_found=False
        )
        if queue_cron:
            queue_cron.sudo()._trigger()
        return mail_id

    def action_test_alert(self):
        """Manual test: trigger the alert regardless of threshold.

        Someone who may edit the spreadsheet (and could post in its discussion
        anyway) runs the full notification. Anyone else, e.g. the creator who
        can only read the spreadsheet, gets a private test: otherwise every
        click would post in a discussion they cannot post in and ping all the
        notified users.
        """
        self.ensure_one()
        if not self.has_access("write"):
            raise AccessError(
                self.env._(
                    "You cannot test the KPI alert %(name)s because you are only "
                    "notified by it. A test sends notifications on the alert's "
                    "behalf, so only its creator, the spreadsheet's owner and "
                    "contributors, and spreadsheet managers may run it. Ask one of "
                    "them to test the alert.",
                    name=self.name,
                )
            )
        private = not self.env.su and not self.spreadsheet_id.has_access("write")
        self._trigger_alert(
            fields.Datetime.now(), test_recipient=self.env.user if private else None
        )
        if private:
            message = self.env._(
                "Test notification for %(name)s sent to you only. You cannot edit "
                "this spreadsheet, so a test does not post in its discussion or "
                "notify the other users; the alert itself still does when its "
                "condition is met.",
                name=self.name,
            )
        else:
            message = self.env._("Notification sent for %(name)s.", name=self.name)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Test Alert Sent"),
                "message": message,
                "type": "success",
            },
        }
