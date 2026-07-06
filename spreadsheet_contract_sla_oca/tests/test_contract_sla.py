# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestContractSla(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Contract = cls.env["spreadsheet.contract"]
        cls.Sla = cls.env["spreadsheet.contract.sla"]
        cls.partner = cls.env["res.partner"].create({"name": "Test Partner"})
        cls.today = fields.Date.context_today(cls.Contract)

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
        user = self.env["res.users"].create(
            {
                "name": "No Email User",
                "login": "no_email_user_sla",
            }
        )
        self._make_contract(
            renewal_reminder_days=30,
            date_end=self.today + timedelta(days=5),
            responsible_id=user.id,
        )
        # Must not raise even if mail delivery/responsible email is missing.
        self.Contract._cron_check_contract_expiry()

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
