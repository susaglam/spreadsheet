# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json
from urllib.parse import unquote

from odoo.tests.common import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools import osutil

from odoo.addons.spreadsheet_public_share_oca.controllers.main import (
    PasswordAttemptThrottle,
    password_throttle,
)

from .fixtures import export_data_workbook


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@tagged("post_install", "-at_install")
class TestPasswordAttemptThrottle(TransactionCase):
    def test_locks_after_max_failures_and_expires(self):
        clock = _FakeClock()
        throttle = PasswordAttemptThrottle(max_failures=3, window=60, clock=clock)
        key = throttle.make_key("db", "token", "10.0.0.1")
        self.assertFalse(throttle.register_failure(key))
        self.assertFalse(throttle.register_failure(key))
        self.assertFalse(throttle.is_locked(key))
        self.assertTrue(throttle.register_failure(key))
        self.assertTrue(throttle.is_locked(key))
        # Another client (or another link) is not affected.
        self.assertFalse(
            throttle.is_locked(throttle.make_key("db", "token", "10.0.0.2"))
        )
        clock.now += 61
        self.assertFalse(throttle.is_locked(key))
        self.assertEqual(len(throttle), 0, "expired entries are pruned")

    def test_reset_on_success(self):
        throttle = PasswordAttemptThrottle(max_failures=2, window=60)
        key = throttle.make_key("db", "token", "10.0.0.1")
        throttle.register_failure(key)
        throttle.reset(key)
        self.assertFalse(throttle.register_failure(key))

    def test_memory_is_bounded(self):
        clock = _FakeClock()
        throttle = PasswordAttemptThrottle(
            max_failures=5, window=600, max_keys=100, clock=clock
        )
        for index in range(1000):
            throttle.register_failure(throttle.make_key("db", f"t{index}", "ip"))
        self.assertLessEqual(len(throttle), 100)

    def test_flood_cannot_push_a_lock_out(self):
        # Filling the table from many addresses evicts unlocked entries first.
        clock = _FakeClock()
        throttle = PasswordAttemptThrottle(
            max_failures=3, window=600, max_keys=10, clock=clock
        )
        locked = throttle.make_key("db", "token", "attacker")
        for _attempt in range(3):
            throttle.register_failure(locked)
        for index in range(200):
            throttle.register_failure(throttle.make_key("db", "token", f"ip{index}"))
        self.assertLessEqual(len(throttle), 10)
        self.assertTrue(throttle.is_locked(locked))
        # When every slot is locked, the newest failure is still counted.
        full = PasswordAttemptThrottle(max_failures=1, window=600, max_keys=2)
        keys = [full.make_key("db", "token", f"ip{index}") for index in range(3)]
        for key in keys:
            full.register_failure(key)
        self.assertEqual(len(full), 2)
        self.assertTrue(full.is_locked(keys[-1]))

    def test_expired_entries_behind_live_ones_are_pruned(self):
        clock = _FakeClock()
        throttle = PasswordAttemptThrottle(max_failures=5, window=60, clock=clock)
        first = throttle.make_key("db", "token", "10.0.0.1")
        second = throttle.make_key("db", "token", "10.0.0.2")
        throttle.register_failure(first)
        clock.now += 30
        throttle.register_failure(second)
        clock.now += 20
        # A later failure must not move the entry: its window started earlier.
        throttle.register_failure(first)
        clock.now += 20  # first failure of "first" is now 70 s old
        throttle.is_locked(throttle.make_key("db", "token", "10.0.0.3"))
        self.assertEqual(len(throttle), 1)


