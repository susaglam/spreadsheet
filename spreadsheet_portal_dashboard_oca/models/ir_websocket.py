# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import models

_logger = logging.getLogger(__name__)

SPREADSHEET_CHANNEL_PREFIX = "spreadsheet_oca;"


class IrWebsocket(models.AbstractModel):
    _inherit = "ir.websocket"

    def _build_bus_channel_list(self, channels):
        """Never subscribe non-internal users to spreadsheet edition channels.

        The spreadsheet_oca channel of a dashboard broadcasts every
        collaborative revision: raw cell formulas, pivot/list definitions with
        their models and domains, Data sheet edits and CLIENT_* messages with
        internal user details. The portal preview does not listen to the bus
        at all (it renders a sanitized snapshot and is refreshed by reloading
        the page), so portal users have no reason to receive any of it.

        Earlier versions of this module granted that channel to portal users
        with an assignment; that grant is gone. The channel is dropped
        silently instead of raising AccessDenied, because raising would abort
        the WHOLE bus subscription of the session (chat, notifications), not
        just this channel.
        """
        if self.env.uid and not self.env.user._is_internal():
            kept = []
            for channel in channels:
                if isinstance(channel, str) and channel.startswith(
                    SPREADSHEET_CHANNEL_PREFIX
                ):
                    _logger.debug(
                        "Ignoring spreadsheet bus channel %r for non-internal user %s",
                        channel,
                        self.env.uid,
                    )
                    continue
                kept.append(channel)
            channels = kept
        return super()._build_bus_channel_list(channels)
