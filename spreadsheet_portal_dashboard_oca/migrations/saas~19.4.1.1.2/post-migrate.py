# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo.api import SUPERUSER_ID, Environment

_logger = logging.getLogger(__name__)

MODULE = "spreadsheet_portal_dashboard_oca"
OLD_CARD_VIEW_KEY = f"{MODULE}.portal_my_home_dashboard_entry"
OLD_PORTAL_GRANT_XMLID = f"{MODULE}.rule_portal_dashboard_portal_read"


def _archive_old_home_card(env):
    """Retire the pre-19.4 /my home card template.

    Up to saas~19.4.1.1.1 the "Dashboards" card was a QWeb inherit of
    portal.portal_my_home calling portal.portal_docs_entry with t-set values.
    In saas-19.4 that template renders a portal.entry record, so the old
    inherit showed ANOTHER card twice and never its own. The card is now the
    portal.entry record data/portal_entry_data.xml.

    The xmlid-bound view is removed automatically at the end of the upgrade
    (it is no longer in the module data), but website-specific copies created
    by the website editor share its key and would survive. Archive every view
    with that key so none of them keeps rendering the broken card.
    """
    views = (
        env["ir.ui.view"]
        .with_context(active_test=False)
        .search([("key", "=", OLD_CARD_VIEW_KEY), ("active", "=", True)])
    )
    if views:
        views.write({"active": False})
        _logger.info(
            "%s: archived %s obsolete portal home card view(s).",
            MODULE,
            len(views),
        )


def _remove_portal_orm_grant(env):
    """Drop the portal users' ORM read grant on spreadsheet.portal.dashboard.

    It exposed partner_ids (other dealers), all_portal_users and descriptions
    of assignments through /web/dataset/call_kw, archived ones included.
    Every portal code path reads assignments with sudo, so nothing needs it.
    The record left security/security.xml, so the end-of-upgrade cleanup
    normally deletes it; this removes it too when its ir.model.data row was
    flagged noupdate (the cleanup skips those).
    """
    grant = env.ref(OLD_PORTAL_GRANT_XMLID, raise_if_not_found=False)
    if grant:
        grant.unlink()
        _logger.info("%s: removed the portal ORM read grant %s.", MODULE, grant)


def migrate(cr, version):
    """Idempotent: each step only touches what is still there, runs in its
    own savepoint and never aborts the upgrade."""
    if not version:
        return
    env = Environment(cr, SUPERUSER_ID, {})
    steps = (
        (
            _archive_old_home_card,
            "could not archive the obsolete portal home card view(s) with key "
            f"{OLD_CARD_VIEW_KEY}. The portal may show a duplicated card on "
            "/my. Fix: in Settings > Technical > Views, search for that key "
            "and archive the views.",
        ),
        (
            _remove_portal_orm_grant,
            f"could not remove the portal ORM read grant {OLD_PORTAL_GRANT_XMLID}. "
            "Portal users may still read assignment details through RPC. Fix: "
            "in Settings > Technical > Security > Access, search for "
            "'Portal Dashboard: Portal user read access' and delete it.",
        ),
    )
    for step, failure_hint in steps:
        try:
            with cr.savepoint():
                step(env)
        except Exception:  # noqa: BLE001 - a migration must never abort the upgrade
            _logger.warning("%s: %s", MODULE, failure_hint, exc_info=True)