@tagged("post_install", "-at_install")
class TestPublicShareController(HttpCase):
    def setUp(self):
        super().setUp()
        password_throttle.clear()
        self.addCleanup(password_throttle.clear)
        self.spreadsheet = self.env["spreadsheet.spreadsheet"].create(
            {
                "name": 'Çeyrek Özeti "Q3" – Ümit/Ağustos',
                "spreadsheet_raw": export_data_workbook(),
            }
        )
        self.share = self.env["spreadsheet.public.share"].create(
            {
                "name": "Board link",
                "spreadsheet_id": self.spreadsheet.id,
                "allow_download": True,
            }
        )

    def _url(self, suffix=""):
        return f"/spreadsheet/public/{self.share.token}{suffix}"

    def test_view_renders_export_data_format(self):
        response = self.url_open(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertIn("Quarter", response.text)
        self.assertIn("background-color:#875a7b;", response.text)
        # Hidden sheets, helper sheets and hidden rows never reach the preview.
        self.assertNotIn("internal only", response.text)
        self.assertNotIn("confidential row", response.text)
        self.share.invalidate_recordset(["view_count"])
        self.assertEqual(self.share.view_count, 1)

    def test_unicode_filename_download(self):
        response = self.url_open(self._url("/download"))
        self.assertEqual(response.status_code, 200)
        disposition = response.headers["Content-Disposition"]
        self.assertTrue(disposition.startswith("attachment; filename*=UTF-8''"))
        filename = unquote(disposition.split("''", 1)[1])
        self.assertEqual(
            filename, osutil.clean_filename(self.spreadsheet.name) + ".json"
        )
        self.assertIn("Çeyrek Özeti", filename)
        self.assertNotIn('"', filename)
        self.assertNotIn("/", filename)
        # The download is the complete workbook, hidden sheets included, so
        # formulas reading from them keep working after a re-import.
        data = json.loads(response.content)
        self.assertEqual(
            [sheet["name"] for sheet in data["sheets"]],
            ["Report", "Hidden notes", "Data"],
        )

    def test_download_disabled(self):
        self.share.allow_download = False
        self.assertEqual(self.url_open(self._url("/download")).status_code, 404)

    def test_password_prompt_grant_and_download(self):
        self.share.password = "s3cret"
        response = self.url_open(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="password"', response.text)
        self.assertNotIn("Quarter", response.text)
        # Without the password the data cannot be downloaded either.
        self.assertEqual(self.url_open(self._url("/download")).status_code, 404)

        response = self.url_open(self._url(), data={"password": "wrong"})
        self.assertIn("Incorrect password", response.text)

        response = self.url_open(self._url(), data={"password": "s3cret"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Quarter", response.text)
        # The session now remembers the password for the page and the download.
        self.assertIn("Quarter", self.url_open(self._url()).text)
        self.assertEqual(self.url_open(self._url("/download")).status_code, 200)

    def test_password_in_query_string_is_ignored(self):
        # A GET password would leak into proxy logs, history and Referer headers.
        self.share.password = "s3cret"
        response = self.url_open(self._url("?password=s3cret"))
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="password"', response.text)
        self.assertNotIn("Quarter", response.text)
        self.assertEqual(
            self.url_open(self._url("/download?password=s3cret")).status_code, 404
        )

    def test_link_of_creator_without_edit_access_is_refused(self):
        # The H2 exploit: a spreadsheet user published (and allowed the download
        # of) a spreadsheet they cannot edit. Such a link never serves data.
        intruder = new_test_user(
            self.env,
            login="share_intruder",
            groups="base.group_user,spreadsheet_oca.group_user",
        )
        self.share.created_by_id = intruder
        self.assertEqual(self.url_open(self._url("/download")).status_code, 404)
        self.assertIn("Invalid or Expired Link", self.url_open(self._url()).text)

    def test_undecodable_workbook_degrades(self):
        not_json = base64.b64encode(b"not json").decode()
        self.spreadsheet.spreadsheet_binary_data = not_json
        response = self.url_open(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertIn("There is nothing to preview", response.text)
        response = self.url_open(self._url("/download"))
        self.assertEqual(response.status_code, 500)
        self.assertIn("could not be read", response.text)

    def test_password_attempts_are_throttled(self):
        self.share.password = "s3cret"
        for _attempt in range(password_throttle.max_failures - 1):
            response = self.url_open(self._url(), data={"password": "wrong"})
            self.assertEqual(response.status_code, 200)
        response = self.url_open(self._url(), data={"password": "wrong"})
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many incorrect passwords", response.text)
        # Even the right password is refused while the prompt is locked.
        response = self.url_open(self._url(), data={"password": "s3cret"})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("Quarter", response.text)

    def test_invalid_token(self):
        response = self.url_open("/spreadsheet/public/not-a-real-token")
        self.assertIn("Invalid or Expired Link", response.text)
        self.assertEqual(
            self.url_open("/spreadsheet/public/not-a-real-token/download").status_code,
            404,
        )
