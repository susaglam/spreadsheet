# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged


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
            groups="spreadsheet_oca.group_user",
        )
        # Another plain user who is NOT owner/contributor/notified -> must not
        # be able to reach the owner's alert through record rules.
        cls.stranger = new_test_user(
            cls.env,
            login="kpi_stranger",
            groups="spreadsheet_oca.group_user",
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

    def _make_alert(self, spreadsheet, **vals):
        base = {
            "name": "Alert",
            "spreadsheet_id": spreadsheet.id,
            "sheet_name": "Sheet1",
            "cell_ref": "B2",
            "operator": ">",
            "threshold_value": 100.0,
        }
        base.update(vals)
        return self.Alert.create(base)

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

    def test_owner_cannot_read_stranger_alert(self):
        # Sanity check the record rule really scopes reads by ownership.
        sheet = self._make_spreadsheet({"B2": "=A1"})
        alert = self._make_alert(sheet)
        with self.assertRaises(AccessError):
            alert.with_user(self.stranger).read(["last_value"])
