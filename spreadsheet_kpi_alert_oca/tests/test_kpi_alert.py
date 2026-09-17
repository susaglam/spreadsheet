# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged

USER_GROUPS = "base.group_user,spreadsheet_oca.group_user"


@tagged("post_install", "-at_install")
class TestKpiAlert(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Alert = cls.env["spreadsheet.kpi.alert"]
        cls.Spreadsheet = cls.env["spreadsheet.spreadsheet"]
        # Owner of the spreadsheet all default alerts hang off.
        cls.owner = new_test_user(
            cls.env,
            login="kpi_owner",
            groups=USER_GROUPS,
        )
        # Another plain user who is NOT owner/contributor/notified -> must not
        # be able to reach the owner's alert through access rules.
        cls.stranger = new_test_user(
            cls.env,
            login="kpi_stranger",
            groups=USER_GROUPS,
        )

    def _make_spreadsheet(self, cells, sheet_name="Sheet1"):
        return self.Spreadsheet.create(
            {
                "name": "KPI Test Sheet",
                "owner_id": self.owner.id,
                "spreadsheet_raw": {
                    "sheets": [{"name": sheet_name, "cells": cells}],
                },
            }
        )

    def _alert_vals(self, spreadsheet, **vals):
        base = {
            "name": "Alert",
            "spreadsheet_id": spreadsheet.id,
            "sheet_name": "Sheet1",
            "cell_ref": "B2",
            "operator": ">",
            "threshold_value": 100.0,
        }
        base.update(vals)
        return base

    def _make_alert(self, spreadsheet, **vals):
        return self.Alert.create(self._alert_vals(spreadsheet, **vals))

    def _reset_access_caches(self):
        self.env.flush_all()
        self.env.invalidate_all()
        self.env.transaction.invalidate_access_cache()

    def _sheet_messages(self, spreadsheet, message_type):
        return (
            self.env["mail.message"]
            .sudo()
            .search(
                [
                    ("model", "=", spreadsheet._name),
                    ("res_id", "=", spreadsheet.id),
                    ("message_type", "=", message_type),
                ]
            )
        )

    def _alert_mails(self, alert):
        return (
            self.env["mail.mail"]
            .sudo()
            .search([("model", "=", alert._name), ("res_id", "=", alert.id)])
        )

    # --- _resolve_current_value branches -------------------------------------

    def test_resolve_literal_number(self):
        sheet = self._make_spreadsheet({"B2": "1500"})
        alert = self._make_alert(sheet)
        self.assertEqual(alert._resolve_current_value(), 1500.0)

    def test_resolve_legacy_dict_cell(self):
        sheet = self._make_spreadsheet({"B2": {"content": "1500"}})
        alert = self._make_alert(sheet)
        self.assertEqual(alert._resolve_current_value(), 1500.0)

    def test_resolve_single_sheet_name_fallback(self):
        # Sheet stored under a translated name; single-sheet workbook -> still
        # resolves against the only sheet.
        sheet = self._make_spreadsheet({"B2": "42"}, sheet_name="Blad1")
        alert = self._make_alert(sheet)  # sheet_name defaults to "Sheet1"
        self.assertEqual(alert._resolve_current_value(), 42.0)

    def test_resolve_formula_cell_returns_none(self):
        sheet = self._make_spreadsheet({"B2": "=A1+A2"})
        alert = self._make_alert(sheet)
        self.assertIsNone(alert._resolve_current_value())

    def test_resolve_stale_sync_ignored(self):
        sheet = self._make_spreadsheet({"B2": "=A1+A2"})
        alert = self._make_alert(sheet)
        alert.last_value = 999.0
        alert.value_synced_at = fields.Datetime.now() - timedelta(hours=48)
        self.assertIsNone(alert._resolve_current_value())

    def test_resolve_fresh_sync_used(self):
        sheet = self._make_spreadsheet({"B2": "=A1+A2"})
        alert = self._make_alert(sheet)
        alert.last_value = 777.0
        alert.value_synced_at = fields.Datetime.now() - timedelta(hours=1)
        self.assertEqual(alert._resolve_current_value(), 777.0)

    # --- cron ----------------------------------------------------------------

    def test_cron_operator_triggers(self):
        # Cell 1500 > threshold 100 -> should trigger.
        sheet = self._make_spreadsheet({"B2": "1500"})
        alert = self._make_alert(sheet, operator=">", threshold_value=100.0)
        self.Alert._cron_check_kpi_thresholds()
        self.assertTrue(alert.last_triggered)
        self.assertTrue(alert.last_checked)
        # last_value persisted from the literal read (Tier 2 honesty fix).
        self.assertEqual(alert.last_value, 1500.0)

    def test_cron_operator_no_trigger(self):
        # Cell 50 is NOT > threshold 100 -> no trigger, but check timestamp set.
        sheet = self._make_spreadsheet({"B2": "50"})
        alert = self._make_alert(sheet, operator=">", threshold_value=100.0)
        self.Alert._cron_check_kpi_thresholds()
        self.assertFalse(alert.last_triggered)
        self.assertTrue(alert.last_checked)

    def test_cron_less_than_triggers(self):
        sheet = self._make_spreadsheet({"B2": "10"})
        alert = self._make_alert(sheet, operator="<", threshold_value=100.0)
        self.Alert._cron_check_kpi_thresholds()
        self.assertTrue(alert.last_triggered)

    def test_cron_cooldown_skip(self):
        sheet = self._make_spreadsheet({"B2": "1500"})
        recent = fields.Datetime.now() - timedelta(hours=1)
        alert = self._make_alert(
            sheet,
            operator=">",
            threshold_value=100.0,
            cooldown_hours=24,
            last_triggered=recent,
        )
        self.Alert._cron_check_kpi_thresholds()
        # Still within cooldown -> last_triggered unchanged.
        self.assertEqual(alert.last_triggered, recent)

    def test_cron_formula_cell_skipped(self):
        sheet = self._make_spreadsheet({"B2": "=A1"})
        alert = self._make_alert(sheet, operator=">", threshold_value=0.0)
        self.Alert._cron_check_kpi_thresholds()
        self.assertFalse(alert.last_triggered)

    def test_cron_chatter_body_is_html_not_escaped(self):
        # message_post escapes a plain str body; the notification must arrive
        # as real HTML with the user-provided name escaped inside it.
        sheet = self._make_spreadsheet({"B2": "1500"})
        self._make_alert(sheet, name="Revenue <b>alert</b>")
        self.Alert._cron_check_kpi_thresholds()
        message = self.env["mail.message"].search(
            [("model", "=", sheet._name), ("res_id", "=", sheet.id)],
            order="id desc",
            limit=1,
        )
        self.assertIn("<strong>", message.body)
        self.assertNotIn("&lt;strong&gt;", message.body)
        self.assertIn("Revenue &lt;b&gt;alert&lt;/b&gt;", message.body)

    # --- email template ------------------------------------------------------

    def test_send_email_renders_and_queues_mail(self):
        # The shipped template used Jinja-only `| join(',')` in email_to
        # (NameError at render, rolled back by the per-alert savepoint, so the
        # alert never fired) and {{ }} in the QWeb body (printed literally).
        notified = new_test_user(
            self.env,
            login="kpi_notified",
            groups=USER_GROUPS,
            email="kpi.notified@example.com",
        )
        sheet = self._make_spreadsheet({"B2": "1500"})
        alert = self._make_alert(
            sheet,
            name="Revenue Alert",
            send_email=True,
            notify_user_ids=[Command.set(notified.ids)],
        )
        template = self.env.ref("spreadsheet_kpi_alert_oca.kpi_alert_email_template")
        self.assertFalse(template.use_default_to)
        # Rendering the recipients must not raise (was NameError: join).
        email_to = template._render_field("email_to", alert.ids)[alert.id]
        self.assertIn("kpi.notified@example.com", email_to)

        Mail = self.env["mail.mail"].sudo()
        mail_domain = [("model", "=", alert._name), ("res_id", "=", alert.id)]
        self.assertFalse(Mail.search(mail_domain))
        self.Alert._cron_check_kpi_thresholds()
        self.assertTrue(
            alert.last_triggered, "the email step must not roll the trigger back"
        )
        mail = Mail.search(mail_domain)
        self.assertEqual(len(mail), 1)
        self.assertIn("kpi.notified@example.com", mail.email_to)
        self.assertTrue(mail.email_from)
        self.assertNotIn("{{", mail.body_html)
        self.assertIn("Revenue Alert", mail.body_html)
        self.assertIn("KPI Test Sheet", mail.body_html)
        self.assertIn("1500", mail.body_html)

    def test_send_email_without_recipient_email_does_not_fail(self):
        notified = new_test_user(
            self.env, login="kpi_no_email", groups=USER_GROUPS, email=False
        )
        sheet = self._make_spreadsheet({"B2": "1500"})
        alert = self._make_alert(
            sheet, send_email=True, notify_user_ids=[Command.set(notified.ids)]
        )
        self.Alert._cron_check_kpi_thresholds()
        self.assertTrue(alert.last_triggered)
        self.assertFalse(
            self.env["mail.mail"]
            .sudo()
            .search([("model", "=", alert._name), ("res_id", "=", alert.id)])
        )

    # --- update_cell_values --------------------------------------------------

    def test_update_cell_values_casts_string_keys(self):
        sheet = self._make_spreadsheet({"B2": "=A1"})
        alert = self._make_alert(sheet)
        # JS sends string keys.
        self.Alert.update_cell_values({str(alert.id): 321.0})
        self.assertEqual(alert.last_value, 321.0)
        self.assertTrue(alert.value_synced_at)

    def test_update_cell_values_acl_scoped(self):
        sheet = self._make_spreadsheet({"B2": "=A1"})
        alert = self._make_alert(sheet)
        # The stranger cannot reach the owner's alert -> search filters it out,
        # so the write is silently skipped (no last_value change, no crash).
        self.Alert.with_user(self.stranger).update_cell_values({str(alert.id): 555.0})
        self.assertEqual(alert.last_value, 0.0)

    def test_update_cell_values_spreadsheet_editor_allowed(self):
        # A contributor can edit the spreadsheet, so their browser may feed it.
        sheet = self._make_spreadsheet({"B2": "=A1"})
        sheet.contributor_ids = [Command.link(self.stranger.id)]
        alert = self._make_alert(sheet)
        self._reset_access_caches()
        self.Alert.with_user(self.stranger).update_cell_values({str(alert.id): 42.0})
        self.assertEqual(alert.last_value, 42.0)
        self.assertTrue(alert.value_synced_at)

    # --- access rules --------------------------------------------------------

    def test_owner_cannot_read_stranger_alert(self):
        # Sanity check the access rules really scope reads by ownership.
        sheet = self._make_spreadsheet({"B2": "=A1"})
        alert = self._make_alert(sheet)
        with self.assertRaises(AccessError):
            alert.with_user(self.stranger).read(["last_value"])

    def test_cannot_create_alert_on_unreadable_spreadsheet(self):
        # Exploit: watch someone else's cell, notify yourself, operator '!='
        # -> the value arrives by notification. Must be refused at create.
        sheet = self._make_spreadsheet({"B2": "1500"})
        vals = self._alert_vals(
            sheet,
            operator="!=",
            threshold_value=0.0,
            notify_user_ids=[Command.set(self.stranger.ids)],
        )
        # The explicit pre-check teaches (ValidationError) before the generic
        # post-insert ir.access create check would refuse it.
        with self.assertRaises(ValidationError):
            self.Alert.with_user(self.stranger).create(vals)

    def test_cannot_move_alert_to_unreadable_spreadsheet(self):
        # The ir.access write check runs before the write, and 19.4 runs
        # @api.constrains as sudo, so write() itself must catch a spreadsheet_id
        # changed to a spreadsheet the writer can't open.
        own_sheet = self.Spreadsheet.with_user(self.stranger).create(
            {"name": "Stranger Sheet"}
        )
        alert = self.Alert.with_user(self.stranger).create(self._alert_vals(own_sheet))
        foreign_sheet = self._make_spreadsheet({"B2": "1500"})
        with self.assertRaises(ValidationError):
            alert.write({"spreadsheet_id": foreign_sheet.id})

    def test_contributor_cannot_move_foreign_alert_to_unreadable_spreadsheet(self):
        # Exploit: an alert created by someone with wider access (here the
        # superuser, whose alerts the cron evaluates with sudo) on a spreadsheet
        # the attacker may edit, re-pointed at a spreadsheet the attacker cannot
        # open, with '!=' and themselves notified.
        editable = self._make_spreadsheet({"B2": "1"})
        editable.contributor_ids = [Command.link(self.stranger.id)]
        private = self._make_spreadsheet({"B2": "1500"})
        alert = self._make_alert(editable, threshold_value=1000.0)
        self._reset_access_caches()
        comments_before = len(self._sheet_messages(private, "comment"))
        with self.assertRaises(ValidationError):
            alert.with_user(self.stranger).write(
                {
                    "spreadsheet_id": private.id,
                    "operator": "!=",
                    "threshold_value": 0.0,
                    "notify_user_ids": [Command.link(self.stranger.id)],
                }
            )
        self._reset_access_caches()
        self.assertEqual(alert.spreadsheet_id, editable)
        self.assertFalse(alert.notify_user_ids)
        self.Alert._cron_check_kpi_thresholds()
        self.assertEqual(len(self._sheet_messages(private, "comment")), comments_before)
        self.assertFalse(self._sheet_messages(private, "user_notification"))
        self.assertEqual(alert.last_value, 0.0)

    def test_editor_cannot_move_foreign_alert_to_read_only_spreadsheet(self):
        # Readable is not enough: after the move the writer must still be
        # allowed to manage the alert on the NEW spreadsheet (creator, or
        # editor of that spreadsheet). The refused move must not persist.
        editable = self._make_spreadsheet({"B2": "1"})
        editable.contributor_ids = [Command.link(self.stranger.id)]
        read_only = self._make_spreadsheet({"B2": "1500"})
        read_only.reader_ids = [Command.link(self.stranger.id)]
        alert = self._make_alert(editable, threshold_value=1000.0)
        self._reset_access_caches()
        with self.assertRaises(AccessError):
            alert.with_user(self.stranger).write({"spreadsheet_id": read_only.id})
        self._reset_access_caches()
        self.assertEqual(alert.spreadsheet_id, editable)

    def test_creator_can_move_own_alert_to_readable_spreadsheet(self):
        first = self._make_spreadsheet({"B2": "1"})
        second = self._make_spreadsheet({"B2": "2"})
        first.reader_ids = [Command.link(self.stranger.id)]
        second.reader_ids = [Command.link(self.stranger.id)]
        self._reset_access_caches()
        alert = self.Alert.with_user(self.stranger).create(self._alert_vals(first))
        alert.write({"spreadsheet_id": second.id})
        self._reset_access_caches()
        self.assertEqual(alert.sudo().spreadsheet_id, second)

    def test_can_manage_hides_actions_from_notified_users(self):
        sheet = self._make_spreadsheet({"B2": "=A1"})
        alert = self._make_alert(
            sheet, notify_user_ids=[Command.set(self.stranger.ids)]
        )
        self._reset_access_caches()
        self.assertFalse(alert.with_user(self.stranger).can_manage)
        self.assertTrue(alert.with_user(self.owner).can_manage)

    def test_owner_lost_access_stops_value_sync_and_is_flagged(self):
        sheet = self._make_spreadsheet({"B2": "=A1"})
        sheet.reader_ids = [Command.link(self.stranger.id)]
        self._reset_access_caches()
        alert = self.Alert.with_user(self.stranger).create(self._alert_vals(sheet))
        self.assertFalse(alert.with_user(self.owner).owner_access_lost)
        # The spreadsheet owner's browser feeds the alert while its creator can
        # still open the spreadsheet ...
        self.Alert.with_user(self.owner).update_cell_values({str(alert.id): 10.0})
        self._reset_access_caches()
        self.assertEqual(alert.sudo().last_value, 10.0)
        # ... but not once the creator lost access: the cron skips the alert, so
        # its notified users must not keep reading live values through it.
        sheet.reader_ids = [Command.unlink(self.stranger.id)]
        self._reset_access_caches()
        self.Alert.with_user(self.owner).update_cell_values({str(alert.id): 20.0})
        self._reset_access_caches()
        self.assertEqual(alert.sudo().last_value, 10.0)
        self.assertTrue(alert.with_user(self.owner).owner_access_lost)

    def test_manual_test_by_spreadsheet_editor_notifies_everyone(self):
        # Also covers restricted template rendering: a plain user (no Mail
        # Template Editor group) must be able to test an alert that emails.
        notified = new_test_user(
            self.env,
            login="kpi_notified_editor",
            groups=USER_GROUPS,
            email="kpi.notified.editor@example.com",
        )
        sheet = self._make_spreadsheet({"B2": "=A1"})
        alert = self.Alert.with_user(self.owner).create(
            self._alert_vals(
                sheet, send_email=True, notify_user_ids=[Command.set(notified.ids)]
            )
        )
        comments_before = len(self._sheet_messages(sheet, "comment"))
        result = alert.action_test_alert()
        self.assertEqual(result["params"]["type"], "success")
        self._reset_access_caches()
        comments = self._sheet_messages(sheet, "comment")
        self.assertEqual(len(comments), comments_before + 1)
        self.assertIn(notified.partner_id, comments.partner_ids)
        self.assertTrue(alert.sudo().last_triggered)
        mail = self._alert_mails(alert)
        self.assertEqual(len(mail), 1)
        self.assertIn("kpi.notified.editor@example.com", mail.email_to)

    def test_manual_test_by_reader_is_private(self):
        # A creator who may only read the spreadsheet cannot use Test to post
        # in its discussion or ping the notified users over and over.
        sheet = self._make_spreadsheet({"B2": "=A1"})
        sheet.reader_ids = [Command.link(self.stranger.id)]
        self._reset_access_caches()
        alert = self.Alert.with_user(self.stranger).create(
            self._alert_vals(
                sheet, send_email=True, notify_user_ids=[Command.set(self.owner.ids)]
            )
        )
        comments_before = len(self._sheet_messages(sheet, "comment"))
        alert.action_test_alert()
        self._reset_access_caches()
        self.assertEqual(len(self._sheet_messages(sheet, "comment")), comments_before)
        private_notes = self._sheet_messages(sheet, "user_notification")
        self.assertEqual(len(private_notes), 1)
        self.assertEqual(private_notes.partner_ids, self.stranger.partner_id)
        # The real recipients were not notified, so the cooldown did not start.
        self.assertFalse(alert.sudo().last_triggered)
        mail = self._alert_mails(alert)
        self.assertEqual(len(mail), 1)
        self.assertIn("kpi_stranger", mail.email_to)
        self.assertNotIn("kpi_owner", mail.email_to)

    def test_notified_user_reads_but_cannot_write_or_forge(self):
        sheet = self._make_spreadsheet({"B2": "=A1"})
        alert = self._make_alert(
            sheet, notify_user_ids=[Command.set(self.stranger.ids)]
        )
        as_notified = alert.with_user(self.stranger)
        # READ is granted to notified users ...
        self.assertEqual(as_notified.read(["name"])[0]["name"], "Alert")
        # ... but nothing else.
        with self.assertRaises(AccessError):
            as_notified.write({"last_value": 999.0})
        with self.assertRaises(AccessError):
            as_notified.write({"notify_user_ids": [Command.clear()]})
        with self.assertRaises(AccessError):
            as_notified.action_test_alert()
        with self.assertRaises(AccessError):
            as_notified.unlink()
        # The RPC used by the browser must not let them forge the value either.
        self.Alert.with_user(self.stranger).update_cell_values({str(alert.id): 999.0})
        self._reset_access_caches()
        self.assertEqual(alert.last_value, 0.0)
        self.assertFalse(alert.value_synced_at)

    def test_cron_evaluates_with_owner_rights_and_skips_lost_access(self):
        sheet = self._make_spreadsheet({"B2": "1500"})
        sheet.reader_ids = [Command.link(self.stranger.id)]
        self._reset_access_caches()
        # A reader may create an alert on a spreadsheet they can open ...
        alert = self.Alert.with_user(self.stranger).create(
            self._alert_vals(
                sheet,
                operator="!=",
                threshold_value=0.0,
                notify_user_ids=[Command.set(self.stranger.ids)],
            )
        )
        alert = alert.sudo()
        self.assertEqual(alert.create_uid, self.stranger)
        # ... but once their access is revoked the cron must not read the cell
        # for them, notify anybody or post in the spreadsheet chatter.
        sheet.reader_ids = [Command.unlink(self.stranger.id)]
        self._reset_access_caches()
        messages_before = self.env["mail.message"].search_count(
            [("model", "=", sheet._name), ("res_id", "=", sheet.id)]
        )
        self.Alert._cron_check_kpi_thresholds()
        self._reset_access_caches()
        self.assertFalse(alert.last_triggered)
        self.assertFalse(alert.last_checked)
        self.assertEqual(alert.last_value, 0.0)
        self.assertEqual(
            self.env["mail.message"].search_count(
                [("model", "=", sheet._name), ("res_id", "=", sheet.id)]
            ),
            messages_before,
        )

    def test_cron_reader_owned_alert_fires_while_access_kept(self):
        # A reader cannot post on the spreadsheet chatter themselves; the cron
        # must still deliver their alert while they can open the spreadsheet.
        sheet = self._make_spreadsheet({"B2": "1500"})
        sheet.reader_ids = [Command.link(self.stranger.id)]
        self._reset_access_caches()
        alert = self.Alert.with_user(self.stranger).create(self._alert_vals(sheet))
        self.Alert._cron_check_kpi_thresholds()
        alert = alert.sudo()
        self.assertTrue(alert.last_triggered)
        self.assertEqual(alert.last_value, 1500.0)
