# Copyright 2023 CreuBlanca
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import re

from odoo import models

_logger = logging.getLogger(__name__)

SPREADSHEET_CHANNEL_RE = re.compile(r"spreadsheet_oca;(\w+(?:\.\w+)*);(\d+)")


class IrWebsocket(models.AbstractModel):
    _inherit = "ir.websocket"

    def _build_bus_channel_list(self, channels):
        """
        With this change we are adding an extra layer of security.
        Without it, any user was able to sniff how all happened using something like:

            const any_spreadsheet_id = 1234;
            const channel = "spreadsheet_oca;spreadsheet.spreadsheet" +
                            ";" + any_spreadsheet_id;
            bus_service.addChannel(channel);
            bus_service.addEventListener(
                "spreadsheet_oca",
                (message) => /* every revision arrives here */
            )

        """
        if self.env.uid:
            # Do not alter original list.
            channels = list(channels)
            for channel in channels:
                if isinstance(channel, str):
                    # fullmatch: trailing garbage must not resolve to a
                    # valid spreadsheet channel.
                    match = SPREADSHEET_CHANNEL_RE.fullmatch(channel)
                    if match:
                        model_name = match[1]
                        res_id = int(match[2])

                        # Edition channels are for internal users only. Skip
                        # the channel instead of raising AccessDenied: raising
                        # aborts the WHOLE bus subscription of that session
                        # (chat, notifications...), not just this channel.
                        if not self.env.user._is_internal():
                            _logger.debug(
                                "Ignoring spreadsheet bus channel %r: user %s is "
                                "not an internal user",
                                channel,
                                self.env.uid,
                            )
                            continue

                        # The channel name comes from the client: an unknown
                        # model (typo, uninstalled module, forged channel) must
                        # only skip this channel, never break the whole bus
                        # subscription with a KeyError.
                        if model_name not in self.env:
                            _logger.debug(
                                "Ignoring spreadsheet bus channel %r: unknown model %r",
                                channel,
                                model_name,
                            )
                            continue

                        # saas-19.4: ir.model.access model removed (merged into
                        # ir.access); model-level access check is now has_access().
                        if not self.env[model_name].has_access("read"):
                            continue
                        # If user don't have access to the model, we don't even try to
                        # read

                        document = self.env[model_name].search(
                            [("id", "=", res_id)], limit=1
                        )
                        # We do a search in order to apply the access rules.
                        # We just need to ensure that the user can read it

                        if not document.exists():
                            continue

                        channels.append(
                            (
                                self.env.registry.db_name,
                                model_name,
                                res_id,
                                "spreadsheet_oca",
                            )
                        )
        return super()._build_bus_channel_list(channels)
