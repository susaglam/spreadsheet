# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _load_menus_blacklist(self):
        """Hide Help guide menus whose formulas come from a missing module."""
        res = super()._load_menus_blacklist()
        try:
            hidden = self.env["spreadsheet.tutorial"]._get_unavailable_guide_menu_ids()
        except Exception:  # never let the Help menu break the whole web client
            _logger.warning(
                "spreadsheet_help_oca: could not compute unavailable guide menus",
                exc_info=True,
            )
            hidden = []
        return list(res) + hidden
