# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import contextlib
import logging

from psycopg2.extras import Json

from odoo.api import SUPERUSER_ID, Environment
from odoo.tools.convert import convert_file

_logger = logging.getLogger(__name__)

MODULE = "spreadsheet_kpi_alert_oca"
TEMPLATE_XMLID = "kpi_alert_email_template"
TEMPLATE_FILE = "data/mail_template.xml"


def _template_row(cr):
    cr.execute(
        """
        SELECT t.id, t.body_html, t.email_to, t.use_default_to
          FROM mail_template t
          JOIN ir_model_data d
            ON d.res_id = t.id AND d.model = 'mail.template'
         WHERE d.module = %s AND d.name = %s
        """,
        (MODULE, TEMPLATE_XMLID),
    )
    return cr.fetchone()


def _is_broken(body_html, email_to, use_default_to):
    """The template shipped up to saas~19.4.1.0.2 could never deliver: its
    QWeb body printed {{ ... }} literally, its email_to used a Jinja filter
    (NameError on render) and use_default_to=True ignored email_to anyway."""
    bodies = (body_html or {}).values() if isinstance(body_html, dict) else ()
    return (
        any("{{" in (body or "") for body in bodies)
        or "| join(" in (email_to or "")
        or bool(use_default_to and "notify_user_ids" in (email_to or ""))
    )


def migrate(cr, version):
    """Repair the KPI alert email template on existing databases.

    data/mail_template.xml is noupdate="1", so `-u` never rewrites the
    installed template. When the database still holds the broken shipped
    version, reload the record from the XML through the regular data loader
    (mode 'init' bypasses the noupdate gate for this one file), so the stored
    body is byte-identical to a fresh install and its .po translations match.
    Translations of the old body that still contain "{{" are dropped; the
    translation update that runs right after this script refills them from
    the module's .po files.

    Idempotent: a repaired or admin-customised (no longer broken) template is
    left untouched. Never blocks the upgrade: failures are logged with the
    manual fix.
    """
    if not version:
        return
    # Build the environment BEFORE the savepoint: the flushing savepoint saves
    # the transaction state on entry only when a transaction already exists, so
    # a rollback then also drops whatever the failed reload left in the cache.
    env = Environment(cr, SUPERUSER_ID, {})
    try:
        with cr.savepoint():
            row = _template_row(cr)
            if not row or not _is_broken(row[1], row[2], row[3]):
                return
            template_id = row[0]
            convert_file(env, MODULE, TEMPLATE_FILE, {}, mode="init", noupdate=True)
            env.flush_all()

            cr.execute(
                "SELECT body_html FROM mail_template WHERE id = %s", (template_id,)
            )
            body = cr.fetchone()[0] or {}
            cleaned = {
                lang: value
                for lang, value in body.items()
                if lang == "en_US" or "{{" not in (value or "")
            }
            if cleaned != body:
                cr.execute(
                    "UPDATE mail_template SET body_html = %s WHERE id = %s",
                    (Json(cleaned), template_id),
                )
            env.invalidate_all()
            _logger.info(
                "%s: repaired email template %s.%s (QWeb body, recipients, sender).",
                MODULE,
                MODULE,
                TEMPLATE_XMLID,
            )
    except Exception:  # noqa: BLE001 - a migration must never abort the upgrade
        # The database was rolled back to the savepoint; make sure no template
        # value cached during the failed reload is flushed later in the upgrade.
        with contextlib.suppress(Exception):
            env.invalidate_all(flush=False)
        _logger.warning(
            "%s: could not repair the KPI alert email template; alerts with "
            "'Send Email' keep failing to email (the Discuss notification still "
            "works). Fix: in Settings > Technical > Email Templates, open "
            "'Spreadsheet KPI Alert', untick 'Default Recipients', set 'To' to "
            "{{ ','.join(object.notify_user_ids.filtered('email')"
            ".mapped('email_formatted')) }} and replace every {{ ... }} in the "
            'body with <t t-out="..."/>.',
            MODULE,
            exc_info=True,
        )
