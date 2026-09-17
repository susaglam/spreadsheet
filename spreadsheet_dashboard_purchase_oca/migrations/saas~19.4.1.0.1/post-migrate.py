# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Bring the "Vendors" dashboard of older versions in line with OCA 19.0.

saas~19.4.1.0.1 takes the OCA 19.0 dashboard: it moves from the Logistics
section to the new "Purchases" section shipped by this module, declares
purchase.order as its main data model and ships a restyled workbook with a
"Top Products" table.

``data/dashboards.xml`` is not ``noupdate``, so ``-u`` already writes all of
that and this script finds nothing to do. It only matters for a dashboard
whose ``ir.model.data`` row was flagged ``noupdate`` (for instance to edit it
with spreadsheet_dashboard_oca), which the XML load skips. Each value is only
moved forward while it still holds what an older version shipped (Logistics
section, no main data model, a workbook byte-identical to a shipped one and
without collaborative revisions); anything a user changed is kept and logged.
The dashboard name ("Vendors") did not change, so its translations stay valid.

Idempotent (a second run finds nothing old to replace) and guarded: every step
runs in its own savepoint and a failure is only logged, never aborting the
upgrade.
"""

import base64
import hashlib
import json
import logging

from odoo.api import SUPERUSER_ID, Environment
from odoo.fields import Command
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

MODULE = "spreadsheet_dashboard_purchase_oca"
DASHBOARD_XMLID = f"{MODULE}.spreadsheet_dashboard_vendors"
DATA_FILE = f"{MODULE}/data/files/vendors_dashboard.json"

NEW_GROUP_XMLID = f"{MODULE}.spreadsheet_dashboard_group_purchase"
OLD_GROUP_XMLID = "spreadsheet_dashboard.spreadsheet_dashboard_group_logistics"
MAIN_MODEL_XMLID = "purchase.model_purchase_order"

# sha256 of the canonical JSON (sorted keys, compact separators) of every
# workbook an older version of this module shipped (OCA 17.0 / 18.0 and this
# fork up to saas~19.4.1.0.0).
SHIPPED_WORKBOOK_SHA256 = {
    "ded860e8f1c26f30d9e16f6e1182c6afbd198a85aca67f2a47300c5d87de473e",
}


def _workbook_digest(raw):
    data = json.loads(raw)
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stored_workbook(dashboard):
    value = dashboard.spreadsheet_binary_data
    if not value:
        return b""
    if hasattr(value, "content"):  # saas-19.4 BinaryValue
        return value.content
    return base64.b64decode(value)  # older API: base64 str/bytes


def _sync_section(env, dashboard):
    vals = {}
    new_group = env.ref(NEW_GROUP_XMLID, raise_if_not_found=False)
    old_group = env.ref(OLD_GROUP_XMLID, raise_if_not_found=False)
    if new_group and old_group and dashboard.dashboard_group_id == old_group:
        vals["dashboard_group_id"] = new_group.id
    main_model = env.ref(MAIN_MODEL_XMLID, raise_if_not_found=False)
    if main_model and not dashboard.main_data_model_ids:
        vals["main_data_model_ids"] = [Command.link(main_model.id)]
    if vals:
        dashboard.write(vals)
        _logger.info(
            "%s: updated %s on dashboard %s.", MODULE, sorted(vals), dashboard.id
        )


def _sync_workbook(env, dashboard):
    with file_open(DATA_FILE, "rb") as fh:
        shipped = fh.read()
    stored = _stored_workbook(dashboard)
    try:
        stored_digest = _workbook_digest(stored) if stored else None
    except ValueError:  # unreadable workbook: nothing worth keeping
        stored_digest = None
    if stored_digest == _workbook_digest(shipped):
        return  # the XML load already wrote the new workbook
    has_revisions = False
    if "spreadsheet.oca.revision" in env:
        has_revisions = bool(
            env["spreadsheet.oca.revision"].search_count(
                [("model", "=", dashboard._name), ("res_id", "=", dashboard.id)],
                limit=1,
            )
        )
    customised = stored_digest not in SHIPPED_WORKBOOK_SHA256 or has_revisions
    if stored_digest and customised:
        _logger.warning(
            "%s: dashboard %s holds a customised workbook, it was NOT replaced "
            "by the new Vendors workbook. Fix: re-apply your changes on a copy, "
            "or delete the dashboard and update this module to get the new one.",
            MODULE,
            dashboard.id,
        )
        return
    dashboard.write({"spreadsheet_binary_data": base64.b64encode(shipped).decode()})
    _logger.info("%s: replaced the workbook of dashboard %s.", MODULE, dashboard.id)


def migrate(cr, version):
    if not version:
        return
    env = Environment(cr, SUPERUSER_ID, {})
    dashboard = env.ref(DASHBOARD_XMLID, raise_if_not_found=False)
    if not dashboard:
        _logger.info(
            "%s: dashboard %s was deleted, nothing to migrate.",
            MODULE,
            DASHBOARD_XMLID,
        )
        return
    steps = (
        (
            _sync_section,
            "could not move the Vendors dashboard to the 'Purchases' section. "
            "Fix: Dashboards > Configuration > Dashboards, open 'Vendors' and "
            "set Dashboard Section = Purchases.",
        ),
        (
            _sync_workbook,
            "could not replace the Vendors dashboard workbook. Fix: delete the "
            "dashboard and update this module to get it back.",
        ),
    )
    for step, failure_hint in steps:
        try:
            with cr.savepoint():
                step(env, dashboard)
        except Exception:  # noqa: BLE001 - a migration must never abort the upgrade
            _logger.warning("%s: %s", MODULE, failure_hint, exc_info=True)
