# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from lxml import etree

from odoo.tests.common import TransactionCase, tagged

SPREADSHEET_APP = "//app[@name='spreadsheet_oca']"


@tagged("post_install", "-at_install")
class TestSpreadsheetSettingsApp(TransactionCase):
    """The "Spreadsheet" settings app is declared once, by spreadsheet_oca.

    The saas-19.4 settings form compiler adds one navigation entry per
    ``<app>`` element and never merges apps that share a name. When both
    spreadsheet_kpi_alert_oca and spreadsheet_scheduled_refresh_oca declared
    ``<app name="spreadsheet_oca">``, Settings listed "Spreadsheet" twice.
    Runs post-install so the check covers every add-on installed alongside.
    """

    def _settings_arch(self):
        view = self.env.ref("base.res_config_settings_view_form")
        arch = self.env["res.config.settings"].get_view(view.id, "form")["arch"]
        return etree.fromstring(arch)

    def test_single_spreadsheet_app(self):
        apps = self._settings_arch().xpath(SPREADSHEET_APP)
        self.assertEqual(
            len(apps),
            1,
            "Exactly one <app name='spreadsheet_oca'> may exist in Settings; "
            "add-ons must xpath into spreadsheet_oca's app, not declare their own.",
        )

    def test_owner_view_inherits_base_settings(self):
        view = self.env.ref("spreadsheet_oca.res_config_settings_view_form")
        self.assertEqual(
            view.inherit_id, self.env.ref("base.res_config_settings_view_form")
        )
        self.assertEqual(view.mode, "extension")

    def test_app_visible_only_when_it_has_content(self):
        (app,) = self._settings_arch().xpath(SPREADSHEET_APP)
        if app.xpath("./block"):
            # An add-on contributed settings: the app must be rendered.
            self.assertEqual(app.get("notApp"), "0")
        else:
            # spreadsheet_oca alone has no settings: never show an empty app.
            self.assertEqual(app.get("notApp"), "1")
