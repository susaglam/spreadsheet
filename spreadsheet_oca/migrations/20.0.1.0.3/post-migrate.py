# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""20.0.1.0.3: scorecard charts in stored revisions use the 20.0 formula format.

o-spreadsheet 20.0 (data version 19.5.1) reads a scorecard chart's ``keyValue``
and ``baseline`` as formulas (``=Sheet1!A1``); saas-19.4 stored a bare range
(``Sheet1!A1``). The workbook itself (``spreadsheet_binary_data``) is upgraded
by o-spreadsheet when it is opened (its 19.5.1 migration step), but the
collaborative revisions that are not folded into the workbook yet are replayed
exactly as recorded: a bare range then shows as the text "Sheet1!A1" instead
of the cell value, and is saved like that on the next save.

This script adds the ``=`` to the scorecard definitions inside the commands of
stored REMOTE_REVISION rows (CREATE_CHART / UPDATE_CHART ...). SNAPSHOT rows
carry a whole workbook with its own ``version`` that o-spreadsheet migrates
itself, so they are left alone. A value that already starts with ``=`` is
kept, so the script is idempotent. A row that cannot be read is logged and
skipped; the upgrade never stops on it.
"""

import json
import logging

from odoo.tools import SQL

_logger = logging.getLogger(__name__)

SCORECARD_FORMULA_KEYS = ("keyValue", "baseline")


def _upgrade_scorecards(node):
    """Prefix ``=`` to the scorecard ranges found in ``node``, in place.

    :return: True when something changed
    """
    changed = False
    if isinstance(node, dict):
        if node.get("type") == "scorecard":
            for key in SCORECARD_FORMULA_KEYS:
                value = node.get(key)
                if isinstance(value, str) and value and not value.startswith("="):
                    node[key] = f"={value}"
                    changed = True
        for value in node.values():
            changed = _upgrade_scorecards(value) or changed
    elif isinstance(node, list):
        for item in node:
            changed = _upgrade_scorecards(item) or changed
    return changed


def _upgrade_revision_commands(commands_json):
    """Return the upgraded JSON of one revision, or None when unchanged."""
    message = json.loads(commands_json)
    if not isinstance(message, dict) or not _upgrade_scorecards(
        message.get("commands")
    ):
        return None
    return json.dumps(message)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        SQL(
            """
            SELECT id, commands
              FROM spreadsheet_oca_revision
             WHERE type = 'REMOTE_REVISION'
               AND commands LIKE %s
            """,
            "%scorecard%",
        )
    )
    upgraded = 0
    for revision_id, commands_json in cr.fetchall():
        try:
            new_json = _upgrade_revision_commands(commands_json)
        except (TypeError, ValueError):
            _logger.warning(
                "spreadsheet_oca: revision %s has unreadable commands; its "
                "scorecard charts (if any) were not converted to the 20.0 "
                "formula format. Open the spreadsheet and check its scorecards.",
                revision_id,
                exc_info=True,
            )
            continue
        if new_json is None:
            continue
        cr.execute(
            SQL(
                "UPDATE spreadsheet_oca_revision SET commands = %s WHERE id = %s",
                new_json,
                revision_id,
            )
        )
        upgraded += 1
    if upgraded:
        _logger.info(
            "spreadsheet_oca: converted the scorecard charts of %s stored "
            "revision(s) to the 20.0 formula format",
            upgraded,
        )
