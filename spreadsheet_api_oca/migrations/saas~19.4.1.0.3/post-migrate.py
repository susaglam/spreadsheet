# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Store API tokens as SHA-256 hashes instead of plaintext.

Up to saas~19.4.1.0.2 the secret lived in the plaintext column ``token``.
From 1.0.3 only ``token_hash`` (sha256 hex) and a short ``token_hint`` are
kept. This script converts every existing secret, so integrations keep
working with the token they already have, then drops the plaintext column.

It also archives tokens bound to the superuser or to portal/public users:
the API now refuses them anyway, and archiving makes that visible.

Finally it deletes webhook events that are still waiting for delivery but
would leak: before 1.0.3 events were queued for every spreadsheet, whether
the token user could read it or not, and their payload carries the
spreadsheet name. Only events the token user may still see are kept.

Idempotent (a second run finds no ``token`` column, no offending token and
no leaking event) and guarded: any failure is logged and never aborts the
upgrade.
"""

import hashlib
import logging

from odoo import api
from odoo.api import SUPERUSER_ID
from odoo.tools import SQL, sql
from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)

TABLE = "spreadsheet_api_token"
HINT_LENGTH = 6


def _hash_legacy_tokens(cr):
    if not sql.table_exists(cr, TABLE):
        return
    if not sql.column_exists(cr, TABLE, "token"):
        return  # already migrated
    if not sql.column_exists(cr, TABLE, "token_hash") or not sql.column_exists(
        cr, TABLE, "token_hint"
    ):
        _logger.error(
            "spreadsheet_api_oca: columns token_hash/token_hint are missing, "
            "legacy API tokens were NOT converted. Upgrade the module again."
        )
        return
    cr.execute(
        SQL(
            """
            SELECT id, token FROM %s
             WHERE token IS NOT NULL AND token <> '' AND token_hash IS NULL
            """,
            SQL.identifier(TABLE),
        )
    )
    rows = cr.fetchall()
    for token_id, token in rows:
        cr.execute(
            SQL(
                """
                UPDATE %s
                   SET token_hash = %s,
                       token_hint = COALESCE(token_hint, %s)
                 WHERE id = %s
                """,
                SQL.identifier(TABLE),
                hashlib.sha256(token.encode()).hexdigest(),
                token[:HINT_LENGTH] + "…",
                token_id,
            )
        )
    # Remove the plaintext secrets for good (also drops the old unique
    # constraint on the column).
    cr.execute(SQL("ALTER TABLE %s DROP COLUMN token CASCADE", SQL.identifier(TABLE)))
    _logger.info(
        "spreadsheet_api_oca: %s API token(s) converted to hashed storage; "
        "plaintext column dropped.",
        len(rows),
    )


def _archive_forbidden_user_tokens(env):
    Token = env["spreadsheet.api.token"].with_context(active_test=False)
    tokens = Token.search([("active", "=", True)])
    forbidden = tokens.filtered(
        lambda t: t.user_id.id == SUPERUSER_ID or t.user_id.share
    )
    if forbidden:
        # active is not a constrained field: no validation is re-run here.
        forbidden.write({"active": False})
        _logger.warning(
            "spreadsheet_api_oca: archived API token(s) %s because they ran as "
            "the superuser or a portal/public user, which the API no longer "
            "allows. Assign an internal user and reactivate them if needed.",
            forbidden.ids,
        )


def _purge_leaking_pending_events(env):
    Event = env["spreadsheet.api.webhook.event"]
    Token = env["spreadsheet.api.token"]
    retry_max = (
        env["ir.config_parameter"].sudo().get_int("spreadsheet_api.webhook_retry_max")
        or 3
    )
    pending = Event.search([("delivered", "=", False), ("retry_count", "<", retry_max)])
    leaking = Event.browse()
    for event in pending:
        user = event.token_id.user_id
        sheet = event.spreadsheet_id
        if (
            not Token._is_allowed_api_user(user)
            or not sheet.exists()
            or (
                event.token_id.spreadsheet_ids
                and sheet not in event.token_id.spreadsheet_ids
            )
            or not sheet._is_readable_by_api_user(user)
        ):
            leaking |= event
    if leaking:
        count = len(leaking)
        leaking.unlink()
        _logger.warning(
            "spreadsheet_api_oca: deleted %s undelivered webhook event(s) about "
            "spreadsheets their token user cannot read (or whose spreadsheet "
            "no longer exists), so their names are not sent to the receiver.",
            count,
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
    try:
        with cr.savepoint(flush=False):
            _hash_legacy_tokens(cr)
    except Exception:
        _logger.exception(
            "spreadsheet_api_oca: converting API tokens to hashes failed; "
            "existing tokens may need to be regenerated."
        )
    try:
        # Flushing savepoint: on failure it also restores the ORM cache.
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            _archive_forbidden_user_tokens(env)
            env.flush_all()
    except Exception:
        _logger.exception(
            "spreadsheet_api_oca: archiving API tokens of forbidden users "
            "failed; the API still rejects them at authentication time."
        )
    try:
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            _purge_leaking_pending_events(env)
            env.flush_all()
    except Exception:
        _logger.exception(
            "spreadsheet_api_oca: checking pending webhook events failed; "
            "events queued before the upgrade may still be delivered. Review "
            "Spreadsheets > Configuration > API Tokens > Webhook Delivery Log."
        )
    try:
        with cr.savepoint():
            _drop_temporary_view_visibility_default(cr)
    except Exception:
        _logger.warning(
            "spreadsheet_api_oca: could not remove the temporary default on "
            "ir_ui_view.visibility; it is harmless (same value as website's "
            "own default) and can be dropped manually.",
            exc_info=True,
        )
