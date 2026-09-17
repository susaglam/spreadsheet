# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo.api import SUPERUSER_ID, Environment

_logger = logging.getLogger(__name__)

MODULE = "spreadsheet_vendor_scorecard_oca"
# The cron and the ir.actions.server row it _inherits from (the XML loader
# names the parent's xmlid "<cron xmlid>_ir_actions_server").
CRON_XMLIDS = (
    "ir_cron_vendor_scorecard",
    "ir_cron_vendor_scorecard_ir_actions_server",
)


def migrate(cr, version):
    """Flag the vendor scorecard cron as noupdate on existing databases.

    Up to saas~19.4.1.0.1 the cron was loaded from the views file without
    noupdate, so its ir.model.data rows carry noupdate=False. It now lives in
    data/ir_cron.xml under noupdate="1"; a fresh install gets noupdate=True on
    both rows. Align upgraded databases so an admin's schedule / user / active
    changes survive later upgrades the same way. The record values themselves
    are unchanged, and the xmlid is the same, so no duplicate cron appears.

    Idempotent (only rows still at False are written) and never blocks the
    upgrade: any failure is logged with the manual fix.
    """
    if not version:
        return
    env = Environment(cr, SUPERUSER_ID, {})
    try:
        with cr.savepoint():
            rows = (
                env["ir.model.data"]
                .sudo()
                .search(
                    [
                        ("module", "=", MODULE),
                        ("name", "in", CRON_XMLIDS),
                        ("noupdate", "=", False),
                    ]
                )
            )
            if rows:
                rows.write({"noupdate": True})
                _logger.info(
                    "%s: marked %s scheduled-action xmlid(s) as noupdate.",
                    MODULE,
                    len(rows),
                )
    except Exception:  # noqa: BLE001 - a migration must never abort the upgrade
        _logger.warning(
            "%s: could not mark the vendor scorecard cron as noupdate; the cron "
            "still works, but a later upgrade may reset admin changes to it. "
            "Fix: in Settings > Technical > External Identifiers, tick "
            "'Non Updatable' on %s.",
            MODULE,
            ", ".join(f"{MODULE}.{name}" for name in CRON_XMLIDS),
            exc_info=True,
        )
