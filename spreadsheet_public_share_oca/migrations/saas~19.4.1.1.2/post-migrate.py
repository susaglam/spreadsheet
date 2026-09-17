# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Hash the share-link passwords that were stored in plain text.

Up to saas~19.4.1.1.1 ``spreadsheet.public.share.password`` was a stored Char
holding the password itself, readable by every spreadsheet user. The field is
now write-only and the value lives hashed in ``password_hash``. Odoo never drops
the old column on its own, so this script hashes every plain-text password into
``password_hash`` and then drops the ``password`` column so no clear-text copy
survives.

Idempotent: rows that already have a hash are left alone and the script does
nothing once the column is gone. A failure never aborts the module upgrade: it
is logged, rolled back to a savepoint, and the links whose password could not be
migrated are archived, so a formerly protected link is never left open without
its password.
"""

import logging

from odoo.api import SUPERUSER_ID, Environment
from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)


def _hash_passwords(env):
    cr = env.cr
    crypt = env["res.users"]._crypt_context()
    cr.execute(
        """
        SELECT id, password
          FROM spreadsheet_public_share
         WHERE password IS NOT NULL
           AND password != ''
           AND (password_hash IS NULL OR password_hash = '')
        """
    )
    rows = cr.fetchall()
    for share_id, plain_password in rows:
        cr.execute(
            "UPDATE spreadsheet_public_share SET password_hash = %s WHERE id = %s",
            (crypt.hash(plain_password), share_id),
        )
    cr.execute('ALTER TABLE spreadsheet_public_share DROP COLUMN "password"')
    return len(rows)


def _archive_unmigrated_links(cr):
    cr.execute(
        """
        UPDATE spreadsheet_public_share
           SET active = FALSE
         WHERE password IS NOT NULL
           AND password != ''
           AND (password_hash IS NULL OR password_hash = '')
     RETURNING id
        """
    )
    return [row[0] for row in cr.fetchall()]


def migrate(cr, version):
    if not version or not column_exists(cr, "spreadsheet_public_share", "password"):
        return
    env = Environment(cr, SUPERUSER_ID, {})
    try:
        with cr.savepoint():
            count = _hash_passwords(env)
        _logger.info(
            "Hashed %s public share password(s) and dropped the plain-text column.",
            count,
        )
    except Exception:  # noqa: BLE001 - an upgrade must never be aborted here
        _logger.exception(
            "Could not hash the public share passwords; the plain-text column "
            "spreadsheet_public_share.password was kept."
        )
        try:
            with cr.savepoint():
                archived = _archive_unmigrated_links(cr)
            if archived:
                _logger.warning(
                    "Archived the password-protected public share links %s so they "
                    "do not open without their password. Set a new password on "
                    "each link (Spreadsheet > Configuration > Public Share Links) "
                    "and reactivate it.",
                    archived,
                )
        except Exception:  # noqa: BLE001
            _logger.exception(
                "Could not archive the unmigrated password-protected share links; "
                "review them in Spreadsheet > Configuration > Public Share Links."
            )
    env.invalidate_all()
