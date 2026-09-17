# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import importlib.util
import re
from datetime import timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger
from odoo.tools.misc import file_path

MODEL_LOGGER = "odoo.addons.spreadsheet_contract_sla_oca.models.contract_sla"
MIGRATION_102 = (
    "spreadsheet_contract_sla_oca/migrations/saas~19.4.1.0.2/post-migrate.py"
)


def load_migration_102():
    """Import the 1.0.2 post-migration script (its folder name is not a valid
    Python package name, so it cannot be imported normally)."""
    spec = importlib.util.spec_from_file_location(
        "spreadsheet_contract_sla_oca_post_migrate_102", file_path(MIGRATION_102)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestContractSla(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Contract = cls.env["spreadsheet.contract"]
        cls.Sla = cls.env["spreadsheet.contract.sla"]
        cls.partner = cls.env["res.partner"].create(
            {"name": "Test Partner", "email": "customer@example.com"}
        )
        cls.owner = new_test_user(
            cls.env,
            login="contract_sla_owner",
            groups="base.group_user,spreadsheet_oca.group_user",
            email="owner@example.com",
        )
        cls.template = cls.env.ref(
            "spreadsheet_contract_sla_oca.contract_expiry_email_template"
        )
        cls.today = fields.Date.context_today(cls.Contract)

    def _reminder_mails(self, contract):
        """Expiry reminder emails queued for ``contract`` (not the activity
        assignment notifications, which share model/res_id)."""
        return self.env["mail.mail"].search(
            [
                ("model", "=", "spreadsheet.contract"),
                ("res_id", "=", contract.id),
                ("subject", "=", f"Contract Expiring: {contract.name}"),
            ]
        )

    def _make_contract(self, **vals):
        base = {
            "name": "Test Contract",
            "partner_id": self.partner.id,
            "date_start": self.today - timedelta(days=30),
            "date_end": self.today + timedelta(days=365),
        }
        base.update(vals)
        return self.Contract.create(base)

    # --- days_to_expiry / state --------------------------------------------

    def test_days_to_expiry(self):
        contract = self._make_contract(date_end=self.today + timedelta(days=10))
        self.assertEqual(contract.days_to_expiry, 10)

    def test_state_active(self):
        contract = self._make_contract(
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=200),
        )
        self.assertEqual(contract.state, "active")

    def test_state_expiring(self):
        contract = self._make_contract(
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=10),
        )
        self.assertEqual(contract.state, "expiring")

    def test_state_expired(self):
        contract = self._make_contract(
            date_start=self.today - timedelta(days=400),
            date_end=self.today - timedelta(days=1),
        )
        self.assertEqual(contract.state, "expired")

    def test_state_draft_future_start(self):
        contract = self._make_contract(
            date_start=self.today + timedelta(days=10),
            date_end=self.today + timedelta(days=400),
            renewal_reminder_days=30,
        )
        self.assertEqual(contract.state, "draft")

    def test_cron_recompute_refreshes_stored_fields(self):
        """The cron must recompute stored date fields so they do not freeze."""
        contract = self._make_contract(date_end=self.today + timedelta(days=10))
        # Simulate a stale stored value written on an earlier day.
        contract.days_to_expiry = 999
        self.Contract._cron_check_contract_expiry()
        self.assertEqual(contract.days_to_expiry, 10)

    # --- date validation ----------------------------------------------------

    def test_end_before_start_rejected_on_create(self):
        with self.assertRaises(ValidationError):
            self._make_contract(
                date_start=self.today,
                date_end=self.today - timedelta(days=1),
            )

    def test_end_before_start_rejected_on_write(self):
        contract = self._make_contract()
        with self.assertRaises(ValidationError):
            contract.write({"date_end": contract.date_start - timedelta(days=1)})

    def test_same_day_contract_allowed(self):
        contract = self._make_contract(date_start=self.today, date_end=self.today)
        self.assertEqual(contract.days_to_expiry, 0)

    # --- renewal ------------------------------------------------------------

    def test_action_renew_preserves_duration(self):
        start = self.today - timedelta(days=10)
        end = self.today + timedelta(days=20)
        contract = self._make_contract(date_start=start, date_end=end)
        contract.action_renew()
        expected_start = end + relativedelta(days=1)
        expected_end = expected_start + relativedelta(end, start)
        self.assertEqual(contract.date_start, expected_start)
        self.assertEqual(contract.date_end, expected_end)

    # --- cron reminder ------------------------------------------------------

    def test_cron_fires_once_no_duplicate(self):
        contract = self._make_contract(
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=10),
        )
        self.Contract._cron_check_contract_expiry()
        self.assertEqual(contract.last_reminder_date, self.today)
        activities_after_first = len(contract.activity_ids)
        self.assertEqual(activities_after_first, 1)
        # Second run on the same day must not re-send.
        self.Contract._cron_check_contract_expiry()
        self.assertEqual(len(contract.activity_ids), 1)

    def test_cron_survives_contract_without_email(self):
        """A responsible user without email still gets the activity, the email
        is skipped, and the other contracts of the batch are processed."""
        no_email_user = new_test_user(
            self.env,
            login="no_email_user_sla",
            groups="base.group_user,spreadsheet_oca.group_user",
            email=False,
        )
        no_email = self._make_contract(
            name="No Email Contract",
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=5),
            responsible_id=no_email_user.id,
        )
        normal = self._make_contract(
            name="Normal Contract",
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=8),
            responsible_id=self.owner.id,
        )
        # Simulate values stored on an earlier day: the cron must refresh them.
        (no_email | normal).flush_recordset()
        self.env.cr.execute(
            "UPDATE spreadsheet_contract SET state = 'active', days_to_expiry = 999 "
            "WHERE id IN %s",
            [(no_email | normal)._ids],
        )
        (no_email | normal).invalidate_recordset(["state", "days_to_expiry"])

        self.Contract._cron_check_contract_expiry()

        self.assertEqual(no_email.days_to_expiry, 5)
        self.assertEqual(normal.days_to_expiry, 8)
        for contract in no_email | normal:
            self.assertEqual(contract.state, "expiring")
            self.assertEqual(contract.last_reminder_date, self.today)
            self.assertEqual(len(contract.activity_ids), 1)
            self.assertEqual(contract.activity_ids.user_id, contract.responsible_id)
        self.assertFalse(self._reminder_mails(no_email))
        self.assertEqual(len(self._reminder_mails(normal)), 1)

    def test_cron_db_error_on_one_contract_does_not_abort_batch(self):
        """A database error on one contract is rolled back to its savepoint;
        the next contract is still reminded (no aborted transaction)."""
        broken = self._make_contract(
            name="Broken Contract",
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=3),
            responsible_id=self.owner.id,
        )
        healthy = self._make_contract(
            name="Healthy Contract",
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=9),
            responsible_id=self.owner.id,
        )
        contract_cls = self.env.registry["spreadsheet.contract"]
        original = contract_cls.activity_schedule

        def activity_schedule(records, *args, **kwargs):
            if records == broken:
                # Real SQL failure: aborts the transaction without a savepoint.
                records.env.cr.execute("SELECT 1/0")
            return original(records, *args, **kwargs)

        with (
            patch.object(contract_cls, "activity_schedule", activity_schedule),
            mute_logger("odoo.sql_db", MODEL_LOGGER),
        ):
            self.Contract._cron_check_contract_expiry()

        # Healthy contract fully processed after the failure.
        self.assertEqual(healthy.last_reminder_date, self.today)
        self.assertEqual(len(healthy.activity_ids), 1)
        self.assertEqual(len(self._reminder_mails(healthy)), 1)
        # Broken contract rolled back cleanly and is retried on the next run.
        self.assertFalse(broken.last_reminder_date)
        self.assertFalse(broken.activity_ids)
        # The transaction is still usable.
        self.assertTrue(self.Contract.search_count([("id", "=", broken.id)]))

    def test_cron_mail_failure_keeps_activity(self):
        """The email is secondary: a failure to queue it keeps the activity."""
        contract = self._make_contract(
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=4),
            responsible_id=self.owner.id,
        )
        template_cls = self.env.registry["mail.template"]

        def send_mail(*args, **kwargs):
            raise UserError("SMTP configuration broken")  # pylint: disable=translation-required

        with (
            patch.object(template_cls, "send_mail", send_mail),
            mute_logger(MODEL_LOGGER),
        ):
            self.Contract._cron_check_contract_expiry()

        self.assertEqual(contract.last_reminder_date, self.today)
        self.assertEqual(len(contract.activity_ids), 1)
        self.assertFalse(self._reminder_mails(contract))

    def test_cron_outside_window_no_reminder(self):
        contract = self._make_contract(
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=200),
        )
        self.Contract._cron_check_contract_expiry()
        self.assertFalse(contract.last_reminder_date)

    # --- compliance ---------------------------------------------------------

    def test_compliance_pending_when_unmeasured(self):
        contract = self._make_contract()
        sla = self.Sla.create(
            {"name": "Uptime", "contract_id": contract.id, "target_value": 99.0}
        )
        # target set but never actually measured -> pending stays until stamped
        sla.last_updated = False
        self.assertEqual(sla.compliance, "pending")

    def test_compliance_breached_with_real_zero(self):
        contract = self._make_contract()
        sla = self.Sla.create(
            {
                "name": "Uptime",
                "contract_id": contract.id,
                "target_value": 99.0,
                "actual_value": 0.0,
            }
        )
        self.assertTrue(sla.last_updated)
        self.assertEqual(sla.compliance, "breached")

    def test_compliance_met(self):
        contract = self._make_contract()
        sla = self.Sla.create(
            {
                "name": "Uptime",
                "contract_id": contract.id,
                "target_value": 99.0,
                "actual_value": 99.9,
            }
        )
        self.assertEqual(sla.compliance, "met")

    # --- config default -----------------------------------------------------

    def test_reminder_default_reads_config(self):
        self.env["ir.config_parameter"].sudo().set_int(
            "spreadsheet_contract.default_reminder_days", 45
        )
        contract = self.Contract.create(
            {
                "name": "Config Default Contract",
                "partner_id": self.partner.id,
                "date_start": self.today,
                "date_end": self.today + timedelta(days=365),
            }
        )
        self.assertEqual(contract.renewal_reminder_days, 45)

    # --- email template -----------------------------------------------------

    def test_template_body_renders_values(self):
        """body_html is QWeb: values must be rendered, no literal {{ }}."""
        contract = self._make_contract(
            name="Acme Hosting",
            amount=1250.0,
            date_end=self.today + timedelta(days=17),
            responsible_id=self.owner.id,
        )
        body = self.template._render_field("body_html", contract.ids)[contract.id]
        self.assertNotIn("{{", body)
        self.assertNotIn("}}", body)
        self.assertIn("Acme Hosting", body)
        self.assertIn(self.partner.name, body)
        self.assertIn(self.owner.name, body)
        self.assertTrue(re.search(r"\b17\s+days", body), body)
        subject = self.template._render_field("subject", contract.ids)[contract.id]
        self.assertEqual(subject, "Contract Expiring: Acme Hosting")

    def test_template_addresses_responsible_not_partner(self):
        """The internal reminder must reach the responsible user, never the
        contract partner (customer/vendor), and carry a sender."""
        contract = self._make_contract(
            name="Recipient Check",
            responsible_id=self.owner.id,
        )
        mail = self.env["mail.mail"].browse(self.template.send_mail(contract.id))
        self.assertEqual(mail.recipient_ids, self.owner.partner_id)
        self.assertNotIn(self.partner, mail.recipient_ids)
        self.assertNotIn(self.partner.email, mail.email_to or "")
        self.assertTrue(mail.email_from)
        self.assertNotIn("{{", mail.body_html)

    def test_migration_repairs_legacy_template(self):
        """The 1.0.2 post-migration fixes a template installed by 1.0.1
        (noupdate) and is idempotent."""
        migration = load_migration_102()

        self._make_contract(responsible_id=self.owner.id)
        legacy_body = (
            "<div><p>Hello {{ object.responsible_id.name }},</p>"
            "<p>{{ object.name }}</p></div>"
        )
        template = self.template.with_context(lang="en_US")
        template.write(
            {
                "body_html": legacy_body,
                "email_to": migration.LEGACY_EMAIL_TO,
                "email_from": False,
                "partner_to": False,
                "use_default_to": True,
            }
        )

        for _run in range(2):  # second run must be a no-op
            migration.migrate(self.env.cr, "saas~19.4.1.0.1")
            template.invalidate_recordset()
            self.assertFalse(migration.has_literal_placeholders(template.body_html))
            self.assertIn('t-out="object.name', template.body_html)
            self.assertFalse(template.use_default_to)
            self.assertFalse(template.email_to)
            self.assertIn("responsible_id.partner_id.id", template.partner_to)
            self.assertTrue(template.email_from)

    def test_migration_keeps_customised_template(self):
        """A template an administrator already fixed is left untouched."""
        migration = load_migration_102()

        custom_body = '<div><p>Custom <t t-out="object.name"/></p></div>'
        template = self.template.with_context(lang="en_US")
        template.write(
            {
                "body_html": custom_body,
                "email_from": "contracts@example.com",
                "partner_to": "{{ object.responsible_id.partner_id.id }}",
            }
        )
        migration.migrate(self.env.cr, "saas~19.4.1.0.1")
        template.invalidate_recordset()
        self.assertIn("Custom", template.body_html)
        self.assertEqual(template.email_from, "contracts@example.com")
        self.assertEqual(
            template.partner_to, "{{ object.responsible_id.partner_id.id }}"
        )
