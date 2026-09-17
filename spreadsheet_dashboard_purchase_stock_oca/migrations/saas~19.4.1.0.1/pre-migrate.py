# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Make sure the "Purchases" dashboard section exists before the data load.

From saas~19.4.1.0.1 ``data/dashboards.xml`` puts the dashboard in the section
``spreadsheet_dashboard_purchase_oca.spreadsheet_dashboard_group_purchase``,
which only exists once spreadsheet_dashboard_purchase_oca itself is on
saas~19.4.1.0.1. ``-u spreadsheet_dashboard_purchase_stock_oca`` alone does not
upgrade that (already installed) dependency, so the XML load would abort the
whole upgrade with "External ID not found".

When the section is missing, create it under that module's external ID with
the same values as its data file; the next update of
spreadsheet_dashboard_purchase_oca simply finds and updates it. Idempotent
(does nothing once the external ID exists) and guarded: a failure is only
logged.
"""

import logging

from odoo.api import SUPERUSER_ID, Environment

_logger = logging.getLogger(__name__)

MODULE = "spreadsheet_dashboard_purchase_stock_oca"
GROUP_MODULE = "spreadsheet_dashboard_purchase_oca"
GROUP_NAME = "spreadsheet_dashboard_group_purchase"


def _ensure_purchase_section(env):
    if env.ref(f"{GROUP_MODULE}.{GROUP_NAME}", raise_if_not_found=False):
        return
    group = env["spreadsheet.dashboard.group"].create(
        {"name": "Purchases", "sequence": 200}
    )
    env["ir.model.data"].create(
        {
            "module": GROUP_MODULE,
            "name": GROUP_NAME,
            "model": group._name,
            "res_id": group.id,
            "noupdate": False,
        }
    )
    _logger.info(
        "%s: created the 'Purchases' dashboard section (%s.%s) ahead of %s. "
        "Update %s as well to get its translations and the restyled Vendors "
        "dashboard.",
        MODULE,
        GROUP_MODULE,
        GROUP_NAME,
        GROUP_MODULE,
        GROUP_MODULE,
    )


def migrate(cr, version):
    if not version:
        return
    try:
        with cr.savepoint():
            _ensure_purchase_section(Environment(cr, SUPERUSER_ID, {}))
    except Exception:  # noqa: BLE001 - a migration must never abort the upgrade
        _logger.warning(
            "%s: could not create the 'Purchases' dashboard section. The update "
            "will stop on 'External ID not found: %s.%s'. Fix: update %s first "
            "(or together with this module).",
            MODULE,
            GROUP_MODULE,
            GROUP_NAME,
            GROUP_MODULE,
            exc_info=True,
        )
