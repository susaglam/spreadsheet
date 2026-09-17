# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from lxml import etree

from odoo.modules import get_manifest
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestContractSettingsView(TransactionCase):
    """Contract & SLA settings live in the app owned by spreadsheet_oca.

    The module used to depend on spreadsheet_kpi_alert_oca only to reach the
    settings app that module declared.
    """

    def test_no_kpi_alert_dependency(self):
        self.assertNotIn(
            "spreadsheet_kpi_alert_oca",
            get_manifest("spreadsheet_contract_sla_oca")["depends"],
        )

    def test_block_inside_single_spreadsheet_app(self):
        view = self.env.ref(
            "spreadsheet_contract_sla_oca.res_config_settings_view_form_spreadsheet_contract"
        )
        self.assertEqual(
            view.inherit_id,
            self.env.ref("spreadsheet_oca.res_config_settings_view_form"),
        )
        base = self.env.ref("base.res_config_settings_view_form")
        arch = etree.fromstring(
            self.env["res.config.settings"].get_view(base.id, "form")["arch"]
        )
        apps = arch.xpath("//app[@name='spreadsheet_oca']")
        self.assertEqual(len(apps), 1, "Settings must list 'Spreadsheet' once.")
        self.assertEqual(apps[0].get("notApp"), "0")
        block = apps[0].xpath("./block[@name='contract_settings_block']")
        self.assertEqual(len(block), 1)
        self.assertTrue(
            block[0].xpath(".//field[@name='contract_default_reminder_days']")
        )
