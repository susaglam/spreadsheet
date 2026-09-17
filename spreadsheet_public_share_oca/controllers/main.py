# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import hashlib
import hmac
import json
import logging
import threading
import time
from collections import OrderedDict
from itertools import islice

from odoo import http
from odoo.http import request
from odoo.http.stream import content_disposition
from odoo.tools import osutil

_logger = logging.getLogger(__name__)

# Wrong passwords accepted per share token and client IP before the prompt is
# locked, and for how long the lock lasts (counted from the first wrong
# password). The lockout message of public_password_prompt and the README say
# "up to 15 minutes": update them together with this value.
PASSWORD_MAX_FAILURES = 5
PASSWORD_LOCK_SECONDS = 15 * 60
# Upper bound of tracked (token, IP) pairs so a flood of random tokens cannot
# grow the worker memory without limit.
PASSWORD_THROTTLE_MAX_KEYS = 10000

# Session key holding the proofs that a share password was already entered,
# and how many of them one visitor session keeps.
SESSION_GRANTS_KEY = "spreadsheet_public_share_grants"
SESSION_GRANTS_MAX = 20


class PasswordAttemptThrottle:
    """Bounded, pruned, in-memory counter of wrong share passwords.

    Like the login cooldown of ``res.users``, the counters live in the worker
    process: they are not shared between workers and reset on restart. That is
    enough to turn an online brute force into a handful of guesses per
    quarter-hour, without a database write on every failed attempt.
    """

    def __init__(
        self,
        max_failures=PASSWORD_MAX_FAILURES,
        window=PASSWORD_LOCK_SECONDS,
        max_keys=PASSWORD_THROTTLE_MAX_KEYS,
        clock=time.monotonic,
    ):
        self.max_failures = max_failures
        self.window = window
        self.max_keys = max_keys
        self._clock = clock
        self._entries = OrderedDict()  # key -> [failures, first_failure_at]
        self._lock = threading.Lock()

    @staticmethod
    def make_key(dbname, token, remote_addr):
        raw = f"{dbname}\x00{token}\x00{remote_addr}".encode()
        return hashlib.sha256(raw).hexdigest()

    def _is_locked_entry(self, entry):
        return entry[0] >= self.max_failures

    def _prune(self, now, keep=None):
        # Entries stay in order of their FIRST failure (an update never moves
        # them), and the lock window is counted from that first failure: the
        # expired entries are therefore always at the head.
        while self._entries:
            key, (_failures, first) = next(iter(self._entries.items()))
            if now - first < self.window:
                break
            del self._entries[key]
        excess = len(self._entries) - self.max_keys
        if excess <= 0:
            return
        # Over the bound: forget the oldest entries that are not locked first,
        # so a flood of new (token, IP) pairs cannot push an active lock out.
        unlocked = (
            key
            for key, entry in self._entries.items()
            if key != keep and not self._is_locked_entry(entry)
        )
        for key in list(islice(unlocked, excess)):
            del self._entries[key]
            excess -= 1
        # Every remaining entry is locked: drop the oldest locks.
        for key in list(islice((k for k in self._entries if k != keep), excess)):
            del self._entries[key]

    def _current(self, key, now):
        entry = self._entries.get(key)
        if entry and now - entry[1] >= self.window:
            del self._entries[key]
            return None
        return entry

    def is_locked(self, key):
        with self._lock:
            now = self._clock()
            self._prune(now)
            entry = self._current(key, now)
            return bool(entry) and self._is_locked_entry(entry)

    def register_failure(self, key):
        """Count one wrong password; return whether the key is now locked."""
        with self._lock:
            now = self._clock()
            entry = self._current(key, now)
            if entry is None:
                # A new (or expired and removed) key goes to the end.
                entry = self._entries[key] = [0, now]
            entry[0] += 1
            self._prune(now, keep=key)
            return self._is_locked_entry(entry)

    def reset(self, key):
        with self._lock:
            self._entries.pop(key, None)

    def clear(self):
        with self._lock:
            self._entries.clear()

    def __len__(self):
        return len(self._entries)


password_throttle = PasswordAttemptThrottle()


