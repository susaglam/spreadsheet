# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import no_retry, tagged

from odoo.addons.web.tests.test_js import HootCommon, unit_test_error_checker

MODULE = "spreadsheet_forecast_oca"
UNIT_TEST_BUNDLE = "web.assets_unit_tests"


@tagged("post_install", "-at_install")
class TestForecastFunctionsHoot(HootCommon):
    """Run this module's Hoot suite (static/tests/*.test.js) in Chrome.

    The suite evaluates ODOO.FORECAST / ODOO.TREND / ODOO.MOVING_AVG in a real
    o-spreadsheet model: results, error messages, error propagation and the
    locale-aware number parsing.
    """

    @no_retry
    def test_forecast_functions_hoot_suite(self):
        addons = self._get_addons_from_asset_bundle(UNIT_TEST_BUNDLE)
        # Guard against a false green: Hoot reports "Test suite succeeded"
        # for an empty selection, e.g. when the manifest stops shipping the
        # test files in the unit test bundle.
        self.assertIn(
            MODULE,
            addons,
            f"No {MODULE} *.test.js file in {UNIT_TEST_BUNDLE}: check the "
            "'web.assets_unit_tests' entry of the manifest.",
        )
        module_filter = self._get_hoot_module_filters(addons, [MODULE])
        self.browser_js(
            "/web/tests?headless&loglevel=2&preset=desktop&timeout=15000"
            f"{module_filter}",
            "",
            "",
            login="admin",
            timeout=900,
            success_signal="[HOOT] Test suite succeeded",
            error_checker=unit_test_error_checker,
        )
