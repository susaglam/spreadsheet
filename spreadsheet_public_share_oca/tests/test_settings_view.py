# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from lxml import etree

from odoo.modules import get_manifest
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPublicShareSettingsView(TransactionCase):
    """Public Share settings live in the app owned by spreadsheet_oca.

    The module used to depend on spreadsheet_kpi_alert_oca only to reach the
    settings app that module declared.
    """

    def test_no_kpi_alert_dependency(self):
        self.assertNotIn(
            "spreadsheet_kpi_alert_oca",
            get_manifest("spreadsheet_public_share_oca")["depends"],
        )

    def test_block_inside_single_spreadsheet_app(self):
        view = self.env.ref(
            "spreadsheet_public_share_oca.res_config_settings_view_form_spreadsheet_share"
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
        block = apps[0].xpath("./block[@name='share_settings_block']")
        self.assertEqual(len(block), 1)
        for field_name in (
            "public_share_default_expiry_days",
            "public_share_allow_download_default",
        ):
            self.assertTrue(block[0].xpath(f".//field[@name='{field_name}']"))
