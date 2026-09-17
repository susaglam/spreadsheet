# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import contextlib
import hashlib
import hmac
import ipaddress
import json
import socket
import threading
import time
from unittest.mock import patch

import requests

from odoo.exceptions import AccessError
from odoo.tests import common as test_common
from odoo.tests.common import MockHTTPClient, TransactionCase, tagged
from odoo.tools import mute_logger

from ..models import spreadsheet_spreadsheet as sheet_module
from ..tools import webhook as webhook_tools
from .common import SpreadsheetApiCommonMixin

PUBLIC_IP = "93.184.215.14"
GETADDRINFO = "odoo.addons.spreadsheet_api_oca.tools.webhook._getaddrinfo"
DELIVERY_LOGGER = "odoo.addons.spreadsheet_api_oca.models.spreadsheet_spreadsheet"


def fake_dns(answers):
    """Return a _getaddrinfo replacement answering ``answers[host]``."""

    def _getaddrinfo(host, port):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
            for ip in answers[host]
        ]

    return _getaddrinfo


@tagged("post_install", "-at_install")
class TestSpreadsheetApiWebhook(SpreadsheetApiCommonMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_api_data()
        cls.token = cls.Token.create(
            {
                "name": "Webhook token",
                "user_id": cls.sheet_user.id,
                "webhook_url": f"https://{PUBLIC_IP}/hook",
            }
        )
        cls.secret = cls.token._generate_token()

    def _readable_sheet(self, name):
        return self.Spreadsheet.create(
            {"name": name, "reader_ids": [(4, self.sheet_user.id)]}
        )

    def _events(self, sheet=None, event_type=None):
        domain = [("token_id", "=", self.token.id)]
        if sheet is not None:
            domain.append(("spreadsheet_id", "=", sheet.id))
        if event_type:
            domain.append(("event_type", "=", event_type))
        return self.Event.search(domain)

    # ------------------------------------------------------------------
    # Event triggering / scoping
    # ------------------------------------------------------------------
    def test_create_spreadsheet_enqueues_create_event(self):
        sheet = self._readable_sheet("WH sheet")
        events = self._events(sheet, "create")
        self.assertEqual(len(events), 1)
        payload = json.loads(events.payload)
        self.assertEqual(payload["spreadsheet_name"], "WH sheet")

    def test_payload_excludes_unreadable_spreadsheets(self):
        # Created by the superuser, no reader/contributor entry: the token's
        # user cannot read it, so its name must not be pushed to the webhook.
        secret_sheet = self.Spreadsheet.create({"name": "Board salaries"})
        self.assertFalse(self._events(secret_sheet))
        secret_sheet.write({"spreadsheet_raw": {"sheets": []}})
        self.assertFalse(self._events(secret_sheet))
        payloads = self._events().mapped("payload")
        self.assertFalse(any("Board salaries" in p for p in payloads))

    def test_update_events_are_coalesced(self):
        sheet = self._readable_sheet("Coalesce sheet")
        sheet._trigger_webhooks("update")
        sheet._trigger_webhooks("update")
        pending = self._events(sheet, "update").filtered(lambda e: not e.delivered)
        self.assertEqual(len(pending), 1)

    def test_delete_event_emitted_on_unlink(self):
        sheet = self._readable_sheet("To delete")
        sheet_id = sheet.id
        sheet.unlink()
        events = self.Event.search(
            [("token_id", "=", self.token.id), ("event_type", "=", "delete")]
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(json.loads(events.payload)["spreadsheet_id"], sheet_id)

    def test_no_delete_event_when_unlink_is_refused(self):
        sheet = self._readable_sheet("Cannot delete")
        # A reader may not delete; a caller catching the error must not end
        # up with a "deleted" event for a spreadsheet that still exists.
        with self.assertRaises(AccessError):
            sheet.with_user(self.sheet_user).unlink()
        self.assertTrue(sheet.exists())
        events = self.Event.search(
            [("token_id", "=", self.token.id), ("event_type", "=", "delete")]
        )
        self.assertFalse(events)

    def test_scoped_token_skips_unrelated_spreadsheet(self):
        other = self._readable_sheet("Scoped-only")
        scoped = self.Token.create(
            {
                "name": "Scoped token",
                "user_id": self.sheet_user.id,
                "webhook_url": f"https://{PUBLIC_IP}/hook",
                "spreadsheet_ids": [(6, 0, other.ids)],
            }
        )
        unrelated = self._readable_sheet("Unrelated")
        events = self.Event.search(
            [("token_id", "=", scoped.id), ("spreadsheet_id", "=", unrelated.id)]
        )
        self.assertFalse(events)

    def test_manager_cannot_forge_events(self):
        # The cron signs whatever payload an event holds: nobody but the
        # system may create or change events.
        sheet = self._readable_sheet("Forge target")
        event = self._events(sheet, "create")
        Event = self.Event.with_user(self.sheet_manager)
        with self.assertRaises(AccessError):
            Event.create(
                {
                    "token_id": self.token.id,
                    "event_type": "update",
                    "payload": '{"forged": true}',
                }
            )
        with self.assertRaises(AccessError):
            event.with_user(self.sheet_manager).write({"payload": "{}"})
        # Reading and cleaning up the log stays possible.
        self.assertTrue(event.with_user(self.sheet_manager).read(["payload"]))
        event.with_user(self.sheet_manager).unlink()

    def test_user_cannot_read_other_users_events(self):
        sheet = self._readable_sheet("Visible to owner only")
        event = self._events(sheet, "create")
        self.assertTrue(event.with_user(self.sheet_user).read(["payload"]))
        self.assertFalse(
            self.Event.with_user(self.other_sheet_user).search([("id", "=", event.id)])
        )

    # ------------------------------------------------------------------
    # Delivery (SSRF hardening at send time)
    # ------------------------------------------------------------------
    def _pending_event(self, url="https://hooks.example.com/in"):
        # Saving the URL runs the save-time DNS check: answer it publicly.
        with patch(GETADDRINFO, fake_dns({"hooks.example.com": [PUBLIC_IP]})):
            self.token.sudo().write({"webhook_url": url})
        sheet = self._readable_sheet("Delivery sheet")
        return self._events(sheet, "create")

    def test_delivery_pins_resolved_ip_and_signs_payload(self):
        event = self._pending_event("https://hooks.example.com/in?x=1")
        with (
            patch(GETADDRINFO, fake_dns({"hooks.example.com": [PUBLIC_IP]})),
            MockHTTPClient(return_status=204, return_body="") as mock,
        ):
            event._deliver()
        mock.assert_called_once()
        request = mock.calls[0]
        self.assertTrue(request.url.startswith(f"https://{PUBLIC_IP}:443/in"))
        self.assertEqual(request.headers["Host"], "hooks.example.com")
        key = hashlib.sha256(self.secret.encode()).hexdigest()
        expected = hmac.new(key.encode(), event.payload.encode(), hashlib.sha256)
        self.assertEqual(
            request.headers["X-Spreadsheet-Signature"],
            f"sha256={expected.hexdigest()}",
        )
        self.assertNotIn(self.secret, json.dumps(dict(request.headers)))
        self.assertTrue(event.delivered)
        self.assertEqual(event.response_status, 204)

    def test_redirect_to_private_address_not_followed(self):
        event = self._pending_event()
        calls = []

        def adapter_send(adapter, request, **kwargs):
            calls.append(request.url)
            response = requests.Response()
            response.request = request
            response.url = request.url
            response._content = b""
            response._content_consumed = True
            if len(calls) == 1:
                response.status_code = 302
                response.headers["Location"] = "http://169.254.169.254/latest"
            else:
                response.status_code = 200
            return response

        with (
            patch(GETADDRINFO, fake_dns({"hooks.example.com": [PUBLIC_IP]})),
            # requests follows redirects inside Session.send: run the real one
            # (MockHTTPClient and the test harness both replace it)...
            patch.object(requests.sessions.Session, "send", test_common._super_send),
            # ...and fake only the network layer below it.
            patch.object(requests.adapters.HTTPAdapter, "send", adapter_send),
        ):
            event._deliver()
        # Exactly one request, to the public IP; the redirect is not followed.
        self.assertEqual(len(calls), 1, calls)
        self.assertTrue(calls[0].startswith(f"https://{PUBLIC_IP}:443/"))
        self.assertFalse(event.delivered)
        self.assertEqual(event.response_status, 302)
        self.assertEqual(event.retry_count, 1)

    def test_token_without_secret_is_not_sent(self):
        token = self.Token.create(
            {
                "name": "No secret yet",
                "user_id": self.sheet_user.id,
                "webhook_url": f"https://{PUBLIC_IP}/hook",
            }
        )
        sheet = self._readable_sheet("Unsigned")
        event = self.Event.search(
            [("token_id", "=", token.id), ("spreadsheet_id", "=", sheet.id)]
        )
        self.assertEqual(len(event), 1)
        with MockHTTPClient() as mock:
            event._deliver()
        mock.assert_called(0)
        self.assertFalse(event.delivered)
        self.assertEqual(event.retry_count, 1)
        self.assertIn("Generate Token", event.sudo().response_body)

    def test_slow_endpoint_stopped_by_total_deadline(self):
        # An endpoint dripping one header byte at a time never trips the
        # per-read socket timeout; the total deadline must end the call.
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(5)
        self.addCleanup(server.close)
        port = server.getsockname()[1]

        def drip():
            try:
                conn, _addr = server.accept()
            except OSError:
                return
            with conn, contextlib.suppress(OSError):
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\n")
                for _i in range(30):
                    conn.sendall(b"X")
                    time.sleep(0.2)

        thread = threading.Thread(target=drip, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        loopback = [ipaddress.ip_address("127.0.0.1")]
        started = time.monotonic()
        with (
            patch.object(webhook_tools, "resolve_public_ips", return_value=loopback),
            self.assertRaises(requests.Timeout),
        ):
            webhook_tools.post_webhook(
                f"http://hooks.example.com:{port}/in", "{}", total_timeout=1
            )
        self.assertLess(time.monotonic() - started, 4)

    def test_cron_stops_when_time_budget_is_spent(self):
        event = self._pending_event()
        with (
            patch.object(sheet_module, "CRON_TIME_BUDGET", -1),
            MockHTTPClient() as mock,
        ):
            self.Event._cron_deliver_webhooks()
        mock.assert_called(0)
        self.assertEqual(event.retry_count, 0)

    @mute_logger(DELIVERY_LOGGER)
    def test_dns_rebinding_to_private_address_blocked(self):
        # Valid (public) when saved, private at send time.
        event = self._pending_event()
        with (
            patch(GETADDRINFO, fake_dns({"hooks.example.com": ["10.0.0.5"]})),
            MockHTTPClient() as mock,
        ):
            event._deliver()
        mock.assert_called(0)
        self.assertFalse(event.delivered)
        self.assertEqual(event.response_status, 0)
        self.assertIn("10.0.0.5", event.sudo().response_body)

    @mute_logger(DELIVERY_LOGGER)
    def test_mixed_dns_answer_blocked(self):
        event = self._pending_event()
        with (
            patch(
                GETADDRINFO,
                fake_dns({"hooks.example.com": [PUBLIC_IP, "127.0.0.1"]}),
            ),
            MockHTTPClient() as mock,
        ):
            event._deliver()
        mock.assert_called(0)
        self.assertFalse(event.delivered)

    def test_post_webhook_disables_redirects(self):
        with (
            patch(GETADDRINFO, fake_dns({"hooks.example.com": [PUBLIC_IP]})),
            patch.object(
                webhook_tools.requests.Session,
                "post",
                autospec=True,
                side_effect=RuntimeError("stop"),
            ) as post,
        ):
            with self.assertRaises(RuntimeError):
                webhook_tools.post_webhook("https://hooks.example.com/in", "{}")
        kwargs = post.call_args.kwargs
        self.assertIs(kwargs["allow_redirects"], False)
        self.assertTrue(kwargs["timeout"])

    def test_public_ip_classifier(self):
        for address in (
            "127.0.0.1",
            "10.1.2.3",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "::1",
            "fe80::1",
            "fd00::1",
            "::ffff:10.0.0.1",
            "64:ff9b::a00:1",
            "2002:a00:1::1",
        ):
            self.assertFalse(webhook_tools.is_public_ip(address), address)
        for address in (PUBLIC_IP, "8.8.8.8", "2606:4700:4700::1111"):
            self.assertTrue(webhook_tools.is_public_ip(address), address)
