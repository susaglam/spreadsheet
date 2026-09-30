# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SpreadsheetSpreadsheet(models.Model):
    _inherit = "spreadsheet.spreadsheet"

    def open_spreadsheet(self):
        """Explain instead of opening a help guide whose formulas are missing.

        The guides are shared read-only with every Spreadsheet user, so they
        also appear in the regular Spreadsheets kanban, list and form. Those
        Edit buttons call this method directly instead of the Help menu
        actions, so the missing-module check has to run here as well. Other
        spreadsheets are not affected.
        """
        self.ensure_one()
        try:
            notification = self.env[
                "spreadsheet.tutorial"
            ]._guide_unavailable_notification(self)
        except Exception:  # a broken help check must never block a spreadsheet
            _logger.warning(
                "spreadsheet_help_oca: guide availability check failed for "
                "spreadsheet %s",
                self.id,
                exc_info=True,
            )
            notification = None
        return notification or super().open_spreadsheet()
