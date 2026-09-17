# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.api import SUPERUSER_ID
from odoo.tests.common import HttpCase, tagged
from odoo.tools import mute_logger

from .common import SpreadsheetApiCommonMixin

LIST_URL = "/api/spreadsheet/list"
CONTROLLER_LOGGER = "odoo.addons.spreadsheet_api_oca.controllers.api"


@tagged("post_install", "-at_install")
class TestSpreadsheetApiController(SpreadsheetApiCommonMixin, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_api_data()
        cls.readable = cls.Spreadsheet.create(
            {"name": "API readable", "reader_ids": [(4, cls.sheet_user.id)]}
        )
        cls.hidden = cls.Spreadsheet.create({"name": "API hidden"})
        cls.token = cls.Token.create(
            {"name": "HTTP token", "user_id": cls.sheet_user.id}
        )
        cls.secret = cls.token._generate_token()

    def _get(self, url, token=None, params=None):
        headers = {"Authorization": f"Bearer {token}"} if token else None
        return self.url_open(url, headers=headers, params=params)

    def _assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        body = response.json()
        self.assertEqual(body["code"], code)
        self.assertTrue(body["error"])
        self.assertTrue(body["message"])
        return body

    def test_header_token_lists_only_readable_spreadsheets(self):
        response = self._get(LIST_URL, token=self.secret)
        self.assertEqual(response.status_code, 200)
        ids = [s["id"] for s in response.json()["spreadsheets"]]
        self.assertIn(self.readable.id, ids)
        self.assertNotIn(self.hidden.id, ids)

    def test_unreadable_spreadsheet_is_json_404(self):
        response = self._get(f"/api/spreadsheet/{self.hidden.id}", token=self.secret)
        body = self._assert_error(response, 404, "not_found")
        self.assertEqual(body["error"], "Not found")
        self.assertIn("/api/spreadsheet/list", body["message"])
        self.assertNotIn("API hidden", response.text)

    def test_spreadsheet_outside_allowed_list_is_403_with_explanation(self):
        self.token.spreadsheet_ids = [(6, 0, self.readable.ids)]
        other = self.Spreadsheet.create(
            {"name": "Not allowed", "reader_ids": [(4, self.sheet_user.id)]}
        )
        response = self._get(f"/api/spreadsheet/{other.id}/cells", token=self.secret)
        body = self._assert_error(response, 403, "forbidden_scope")
        self.assertIn("Allowed Spreadsheets", body["message"])

    @mute_logger(CONTROLLER_LOGGER)
    def test_query_string_token_refused_by_default(self):
        response = self._get(LIST_URL, params={"token": self.secret})
        body = self._assert_error(response, 401, "query_token_disabled")
        self.assertIn("Authorization: Bearer", body["message"])
        self.assertIn("spreadsheet_api_oca.allow_query_token", body["message"])
        self.token.invalidate_recordset(["usage_count"])
        self.assertEqual(self.token.usage_count, 0)

    def test_query_string_token_allowed_when_enabled(self):
        self.env["ir.config_parameter"].sudo().set_bool(
            "spreadsheet_api_oca.allow_query_token", True
        )
        response = self._get(LIST_URL, params={"token": self.secret})
        self.assertEqual(response.status_code, 200)

    def test_missing_and_invalid_token_are_401(self):
        self._assert_error(self._get(LIST_URL), 401, "missing_token")
        response = self._get(LIST_URL, token="not-a-real-token")
        self._assert_error(response, 401, "invalid_token")
        self.assertIn("Bearer", response.headers.get("WWW-Authenticate", ""))

    @mute_logger("odoo.addons.spreadsheet_api_oca.models.api_token")
    def test_superuser_bound_token_rejected(self):
        # A legacy/tampered row must never yield a sudo environment.
        self.env.cr.execute(
            "UPDATE spreadsheet_api_token SET user_id = %s WHERE id = %s",
            (SUPERUSER_ID, self.token.id),
        )
        self.env.invalidate_all()
        response = self._get(LIST_URL, token=self.secret)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("API hidden", response.text)

    def test_failed_attempts_throttled_but_valid_token_passes(self):
        self.env["ir.config_parameter"].sudo().set_int(
            "spreadsheet_api_oca.failed_auth_per_minute", 2
        )
        for _i in range(2):
            self.assertEqual(self._get(LIST_URL, token="guess").status_code, 401)
        response = self._get(LIST_URL, token="guess")
        self._assert_error(response, 429, "rate_limited")
        self.assertEqual(response.headers.get("Retry-After"), "60")
        # Same client address, valid token: not locked out.
        self.assertEqual(self._get(LIST_URL, token=self.secret).status_code, 200)
