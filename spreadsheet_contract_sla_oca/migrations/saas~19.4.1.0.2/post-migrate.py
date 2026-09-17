# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Repair the contract expiry email template on existing databases.

The template lives in a ``noupdate="1"`` data file, so the fixed XML is not
re-applied by ``-u``. Up to 1.0.1 the template

* used ``{{ object.x }}`` in ``body_html``. That field is rendered with QWeb,
  which only interpolates ``{{ }}`` inside ``t-attf-*`` attributes, so users
  received the raw placeholders;
* addressed the responsible user through ``email_to``. saas-19.4 ignores
  ``email_to`` while ``use_default_to`` is set (the default), so the internal
  reminder went to the contract partner (customer/vendor) instead;
* had no ``email_from``.

Idempotent: every change is guarded by a check of the current value, so a
second run, or a template an administrator already fixed, is left alone. Never
raises: a failure is logged with the manual fix and the upgrade continues.
"""

import logging
import re
from pathlib import Path

from lxml import etree

from odoo.api import SUPERUSER_ID, Environment

_logger = logging.getLogger(__name__)

TEMPLATE_XMLID = "spreadsheet_contract_sla_oca.contract_expiry_email_template"
DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "mail_template.xml"
LEGACY_EMAIL_TO = "{{ object.responsible_id.email_formatted }}"
_ATTRIBUTE_RE = re.compile(r"""\s[\w:.@-]+\s*=\s*("[^"]*"|'[^']*')""")


def has_literal_placeholders(html):
    """True when ``{{ }}`` appears outside attributes, where QWeb prints it."""
    return bool(html) and "{{" in _ATTRIBUTE_RE.sub("", html)


def _shipped_values():
    """Values of the template as shipped in the data file.

    Serialised the way ``odoo.tools.convert`` loads them, so the database ends
    up with the same content as a fresh install.
    """
    tree = etree.parse(str(DATA_FILE))
    record = tree.find(".//record[@id='contract_expiry_email_template']")
    values = {}
    for node in record.iterfind("field"):
        if node.get("type") == "html":
            values[node.get("name")] = "".join(
                etree.tostring(child, method="html", encoding="unicode")
                for child in node
            )
        elif node.get("eval") is None:
            values[node.get("name")] = node.text or ""
    return values


def _repair_template(env):
    template = env.ref(TEMPLATE_XMLID, raise_if_not_found=False)
    if not template:
        # Deleted by an administrator: the XML loader recreates it from the
        # fixed data file, nothing to repair.
        return
    template = template.with_context(lang="en_US")
    shipped = _shipped_values()
    vals = {}

    if not template.email_from:
        vals["email_from"] = shipped["email_from"]

    email_to = (template.email_to or "").strip()
    if (
        template.use_default_to
        and not template.partner_to
        and email_to in ("", LEGACY_EMAIL_TO)
    ):
        vals.update(
            use_default_to=False,
            partner_to=shipped["partner_to"],
            email_to=False,
        )
    if not template.lang:
        vals["lang"] = shipped["lang"]

    env.cr.execute("SELECT body_html FROM mail_template WHERE id = %s", [template.id])
    stored = env.cr.fetchone()[0] or {}
    broken_langs = sorted(
        lang for lang, html in stored.items() if has_literal_placeholders(html)
    )
    if "en_US" in broken_langs:
        vals["body_html"] = shipped["body_html"]

    if vals:
        # write() re-renders the template on an existing contract
        # (_check_can_be_rendered), so a broken body cannot slip through.
        template.write(vals)
        _logger.info(
            "Contract expiry email template repaired (fields: %s).",
            ", ".join(sorted(vals)),
        )

    # Other languages still holding the old body: drop them so they fall back
    # to the fixed English body until the module .po files (loaded right after
    # this script) provide the translation.
    other_langs = [lang for lang in broken_langs if lang != "en_US"]
    if other_langs:
        template.flush_recordset(["body_html"])
        env.cr.execute(
            "UPDATE mail_template SET body_html = body_html - %s::text[] WHERE id = %s",
            [other_langs, template.id],
        )
        template.invalidate_recordset(["body_html"])
        _logger.info(
            "Contract expiry email template: dropped outdated body translations "
            "for %s.",
            ", ".join(other_langs),
        )


def migrate(cr, version):
    if not version:
        return
    env = Environment(cr, SUPERUSER_ID, {})
    try:
        with cr.savepoint():
            _repair_template(env)
    except Exception:
        _logger.exception(
            "Could not repair the 'Contract Expiry Reminder' email template; the "
            "upgrade continues. Reminder emails may still show raw {{ }} "
            "placeholders or reach the contract partner. Fix it by hand in "
            "Settings > Technical > Email Templates: replace each {{ object.x }} "
            "in the body by <t t-out=\"object.x\"/>, untick 'Default Recipients' "
            "and set 'To (Partners)' to {{ object.responsible_id.partner_id.id }}."
        )
