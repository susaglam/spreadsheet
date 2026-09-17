# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKpiAlertSettingsView(TransactionCase):
    """KPI Alert settings live in the single app owned by spreadsheet_oca."""

    def test_block_inside_single_spreadsheet_app(self):
        view = self.env.ref(
            "spreadsheet_kpi_alert_oca.res_config_settings_view_form_spreadsheet_kpi"
        )
        self.assertEqual(
            view.inherit_id,
            self.env.ref("spreadsheet_oca.res_config_settings_view_form"),
            "Add-ons must extend spreadsheet_oca's settings app, not create one.",
        )
        base = self.env.ref("base.res_config_settings_view_form")
        arch = etree.fromstring(
            self.env["res.config.settings"].get_view(base.id, "form")["arch"]
        )
        apps = arch.xpath("//app[@name='spreadsheet_oca']")
        self.assertEqual(len(apps), 1, "Settings must list 'Spreadsheet' once.")
        self.assertEqual(apps[0].get("notApp"), "0")
        block = apps[0].xpath("./block[@name='kpi_alert_settings_block']")
        self.assertEqual(len(block), 1)
        for field_name in (
            "kpi_alert_default_cooldown_hours",
            "kpi_alert_default_send_email",
        ):
            self.assertTrue(block[0].xpath(f".//field[@name='{field_name}']"))
