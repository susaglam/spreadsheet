# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo import http
from odoo.http import request


class SpreadsheetApiController(http.Controller):
    """REST API endpoints for external spreadsheet integration.

    Authentication: Bearer token in `Authorization` header, or `token` query param.
    """

    def _authenticate(self):
        auth = request.httprequest.headers.get("Authorization", "")
        token = None
        if auth.startswith("Bearer "):
            token = auth[7:]
        else:
            token = request.httprequest.args.get("token") or request.params.get("token")
        if not token:
            return None
        result = request.env["spreadsheet.api.token"].sudo().authenticate(token)
        return result  # Can be False, "RATE_LIMITED", or the token record

    def _handle_auth(self):
        """Returns (token_record, error_response). One will be None."""
        result = self._authenticate()
        if result == "RATE_LIMITED":
            return None, self._json_response(
                {"error": "Rate limit exceeded. Try again later."},
                status=429,
            )
        if not result:
            return None, self._json_response({"error": "Unauthorized"}, status=401)
        return result, None

    def _json_response(self, data, status=200):
        return request.make_response(
            json.dumps(data, default=str),
            headers=[("Content-Type", "application/json")],
            status=status,
        )

    @http.route(
        "/api/spreadsheet/list",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def list_spreadsheets(self, **kw):
        token_rec, err = self._handle_auth()
        if err:
            return err

        env = request.env(user=token_rec.user_id)
        if token_rec.spreadsheet_ids:
            sheets = token_rec.spreadsheet_ids
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
    )
    def get_spreadsheet(self, spreadsheet_id, **kw):
        token_rec, err = self._handle_auth()
        if err:
            return err

        # Check access
        if (
            token_rec.spreadsheet_ids
            and spreadsheet_id not in token_rec.spreadsheet_ids.ids
        ):
            return self._json_response({"error": "Forbidden"}, status=403)

        env = request.env(user=token_rec.user_id)
        sheet = env["spreadsheet.spreadsheet"].browse(spreadsheet_id)
        if not sheet.exists():
            return self._json_response({"error": "Not found"}, status=404)

        data = sheet.get_spreadsheet_data()
        return self._json_response(data)

    @http.route(
        "/api/spreadsheet/<int:spreadsheet_id>/cells",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_cells(self, spreadsheet_id, sheet=None, **kw):
        """Return a simplified cell-by-cell representation for external tools."""
        token_rec, err = self._handle_auth()
        if err:
            return err

        if (
            token_rec.spreadsheet_ids
            and spreadsheet_id not in token_rec.spreadsheet_ids.ids
        ):
            return self._json_response({"error": "Forbidden"}, status=403)

        env = request.env(user=token_rec.user_id)
        ss = env["spreadsheet.spreadsheet"].browse(spreadsheet_id)
        if not ss.exists():
            return self._json_response({"error": "Not found"}, status=404)

        raw = ss.spreadsheet_raw or {}
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
