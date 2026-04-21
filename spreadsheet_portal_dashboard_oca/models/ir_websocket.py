# Copyright 2026 Badkamertien
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
        if self.env.uid and not self.env.user._is_internal():
            channels = list(channels)
            for channel in channels:
                if isinstance(channel, str):
                    match = re.match(r"spreadsheet_oca;(\w+(?:\.\w+)*);(\d+)", channel)
                    if match:
                        model_name = match[1]
                        res_id = int(match[2])

                        if model_name != "spreadsheet.dashboard":
                            # Only allow portal access to dashboards
                            continue

                        # Check if this dashboard is assigned to the portal user
                        partner = self.env.user.partner_id
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
                        if portal_dash and portal_dash._is_accessible_by_partner(
                            partner
                        ):
                            channels.append(
                                (
                                    self.env.registry.db_name,
                                    model_name,
                                    res_id,
                                    "spreadsheet_oca",
                                )
                            )
                        # Don't raise AccessDenied — just skip silently

        return super()._build_bus_channel_list(channels)
