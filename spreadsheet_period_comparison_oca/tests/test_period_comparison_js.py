# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import HttpCase, tagged

from odoo.addons.web.tests.test_js import unit_test_error_checker

MODULE = "spreadsheet_period_comparison_oca"
FUNCTIONS_JS = f"/{MODULE}/static/src/spreadsheet/bundle/period_comparison.esm.js"
TESTS_JS = f"/{MODULE}/static/tests/period_comparison.test.js"


def hoot_job_id(full_name):
    """Id of a Hoot suite or test, as computed by core Hoot (generateHash)
    and by ``HootCommon._generate_hash`` in web/tests/test_js.py."""
    value = 0
    for char in full_name:
        value = ((value << 5) - value + ord(char)) & 0xFFFFFFFF
    return f"{value:08x}"


@tagged("post_install", "-at_install")
class TestPeriodComparisonFunctions(HttpCase):
    """Run the Hoot unit tests of the ODOO.PERCENT_CHANGE / VARIANCE /
    GROWTH_ARROW / YOY spreadsheet functions in a real browser."""

    def test_hoot_job_id_matches_core(self):
        # Reference values from web/tests/test_js.py (test_generate_hoot_hash).
        self.assertEqual(hoot_job_id("@web/core"), "e39ce9ba")
        self.assertEqual(hoot_job_id("@web/core/autocomplete"), "69a6561d")

    def test_unit_test_bundle_contains_module_files(self):
        """Without these files the Hoot run below would select no test and
        report success anyway."""
        assets = self.env["ir.qweb"]._get_asset_content("web.assets_unit_tests")[0]
        urls = {asset["url"] for asset in assets}
        self.assertIn(TESTS_JS, urls)
        self.assertIn(FUNCTIONS_JS, urls)

    def test_period_comparison_hoot(self):
        suite_id = hoot_job_id(f"@{MODULE}")
        self.browser_js(
            "/web/tests?headless&loglevel=2&preset=desktop&timeout=15000"
            f"&id={suite_id}",
            "",
            "",
            login="admin",
            timeout=1800,
            success_signal="[HOOT] Test suite succeeded",
            error_checker=unit_test_error_checker,
        )
