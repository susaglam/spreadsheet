# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json

from odoo import fields, http
from odoo.http import request


class SpreadsheetPublicShareController(http.Controller):
    @http.route(
        "/spreadsheet/public/<string:token>",
        type="http",
        auth="public",
        website=True,
        csrf=False,
    )
    def public_spreadsheet_view(self, token, password=None, **kw):
        share = (
            request.env["spreadsheet.public.share"].sudo().verify_token(token, password)
        )
        if not share:
            # Check if password is needed
            raw_share = (
                request.env["spreadsheet.public.share"]
                .sudo()
                .search([("token", "=", token), ("active", "=", True)], limit=1)
            )
            # A still-valid, password-protected link must keep re-prompting
            # (with an error banner on a wrong attempt) instead of dead-ending
            # on the "Invalid or Expired Link" page. Only unknown / inactive /
            # expired tokens fall through to public_share_invalid.
            if (
                raw_share
                and raw_share.password
                and (
                    not raw_share.expires_at
                    or raw_share.expires_at >= fields.Datetime.now()
                )
            ):
                return request.render(
                    "spreadsheet_public_share_oca.public_password_prompt",
                    {"token": token, "error": bool(password)},
                )
            return request.render(
                "spreadsheet_public_share_oca.public_share_invalid", {}
            )

        spreadsheet = share.spreadsheet_id.sudo()
        return request.render(
            "spreadsheet_public_share_oca.public_spreadsheet_view",
            {
                "share": share,
                "spreadsheet": spreadsheet,
                "sheets": share.get_rendered_sheets(),
            },
        )

    @http.route(
        "/spreadsheet/public/<string:token>/download",
        type="http",
        auth="public",
        csrf=False,
    )
    def public_spreadsheet_download(self, token, password=None, **kw):
        # count=False: a file download must not inflate the page view_count.
        share = (
            request.env["spreadsheet.public.share"]
            .sudo()
            .verify_token(token, password, count=False)
        )
        if not share or not share.allow_download:
            return request.not_found()

        spreadsheet = share.spreadsheet_id.sudo()
        # The server has no o-spreadsheet engine, so it cannot render a real
        # .xlsx (the old code streamed the JSON binary under a .xlsx name, which
        # Excel refused to open). Serve the o-spreadsheet JSON honestly instead;
        # it re-imports into Odoo / o-spreadsheet losslessly.
        raw = spreadsheet.spreadsheet_raw or {}
        content = json.dumps(raw).encode("utf-8")

        filename = f"{spreadsheet.name}.json"
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "application/json"),
                ("Content-Disposition", f'attachment; filename="{filename}"'),
            ],
        )
