# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import html
import logging
import re

from lxml import etree

from odoo.api import SUPERUSER_ID, Environment
from odoo.tools.misc import file_path

_logger = logging.getLogger(__name__)

MODULE = "spreadsheet_email_report_oca"
TEMPLATE_XMLID = f"{MODULE}.spreadsheet_email_report_template"
TEMPLATE_RECORD_ID = "spreadsheet_email_report_template"
TEMPLATE_FILE = f"{MODULE}/data/mail_template.xml"

# The pre-1.1.2 default body wrote {{ ... }} in QWeb text nodes (rendered
# literally). These markers identify an untouched copy of that default.
OLD_DEFAULT_MARKERS = (
    "Please find attached the scheduled report",
    "{{ object.name }}",
)
_TAG_SPLIT = re.compile(r"(<[^>]*>)")
_INLINE_EXPR = re.compile(r"\{\{\s*(.+?)\s*\}\}", re.S)


def _has_text_placeholder(body):
    """True when a {{ }} placeholder sits in a text node (not in a tag)."""
    parts = _TAG_SPLIT.split(body or "")
    return any("{{" in part for part in parts[::2])


def _t_out(match):
    expression = html.escape(html.unescape(match.group(1)), quote=True)
    return f'<t t-out="{expression}"/>'


def _convert_text_placeholders(body):
    """Rewrite {{ expr }} in text nodes as <t t-out="expr"/>.

    Used for customised bodies, so an admin's own wording is kept while the
    placeholders start rendering. Attributes (e.g. t-attf-href) are untouched,
    because {{ }} is valid there.
    """
    parts = _TAG_SPLIT.split(body)
    for index in range(0, len(parts), 2):
        if "{{" in parts[index]:
            parts[index] = _INLINE_EXPR.sub(_t_out, parts[index])
    return "".join(parts)


def _read_xml_template_values():
    """Read body_html and email_from exactly as the XML loader would build them."""
    tree = etree.parse(file_path(TEMPLATE_FILE))
    record = tree.xpath(f"//record[@id='{TEMPLATE_RECORD_ID}']")[0]
    body_node = record.xpath("field[@name='body_html']")[0]
    # Same serialisation as odoo.tools.convert._eval_xml for type="html".
    body = "".join(
        etree.tostring(child, method="html", encoding="unicode") for child in body_node
    )
    email_from = (record.xpath("field[@name='email_from']")[0].text or "").strip()
    return body, email_from


def _backfill_owner(cr):
    # owner_id is new: the ORM filled existing rows with the upgrade user
    # (superuser). The person who created the schedule is the right owner:
    # sends are now gated on the owner's read access to the spreadsheet, so a
    # report created on a spreadsheet its creator cannot read stops leaking.
    cr.execute(
        """
        UPDATE spreadsheet_email_report r
           SET owner_id = r.create_uid
          FROM res_users u
         WHERE u.id = r.create_uid
           AND (r.owner_id IS NULL OR r.owner_id = %s)
           AND r.create_uid IS DISTINCT FROM r.owner_id
        """,
        (SUPERUSER_ID,),
    )
    if cr.rowcount:
        _logger.info(
            "%s: set the owner of %s scheduled email report(s) to their creator.",
            MODULE,
            cr.rowcount,
        )


def _fix_interval(cr):
    # interval_number <= 0 made the report resend on every hourly cron run.
    cr.execute(
        "UPDATE spreadsheet_email_report SET interval_number = 1 "
        "WHERE interval_number IS NULL OR interval_number < 1"
    )
    if cr.rowcount:
        _logger.warning(
            "%s: %s scheduled email report(s) had an interval below 1 (resent every "
            "hour); set to 1. Review their interval in Spreadsheet > Configuration "
            "> Email Reports.",
            MODULE,
            cr.rowcount,
        )


def _fix_template(env):
    template = env.ref(TEMPLATE_XMLID, raise_if_not_found=False)
    if not template:
        return
    new_body, new_email_from = _read_xml_template_values()

    env.cr.execute("SELECT body_html FROM mail_template WHERE id = %s", (template.id,))
    row = env.cr.fetchone()
    bodies = (row and row[0]) or {}
    active_langs = {code for code, _name in env["res.lang"].get_installed()}
    for lang, body in bodies.items():
        if not body or lang.startswith("_") or not _has_text_placeholder(body):
            continue
        is_old_default = all(marker in body for marker in OLD_DEFAULT_MARKERS)
        if lang != "en_US" and is_old_default:
            # An untranslated English copy of the broken default: drop it so
            # the fixed .po translation (loaded right after this script) or
            # the en_US fallback is used instead.
            env.cr.execute(
                "UPDATE mail_template SET body_html = body_html - %s WHERE id = %s",
                (lang, template.id),
            )
            template.invalidate_recordset(["body_html"])
            continue
        value = new_body if is_old_default else _convert_text_placeholders(body)
        if lang != "en_US" and lang not in active_langs:
            continue
        template.with_context(lang=lang).write({"body_html": value})
    if not template.email_from and new_email_from:
        template.write({"email_from": new_email_from})


def migrate(cr, version):
    """Bring databases installed before saas~19.4.1.1.2 in line.

    * owner_id: set to the report creator (new access model: users only see
      their own reports and every send runs with the owner's rights);
    * interval_number: values below 1 (resend every hour) become 1;
    * mail template (noupdate): body placeholders rendered literally are
      converted to QWeb t-out, and an explicit email_from is set when empty.

    Idempotent, and never blocks the upgrade: each step runs in its own
    savepoint and failures are only logged with the manual fix.
    """
    if not version:
        return
    env = Environment(cr, SUPERUSER_ID, {})
    steps = (
        ("owner backfill", lambda: _backfill_owner(cr)),
        ("interval normalisation", lambda: _fix_interval(cr)),
        ("mail template body/sender", lambda: _fix_template(env)),
    )
    for label, step in steps:
        try:
            with cr.savepoint():
                step()
        except Exception:
            _logger.warning(
                "%s: migration step '%s' failed and was skipped. Fix it manually: "
                "owners in Spreadsheet > Configuration > Email Reports, the mail "
                "template in Settings > Technical > Email Templates "
                "('Spreadsheet Scheduled Report').",
                MODULE,
                label,
                exc_info=True,
            )
