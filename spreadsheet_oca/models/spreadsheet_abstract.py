# Copyright 2022 CreuBlanca
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json
from typing import Any

from odoo import api, fields, models

CollaborationMessage = dict[str, Any]

# Message types that persist a spreadsheet.oca.revision row.
PERSISTED_REVISION_TYPES = (
    "REVISION_UNDONE",
    "REMOTE_REVISION",
    "REVISION_REDONE",
    "SNAPSHOT",
)


class SpreadsheetAbstract(models.AbstractModel):
    _name = "spreadsheet.abstract"
    _description = "Spreadsheet abstract for inheritance"
    _inherit = ["bus.listener.mixin"]

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    spreadsheet_binary_data = fields.Binary(
        string="Spreadsheet file",
        default=lambda self: base64.b64encode(
            self._empty_spreadsheet_data_bin()
        ).decode(),
    )
    spreadsheet_raw = fields.Serialized(
        inverse="_inverse_spreadsheet_raw", compute="_compute_spreadsheet_raw"
    )
    # Revisions hold the raw cell commands of every collaborative edit, so
    # spreadsheet.oca.revision has no ACL for regular users and this field is
    # restricted to administrators. Business code reads/writes revisions
    # through _get_spreadsheet_revisions() (sudo) AFTER checking access on
    # the parent record.
    spreadsheet_revision_ids = fields.One2many(
        "spreadsheet.oca.revision",
        inverse_name="res_id",
        domain=lambda r: [("model", "=", r._name)],
        groups="base.group_system",
        help="Technical: the collaborative edit history (revision commands) "
        "replayed on top of the stored spreadsheet file when it is opened. "
        "Only administrators can read it directly; users see its effect by "
        "opening the spreadsheet.",
    )

    @api.depends("spreadsheet_binary_data")
    def _compute_spreadsheet_raw(self):
        for dashboard in self:
            data = dashboard.spreadsheet_binary_data
            if not data:
                dashboard.spreadsheet_raw = {}
                continue
            # saas-19.4: reading a Binary(attachment=True) field returns a
            # BinaryValueAttachment wrapper, and bytes(wrapper) is the raw
            # (already base64-decoded) content — decode the JSON directly.
            # Older Odoo returned a base64 str/bytes, so keep a fallback.
            if isinstance(data, (bytes, bytearray, str)):
                raw = base64.b64decode(data)
            else:
                raw = bytes(data)
            dashboard.spreadsheet_raw = json.loads(raw.decode("UTF-8"))

    def _inverse_spreadsheet_raw(self):
        for record in self:
            # Store a clean base64 string (canonical Binary write format in
            # saas-19.4; base64.encodebytes' newline-wrapped bytes are avoided).
            record.spreadsheet_binary_data = base64.b64encode(
                json.dumps(record.spreadsheet_raw).encode("UTF-8")
            ).decode("ascii")

    def _empty_spreadsheet_data_bin(self):
        """Create an empty spreadsheet workbook.
        Returns raw JSON bytes.
        """
        return json.dumps(self._empty_spreadsheet_data()).encode()

    def _empty_spreadsheet_data(self):
        """Create an empty spreadsheet workbook.
        The sheet name should be the same for all users to allow consistent references
        in formulas. It is translated for the user creating the spreadsheet.
        """
        # sudo: res.lang is only readable through base.group_everyone, which
        # a user without an internal/portal role does not carry; the locale is
        # harmless formatting data.
        lang = self.env["res.lang"].sudo()._lang_get(self.env.user.lang)
        locale = lang._odoo_lang_to_spreadsheet_locale()
        return {
            "sheets": [
                {
                    "id": "sheet1",
                    "name": self.env._("Sheet1"),
                }
            ],
            "settings": {
                "locale": locale,
            },
            "revisionId": "START_REVISION",
        }

    def get_spreadsheet_data(self):
        self.ensure_one()
        # Revisions are read with sudo below, so the parent access check is
        # the only thing protecting them: it must stay first.
        self.check_access("read")
        mode = "normal"
        if not self.has_access("write"):
            mode = "readonly"
        return {
            "name": self.name,
            "spreadsheet_raw": self.spreadsheet_raw,
            "revisions": [
                dict(
                    json.loads(revision.commands),
                    nextRevisionId=revision.next_revision_id,
                    serverRevisionId=revision.server_revision_id,
                )
                for revision in self._get_spreadsheet_revisions()
            ],
            "mode": mode,
            "default_currency": self.env[
                "res.currency"
            ].get_company_currency_for_spreadsheet(),
            "user_locale": self.env["res.lang"]._get_user_spreadsheet_locale(),
        }

    def _get_spreadsheet_revisions(self):
        """Return the collaborative revisions of the records in ``self``.

        The result is a **sudo** recordset ordered by creation (id): revision
        commands contain cell contents and spreadsheet.oca.revision is not
        readable by regular users. Callers MUST check access on ``self``
        (``check_access('read')`` to read, ``check_access('write')`` to
        modify) before using it.
        """
        if not self.ids:
            return self.env["spreadsheet.oca.revision"].sudo()
        return (
            self.env["spreadsheet.oca.revision"]
            .sudo()
            .search(
                [("model", "=", self._name), ("res_id", "in", self.ids)],
                order="id",
            )
        )

    def open_spreadsheet(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "action_spreadsheet_oca",
            "params": {"spreadsheet_id": self.id, "model": self._name},
        }

    def send_spreadsheet_message(
        self, message: CollaborationMessage, access_token=None
    ):
        self.ensure_one()
        if message["type"] in PERSISTED_REVISION_TYPES:
            # Access check first: the revision is created with sudo because
            # spreadsheet.oca.revision has no ACL for regular users.
            self._check_access_spreadsheet("write")
            self.env["spreadsheet.oca.revision"].sudo().create(
                {
                    "model": self._name,
                    "res_id": self.id,
                    "type": message["type"],
                    "client_id": message.get("clientId"),
                    "next_revision_id": message["nextRevisionId"],
                    "server_revision_id": message["serverRevisionId"],
                    "commands": json.dumps(
                        self._build_spreadsheet_revision_commands_data(message)
                    ),
                }
            )
            if message["type"] != "SNAPSHOT":
                self._bus_send(
                    "notification",
                    dict(message, id=self.id),
                    subchannel="spreadsheet_oca",
                )
            return True
        elif message["type"] in ["CLIENT_JOINED", "CLIENT_LEFT", "CLIENT_MOVED"]:
            self._check_access_spreadsheet("read")
            self._bus_send(
                "notification", dict(message, id=self.id), subchannel="spreadsheet_oca"
            )
            return True
        return False

    def _check_access_spreadsheet(self, operation: str):
        """Raise AccessError unless the current user may ``operation`` self."""
        self.check_access(operation)
        return True

    @api.model
    def _build_spreadsheet_revision_commands_data(self, message):
        """Prepare spreadsheet revision commands data from the message"""
        commands = dict(message)
        commands.pop("serverRevisionId", None)
        commands.pop("nextRevisionId", None)
        commands.pop("clientId", None)
        return commands

    def write(self, vals):
        if "spreadsheet_raw" in vals:
            # A new base document invalidates the edit history. Check write
            # access on the parents before deleting their revisions with sudo.
            self.check_access("write")
            self._get_spreadsheet_revisions().unlink()
        return super().write(vals)

    def unlink(self):
        # Collect before the parents disappear; delete only once the parent
        # unlink (and its access check) succeeded, so no orphan revision
        # commands (cell contents) outlive their spreadsheet.
        revisions = self._get_spreadsheet_revisions()
        result = super().unlink()
        revisions.unlink()
        return result
