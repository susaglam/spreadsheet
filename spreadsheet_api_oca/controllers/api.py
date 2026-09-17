# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from ..models.api_token import RATE_LIMITED
from ..tools.rate_limit import SlidingWindowLimiter, client_ip_bucket

_logger = logging.getLogger(__name__)

ALLOW_QUERY_TOKEN_PARAM = "spreadsheet_api_oca.allow_query_token"
TOKENS_MENU = "Spreadsheets > Configuration > API Tokens"

# Error bodies are machine-facing and therefore kept in English, with a
# stable shape: {"error": <short label>, "code": <stable code>, "message":
# <what failed, why, and how to fix it>}. "error" keeps the labels of
# previous versions so existing clients keep matching them.
QUERY_TOKEN_DISABLED_MESSAGE = (
    "Passing the API token in the URL query string (?token=...) is disabled, "
    "because URLs are written to server logs, proxy logs and browser history "
    "where the secret would leak. Send it as the HTTP header "
    "'Authorization: Bearer <token>' instead. If a client really cannot send "
    "headers, an administrator can set the system parameter "
    f"'{ALLOW_QUERY_TOKEN_PARAM}' to 'True'."
)
MISSING_TOKEN_MESSAGE = (
    "Missing API token. Send it as the HTTP header "
    f"'Authorization: Bearer <token>'. Create a token in {TOKENS_MENU}."
)
INVALID_TOKEN_MESSAGE = (
    "The API token is invalid, expired, archived or bound to a user that is "
    f"not allowed to use the API. Check the token in {TOKENS_MENU} or generate "
    "a new one."
)
RATE_LIMITED_MESSAGE = (
    "Too many requests with this token, or too many failed authentication "
    "attempts from your address, in the last minute. Wait a minute before "
    "retrying; the token's Rate Limit (per minute) can be raised in "
    f"{TOKENS_MENU}."
)
FORBIDDEN_SCOPE_MESSAGE = (
    "Spreadsheet {id} is not in this token's Allowed Spreadsheets, so the "
    f"token may not read it. Add it to Allowed Spreadsheets in {TOKENS_MENU}, "
    "or leave that list empty to allow every spreadsheet the token user can "
    "read."
)
NOT_FOUND_MESSAGE = (
    "Spreadsheet {id} does not exist or the token user cannot read it. Call "
    "/api/spreadsheet/list for the ids this token can use, or share the "
    "spreadsheet with the token user."
)

# Log a refused query-string token at most once per hour per client, so the
# administrator learns which integration broke without flooding the log.
QUERY_TOKEN_LOG_LIMITER = SlidingWindowLimiter(window=3600, prune_interval=3600)


