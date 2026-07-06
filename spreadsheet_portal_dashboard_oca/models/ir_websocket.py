# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import re

from odoo import models


class IrWebsocket(models.AbstractModel):
    _inherit = "ir.websocket"

    def _build_bus_channel_list(self, channels):
        """Allow portal users to subscribe to spreadsheet bus channels
        for dashboards that have been explicitly assigned to them via
        spreadsheet.portal.dashboard.
        """
        # Only PORTAL users get the relaxed dashboard subscription. Public
        # users (also non-internal) must NOT — they fall through to the parent,
        # which correctly denies them. Internal users use the normal path too.
        if self.env.uid and self.env.user._is_portal():
            partner = self.env.user.partner_id
            new_channels = []
            for channel in channels:
                match = (
                    re.match(r"spreadsheet_oca;(\w+(?:\.\w+)*);(\d+)", channel)
                    if isinstance(channel, str)
                    else None
                )
                if not match:
                    # Non-spreadsheet_oca channels pass through untouched.
                    new_channels.append(channel)
                    continue

                # Drop the raw spreadsheet_oca string entirely so the parent
                # override never sees it and never raises AccessDenied. For an
                # accessible dashboard we substitute a resolved bus tuple; for
                # anything else the channel is silently removed.
                model_name = match[1]
                res_id = int(match[2])
                if model_name != "spreadsheet.dashboard":
                    continue

                portal_dash = (
                    self.env["spreadsheet.portal.dashboard"]
                    .sudo()
                    .search(
                        [
                            ("dashboard_id", "=", res_id),
                            ("active", "=", True),
                        ],
                        limit=1,
                    )
                )
                if portal_dash and portal_dash._is_accessible_by_partner(partner):
                    new_channels.append(
                        (
                            self.env.registry.db_name,
                            model_name,
                            res_id,
                            "spreadsheet_oca",
                        )
                    )
            return super()._build_bus_channel_list(new_channels)

        return super()._build_bus_channel_list(channels)
