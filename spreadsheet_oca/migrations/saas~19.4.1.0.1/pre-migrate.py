# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""saas~19.4.1.0.1: let this upgrade create its NEW ir.ui.view records
(``res_config_settings_view_form``) on databases where ``website`` is installed.

``website`` adds ``ir.ui.view.visibility`` as a required field, so the column
is NOT NULL without a database default. During ``-u`` this module is loaded
before ``website``: the registry does not know the field yet, the ORM leaves
the column out of the INSERT and PostgreSQL rejects the new view with
``null value in column "visibility" of relation "ir_ui_view"``. Fresh installs
are not affected (modules being installed load after the installed ones).

Give the column the same default ``website`` uses while this module's data is
loaded; ``post-migrate`` removes it again, so the schema ends up unchanged.
"""

import logging

from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version or not column_exists(cr, "ir_ui_view", "visibility"):
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
    if row and row[0] is None:
        cr.execute(
            "ALTER TABLE ir_ui_view ALTER COLUMN visibility SET DEFAULT 'public'"
        )
        _logger.info(
            "%s: temporary default 'public' on ir_ui_view.visibility "
            "so the new views of this upgrade can be created (removed again "
            "in post-migrate).",
            "spreadsheet_oca",
        )