class SpreadsheetApiController(http.Controller):
    """REST API endpoints for external spreadsheet integration.

    Authentication: Bearer token in the ``Authorization`` header. The
    ``token`` query parameter is only accepted when the system parameter
    ``spreadsheet_api_oca.allow_query_token`` is ``True`` (off by default).
    """

    def _query_token_allowed(self):
        return (
            request.env["ir.config_parameter"]
            .sudo()
            .get_bool(ALLOW_QUERY_TOKEN_PARAM, False)
        )

    def _log_refused_query_token(self, query_token):
        remote_addr = request.httprequest.remote_addr
        key = (request.env.cr.dbname, client_ip_bucket(remote_addr))
        if not QUERY_TOKEN_LOG_LIMITER.allow(key, 1):
            return
        token = (
            request.env["spreadsheet.api.token"].sudo()._find_valid_token(query_token)
        )
        _logger.warning(
            "Spreadsheet API: refused a token sent in the URL query string "
            "from %s (token id: %s). Configure that client to send "
            "'Authorization: Bearer <token>', or set the system parameter "
            "%s to True.",
            remote_addr,
            token.id or "unknown",
            ALLOW_QUERY_TOKEN_PARAM,
        )

    def _extract_token(self):
        """Return ``(token, error_response)``; at most one is set."""
        auth = request.httprequest.headers.get("Authorization", "")
        scheme, _sep, value = auth.strip().partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip(), None
        query_token = request.httprequest.args.get("token")
        if query_token:
            if self._query_token_allowed():
                return query_token, None
            self._log_refused_query_token(query_token)
            return None, self._unauthorized(
                "query_token_disabled", QUERY_TOKEN_DISABLED_MESSAGE
            )
        return None, self._unauthorized("missing_token", MISSING_TOKEN_MESSAGE)

    def _error(self, status, error, code, message, headers=None):
        return self._json_response(
            {"error": error, "code": code, "message": message},
            status=status,
            headers=headers,
        )

    def _unauthorized(self, code, message):
        return self._error(
            401,
            "Unauthorized",
            code,
            message,
            headers=[("WWW-Authenticate", 'Bearer realm="spreadsheet-api"')],
        )

    def _handle_auth(self):
        """Returns (token_record, error_response). One will be None."""
        token, err = self._extract_token()
        if err:
            return None, err
        Token = request.env["spreadsheet.api.token"].sudo()
        result = Token._authenticate(token, remote_addr=request.httprequest.remote_addr)
        if result == RATE_LIMITED:
            return None, self._error(
                429,
                "Rate limit exceeded. Try again later.",
                "rate_limited",
                RATE_LIMITED_MESSAGE,
                headers=[("Retry-After", "60")],
            )
        # Defense in depth: never build an environment for the superuser
        # (env(user=1) is sudo), a portal/public user or an archived user.
        if not result or not Token._is_allowed_api_user(result.user_id):
            return None, self._unauthorized("invalid_token", INVALID_TOKEN_MESSAGE)
        return result, None

    def _user_env(self, token_rec):
        return request.env(user=token_rec.user_id.id, su=False)

    def _json_response(self, data, status=200, headers=None):
        return request.make_json_response(data, headers=headers, status=status)

    def _not_found(self, spreadsheet_id):
        return self._error(
            404,
            "Not found",
            "not_found",
            NOT_FOUND_MESSAGE.format(id=spreadsheet_id),
        )

    def _forbidden_scope(self, token_rec, spreadsheet_id):
        if (
            token_rec.spreadsheet_ids
            and spreadsheet_id not in token_rec.spreadsheet_ids.ids
        ):
            return self._error(
                403,
                "Forbidden",
                "forbidden_scope",
                FORBIDDEN_SCOPE_MESSAGE.format(id=spreadsheet_id),
            )
        return None

    @http.route(
        "/api/spreadsheet/list",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
        save_session=False,
    )
    def list_spreadsheets(self, **kw):
        token_rec, err = self._handle_auth()
        if err:
            return err

        env = self._user_env(token_rec)
        # Resolve the scoped set under the user's env so record rules apply,
        # keeping list consistent with get/cells (which 404 on unreadable
        # sheets) instead of leaking id/name/company_id.
        if token_rec.spreadsheet_ids:
            sheets = env["spreadsheet.spreadsheet"].search(
                [("id", "in", token_rec.spreadsheet_ids.ids)]
            )
        else:
            sheets = env["spreadsheet.spreadsheet"].search([])

        data = [
            {"id": s.id, "name": s.name, "company_id": s.company_id.id} for s in sheets
        ]
        return self._json_response({"spreadsheets": data})

    @http.route(
        "/api/spreadsheet/<int:spreadsheet_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
        save_session=False,
    )
    def get_spreadsheet(self, spreadsheet_id, **kw):
        token_rec, err = self._handle_auth()
        if err:
            return err
        forbidden = self._forbidden_scope(token_rec, spreadsheet_id)
        if forbidden:
            return forbidden

        env = self._user_env(token_rec)
        sheet = env["spreadsheet.spreadsheet"].browse(spreadsheet_id)
        try:
            if not sheet.exists():
                return self._not_found(spreadsheet_id)
            data = sheet.get_spreadsheet_data()
        except (AccessError, MissingError):
            # Same answer as a missing record: don't confirm it exists.
            return self._not_found(spreadsheet_id)
        return self._json_response(data)

    @http.route(
        "/api/spreadsheet/<int:spreadsheet_id>/cells",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
        save_session=False,
    )
    def get_cells(self, spreadsheet_id, sheet=None, **kw):
        """Return a simplified cell-by-cell representation for external tools."""
        token_rec, err = self._handle_auth()
        if err:
            return err
        forbidden = self._forbidden_scope(token_rec, spreadsheet_id)
        if forbidden:
            return forbidden

        env = self._user_env(token_rec)
        ss = env["spreadsheet.spreadsheet"].browse(spreadsheet_id)
        try:
            if not ss.exists():
                return self._not_found(spreadsheet_id)
            raw = ss.spreadsheet_raw or {}
        except (AccessError, MissingError):
            return self._not_found(spreadsheet_id)
        output = {}
        for s in raw.get("sheets", []):
            sheet_name = s.get("name", "Sheet")
            if sheet and sheet_name != sheet:
                continue
            output[sheet_name] = {
                ref: {"content": c.get("content", "")}
                for ref, c in (s.get("cells") or {}).items()
            }
        return self._json_response({"sheets": output})
