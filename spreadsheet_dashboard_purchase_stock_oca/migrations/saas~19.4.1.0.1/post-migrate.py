# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Bring the "Purchase" dashboard of older versions in line with OCA 19.0.

saas~19.4.1.0.1 takes the OCA 19.0 dashboard: it is renamed "Purchase
Receipts", moves from the Logistics section to the "Purchases" section of
spreadsheet_dashboard_purchase_oca (sequence 300), declares stock.picking as
its main data model and ships a new workbook (late receipts list, supplier
service level and on-time delivery KPIs).

``data/dashboards.xml`` is not ``noupdate``, so ``-u`` already writes all of
that. Two things it cannot do, handled here:

* translations: ``-u`` only rewrites the ``en_US`` key of the translatable
  ``name``. The other languages keep the translation of the OLD name
  ("Inkoop", "Einkauf", "Satınalma"...) because the ``.po`` import that runs
  right after this script never overwrites an existing key. Every language key
  still holding a translation this module shipped for "Purchase" is dropped,
  so that import fills in the translation of "Purchase Receipts".
* records whose ``ir.model.data`` row was flagged ``noupdate`` (for instance
  to edit the dashboard with spreadsheet_dashboard_oca): the XML load skips
  them. Each value is only moved forward while it still holds what an older
  version shipped (old name, Logistics section, sequence 100, a workbook
  byte-identical to a shipped one and without collaborative revisions);
  anything a user changed is kept and logged.

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
from odoo.tools import SQL, file_open

_logger = logging.getLogger(__name__)

MODULE = "spreadsheet_dashboard_purchase_stock_oca"
DASHBOARD_XMLID = f"{MODULE}.spreadsheet_dashboard_purchase"
DATA_FILE = f"{MODULE}/data/files/purchase_dashboard.json"

NEW_NAME = "Purchase Receipts"
OLD_NAMES = {"Purchase"}
# Every translation of "Purchase" this module ever shipped in its .po files
# (OCA 17.0, 18.0, 19.0 and this fork). Values outside this set were typed by
# a user and are kept.
OLD_NAME_TRANSLATIONS = {
    "Achat",
    "Achiziție",
    "Acquisti",
    "Acquisto",
    "Beszerzés",
    "Compra",
    "Compras",
    "Compres",
    "Einkauf",
    "Indkøb",
    "Inkoop",
    "Innkjøp",
    "Inköp",
    "Kupovina",
    "Mua hàng",
    "Nabava",
    "Nákup",
    "Ost",
    "Ostot",
    "Pembelian",
    "Pirkimas",
    "Pirkšana",
    "Satın alın",
    "Satınalma",
    "Zakup",
    "Αγορά",
    "Купівля",
    "Покупка",
    "רכש",
    "الشراء",
    "خرید",
    "สั่งซื้อ",
    "매입",
    "購買",
    "采购",
    "採購",
}

NEW_GROUP_XMLID = (
    "spreadsheet_dashboard_purchase_oca.spreadsheet_dashboard_group_purchase"
)
OLD_GROUP_XMLID = "spreadsheet_dashboard.spreadsheet_dashboard_group_logistics"
NEW_SEQUENCE = 300
OLD_SEQUENCES = {100}
MAIN_MODEL_XMLID = "stock.model_stock_picking"

# sha256 of the canonical JSON (sorted keys, compact separators) of every
# workbook an older version of this module shipped.
SHIPPED_WORKBOOK_SHA256 = {
    # OCA 17.0 / 18.0
    "bc136d01e59b6b3cfa0e281c155e0486270c5c05d6ce4520afe437dabe7c2d29",
    # this fork up to saas~19.4.1.0.0 (scheduled_date instead of date)
    "ad82c07009856e319d6af1b38d35cf6d467d83a8fb8507686a2aa6ce889099ed",
    # intermediate OCA 19.0 exports
    "f19b44a46ba5a6f757e4ed97c521e65e00a0d9413f8b03528efb0e3a7b1c74a8",
    "65c4bd464eccd416bdba0be62125fdebb060755de73eb9ce0aac4110501667b0",
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


def _sync_name(env, dashboard):
    dashboard.flush_recordset(["name"])
    env.cr.execute(
        SQL("SELECT name FROM spreadsheet_dashboard WHERE id = %s", dashboard.id)
    )
    row = env.cr.fetchone()
    name = row and row[0]
    if not isinstance(name, dict):
        return
    new_name = dict(name)
    if new_name.get("en_US") in OLD_NAMES:
        new_name["en_US"] = NEW_NAME
    if new_name.get("en_US") != NEW_NAME:
        _logger.info(
            "%s: dashboard %s was renamed to %r, its name and translations are kept.",
            MODULE,
            dashboard.id,
            new_name.get("en_US"),
        )
        return
    for lang in list(new_name):
        if lang != "en_US" and (
            new_name[lang] in OLD_NAME_TRANSLATIONS or new_name[lang] in OLD_NAMES
        ):
            del new_name[lang]
    if new_name != name:
        env.cr.execute(
            SQL(
                "UPDATE spreadsheet_dashboard SET name = %s::jsonb WHERE id = %s",
                json.dumps(new_name),
                dashboard.id,
            )
        )
        dashboard.invalidate_recordset(["name"])
        _logger.info(
            "%s: renamed dashboard %s to %r and dropped the stale translations "
            "of the old name %s.",
            MODULE,
            dashboard.id,
            NEW_NAME,
            sorted(set(name) - set(new_name)),
        )


def _sync_section(env, dashboard):
    vals = {}
    new_group = env.ref(NEW_GROUP_XMLID, raise_if_not_found=False)
    old_group = env.ref(OLD_GROUP_XMLID, raise_if_not_found=False)
    if not new_group:
        _logger.warning(
            "%s: the 'Purchases' dashboard section (%s) does not exist, the "
            "Purchase Receipts dashboard stays in its current section. Fix: "
            "update spreadsheet_dashboard_purchase_oca, then this module.",
            MODULE,
            NEW_GROUP_XMLID,
        )
    elif old_group and dashboard.dashboard_group_id == old_group:
        vals["dashboard_group_id"] = new_group.id
    if dashboard.sequence in OLD_SEQUENCES:
        vals["sequence"] = NEW_SEQUENCE
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
            "by the new Purchase Receipts workbook. Fields removed in Odoo 19 "
            "(e.g. stock.picking.date) may show #ERROR. Fix: re-apply your "
            "changes on a copy, or delete the dashboard and update this module "
            "to get the new one.",
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
            _sync_name,
            "could not update the dashboard name and its translations. Users "
            "may still see the old translated name. Fix: Dashboards > "
            "Configuration > Dashboards, open 'Purchase Receipts' and set the "
            "name in each language.",
        ),
        (
            _sync_section,
            "could not move the dashboard to the 'Purchases' section. Fix: "
            "Dashboards > Configuration > Dashboards, open 'Purchase Receipts' "
            "and set Dashboard Section = Purchases.",
        ),
        (
            _sync_workbook,
            "could not replace the dashboard workbook. It may show #ERROR. "
            "Fix: delete the dashboard and update this module to get it back.",
        ),
    )
    for step, failure_hint in steps:
        try:
            with cr.savepoint():
                step(env, dashboard)
        except Exception:  # noqa: BLE001 - a migration must never abort the upgrade
            _logger.warning("%s: %s", MODULE, failure_hint, exc_info=True)