class SpreadsheetPublicShareController(http.Controller):
    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _password_throttle_key(self, token):
        return password_throttle.make_key(
            request.db or "", token, request.httprequest.remote_addr or ""
        )

    def _session_grants(self):
        grants = request.session.get(SESSION_GRANTS_KEY)
        if not isinstance(grants, list):
            return []
        return [grant for grant in grants if isinstance(grant, str)]

    def _session_has_grant(self, share):
        expected = share._get_access_grant()
        return any(
            hmac.compare_digest(expected, grant) for grant in self._session_grants()
        )

    def _session_add_grant(self, share):
        grant = share._get_access_grant()
        grants = [other for other in self._session_grants() if other != grant]
        grants.append(grant)
        request.session[SESSION_GRANTS_KEY] = grants[-SESSION_GRANTS_MAX:]

    def _posted_password(self, password):
        """Only accept a password sent in a POST body.

        A password in the query string (``?password=...``) would end up in
        reverse-proxy access logs, browser history and Referer headers, so a
        GET request relies on the session grant only.
        """
        if request.httprequest.method != "POST":
            return None
        return password

    def _authorize(self, token, password):
        """Resolve a public request into ``(share, state)``.

        ``state`` is one of ``ok``, ``invalid`` (unknown / revoked / expired),
        ``password_required``, ``wrong_password`` or ``locked`` (too many wrong
        passwords from this client for this link).
        """
        Share = request.env["spreadsheet.public.share"].sudo()
        share = Share._get_live_share(token)
        if not share:
            return Share, "invalid"
        if not share.has_password or self._session_has_grant(share):
            return share, "ok"
        key = self._password_throttle_key(token)
        if password_throttle.is_locked(key):
            # Refuse without even hashing the attempt.
            return share, "locked"
        if not password:
            return share, "password_required"
        if share._check_share_password(password):
            password_throttle.reset(key)
            self._session_add_grant(share)
            return share, "ok"
        if password_throttle.register_failure(key):
            _logger.warning(
                "Public spreadsheet share %s: password prompt locked for %s after "
                "%s wrong passwords.",
                share.id,
                request.httprequest.remote_addr,
                password_throttle.max_failures,
            )
            return share, "locked"
        return share, "wrong_password"

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @http.route(
        "/spreadsheet/public/<string:token>",
        type="http",
        auth="public",
        website=True,
        csrf=False,
    )
    def public_spreadsheet_view(self, token, password=None, **kw):
        share, state = self._authorize(token, self._posted_password(password))
        if state == "invalid":
            return request.render(
                "spreadsheet_public_share_oca.public_share_invalid", {}
            )
        if state != "ok":
            # A still-valid, password-protected link keeps re-prompting (with an
            # error banner on a wrong attempt) instead of dead-ending on the
            # "Invalid or Expired Link" page.
            return request.render(
                "spreadsheet_public_share_oca.public_password_prompt",
                {
                    "token": token,
                    "error": state == "wrong_password",
                    "locked": state == "locked",
                },
                status=429 if state == "locked" else 200,
            )

        share._register_view()
        return request.render(
            "spreadsheet_public_share_oca.public_spreadsheet_view",
            {
                "share": share,
                "spreadsheet": share.spreadsheet_id.sudo(),
                "sheets": share._get_rendered_sheets(),
            },
        )

    @http.route(
        "/spreadsheet/public/<string:token>/download",
        type="http",
        auth="public",
        csrf=False,
    )
    def public_spreadsheet_download(self, token, password=None, **kw):
        # A password-protected link is unlocked by the password entered on the
        # public page (session grant); a download does not count as a page view.
        share, state = self._authorize(token, self._posted_password(password))
        if state != "ok" or not share.allow_download:
            return request.not_found()

        spreadsheet = share.spreadsheet_id.sudo()
        # The server has no o-spreadsheet engine, so it cannot render a real
        # .xlsx; serve the o-spreadsheet JSON, which re-imports into Odoo /
        # o-spreadsheet losslessly. The file deliberately contains every sheet,
        # hidden and helper ones included: formulas on the visible sheets read
        # from them (documented on the allow_download field).
        raw = share._get_spreadsheet_data()
        if raw is None:
            return request.make_response(
                request.env._(
                    "The data of this spreadsheet could not be read, so it cannot "
                    "be downloaded right now. Please tell the person who shared "
                    "this link, so they can open the spreadsheet in Odoo and save "
                    "it again."
                ),
                headers=[("Content-Type", "text/plain; charset=utf-8")],
                status=500,
            )
        content = json.dumps(raw).encode("utf-8")

        filename = osutil.clean_filename(spreadsheet.name or "spreadsheet") + ".json"
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "application/json"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )
