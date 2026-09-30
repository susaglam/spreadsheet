# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""saas~19.4.1.0.2: remove the temporary ``DEFAULT 'public'`` that pre-migrate
put on ``ir_ui_view.visibility`` (see pre-migrate for why it was needed)."""

import logging

from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)


def _drop_temporary_view_visibility_default(cr):
    if not column_exists(cr, "ir_ui_view", "visibility"):
        return
    cr.execute(
        """
        SELECT column_default
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'ir_ui_view'
           AND column_name = 'visibility'
        """
    )
    row = cr.fetchone()
    if row and row[0] and row[0].startswith("'public'"):
        cr.execute("ALTER TABLE ir_ui_view ALTER COLUMN visibility DROP DEFAULT")


def migrate(cr, version):
    if not version:
        return
    try:
        with cr.savepoint():
            _drop_temporary_view_visibility_default(cr)
    except Exception:
        _logger.warning(
            "spreadsheet_pdf_report_oca: could not remove the temporary default "
            "on ir_ui_view.visibility; it is harmless (same value as website's "
            "own default) and can be dropped manually.",
            exc_info=True,
        )
