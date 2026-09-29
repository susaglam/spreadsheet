# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""saas~19.4.1.0.1: security repairs for databases installed before this fix.

``security/security.xml`` and ``security/ir.access.csv`` are NOT noupdate, so
a regular ``-u`` already reloads them before this script runs. This script is
the idempotent safety net: it verifies the result in the database and repairs
it when the reload did not reach a record.

1. ``base.user_root`` and ``base.user_admin`` are members of
   ``spreadsheet_oca.group_manager`` (an earlier port dropped
   ``<field name="user_ids">``, believing the field was removed; it was renamed).
2. The group-sharing ``ir.access`` domains test ``user.all_group_ids``
   (explicit + implied groups) instead of ``user.group_ids`` (explicit only).
3. ``spreadsheet.oca.revision`` (the cell contents of every collaborative
   edit) is no longer granted to ``base.group_user``. Grants that do not come
   from this module (e.g. an administrator's customized copy) are reported,
   never silently deleted.
4. Revisions left behind by spreadsheets deleted before ``unlink()`` started
   cleaning them up are removed. Only models loaded in the registry at this
   point are checked (a model from a module that loads later, e.g.
   ``spreadsheet.dashboard``, cannot be verified yet and is left alone): a
   revision is deleted only when its model's table provably has no row with
   its ``res_id``.

Every step runs in its own savepoint: a failure logs a warning and never
aborts the upgrade.
"""

import logging

from odoo.api import SUPERUSER_ID, Environment
from odoo.fields import Command
from odoo.tools import SQL
from odoo.tools.sql import column_exists, table_exists

_logger = logging.getLogger(__name__)

GROUP_SHARING_ACCESSES = (
    "spreadsheet_oca.spreadsheet_contributor_rule",
    "spreadsheet_oca.spreadsheet_reader_rule",
    "spreadsheet_oca.spreadsheet_import_mode_rule",
)
OLD_GROUP_EXPR = "user.group_ids.ids"
NEW_GROUP_EXPR = "user.all_group_ids.ids"


def _ensure_admins_in_manager_group(env):
    group = env.ref("spreadsheet_oca.group_manager", raise_if_not_found=False)
    if not group:
        _logger.warning(
            "spreadsheet_oca: group_manager not found; administrators were not "
            "added to it. Add them in Settings > Users > Access Rights."
        )
        return
    members = group.with_context(active_test=False).user_ids
    to_link = []
    for xmlid in ("base.user_root", "base.user_admin"):
        user = env.ref(xmlid, raise_if_not_found=False)
        if user and user not in members:
            to_link.append(Command.link(user.id))
    if to_link:
        group.write({"user_ids": to_link})
        _logger.info(
            "spreadsheet_oca: added %s administrator user(s) to Spreadsheets / Manager",
            len(to_link),
        )


def _fix_group_sharing_domains(env):
    for xmlid in GROUP_SHARING_ACCESSES:
        access = env.ref(xmlid, raise_if_not_found=False)
        if not access or not access.domain or OLD_GROUP_EXPR not in access.domain:
            continue
        access.domain = access.domain.replace(OLD_GROUP_EXPR, NEW_GROUP_EXPR)
        _logger.info(
            "spreadsheet_oca: %s now matches implied groups (all_group_ids)", xmlid
        )


def _restrict_revision_access(env):
    access_model = env["ir.access"].with_context(active_test=False)
    own = env.ref(
        "spreadsheet_oca.access_spreadsheet_oca_revision", raise_if_not_found=False
    )
    system = env.ref("base.group_system", raise_if_not_found=False)
    if own and system and own.group_id != system:
        own.group_id = system
        _logger.info(
            "spreadsheet_oca: spreadsheet.oca.revision access restricted to "
            "Settings administrators"
        )
    employee = env.ref("base.group_user", raise_if_not_found=False)
    if not employee:
        return
    leftovers = access_model.search(
        [
            ("model_id.model", "=", "spreadsheet.oca.revision"),
            ("group_id", "=", employee.id),
            ("active", "=", True),
        ]
    )
    if leftovers:
        _logger.warning(
            "spreadsheet_oca: ir.access record(s) %s still grant every internal "
            "user access to spreadsheet revisions (the cell contents of all "
            "spreadsheets). They are not managed by this module, so they were "
            "kept. Review them in Settings > Technical > Security > Access.",
            leftovers.ids,
        )


def _delete_orphan_revisions(env):
    env.flush_all()  # the raw SQL below must see pending ORM writes
    cr = env.cr
    cr.execute(SQL("SELECT DISTINCT model FROM spreadsheet_oca_revision"))
    deleted = 0
    unverified = []
    for (model_name,) in cr.fetchall():
        model = env[model_name] if model_name and model_name in env else None
        if (
            model is None
            or model._abstract
            or not model._auto
            or not table_exists(cr, model._table)
        ):
            unverified.append(model_name)
            continue
        cr.execute(
            SQL(
                """
                DELETE FROM spreadsheet_oca_revision rev
                 WHERE rev.model = %s
                   AND NOT EXISTS (SELECT 1 FROM %s rec WHERE rec.id = rev.res_id)
                """,
                model_name,
                SQL.identifier(model._table),
            )
        )
        deleted += cr.rowcount
    if deleted:
        env["spreadsheet.oca.revision"].invalidate_model()
        _logger.info(
            "spreadsheet_oca: deleted %s orphan spreadsheet revision(s) whose "
            "spreadsheet no longer exists",
            deleted,
        )
    if unverified:
        _logger.info(
            "spreadsheet_oca: orphan revisions of model(s) %s were not checked "
            "because the model is not loaded yet; they stay readable only by "
            "Settings administrators.",
            unverified,
        )


def _drop_temporary_view_visibility_default(cr):
    """Undo pre-migrate: remove the temporary ``DEFAULT 'public'`` on
    ``ir_ui_view.visibility`` (see pre-migrate for why it was needed)."""
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
    env = Environment(cr, SUPERUSER_ID, {})
    for step in (
        _ensure_admins_in_manager_group,
        _fix_group_sharing_domains,
        _restrict_revision_access,
        _delete_orphan_revisions,
    ):
        try:
            with cr.savepoint():
                step(env)
        except Exception:
            _logger.warning(
                "spreadsheet_oca: post-migrate step %s failed; the upgrade "
                "continues. Re-run it from an odoo shell or apply the change "
                "manually.",
                step.__name__,
                exc_info=True,
            )
    try:
        with cr.savepoint():
            _drop_temporary_view_visibility_default(cr)
    except Exception:
        _logger.warning(
            "spreadsheet_oca: could not remove the temporary default on "
            "ir_ui_view.visibility; it is harmless (same value as website's "
            "own default) and can be dropped manually.",
            exc_info=True,
        )
