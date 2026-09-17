# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

# Sheets that hold the raw data behind a dashboard. They are hidden in the
# editor and must never leave the server for a portal viewer.
DATA_SHEET_NAMES = {"Data"}

# Top-level workbook keys the portal renderer reads. Everything else
# (pivots, lists, globalFilters, odoo links, data sources, revisions ...)
# describes internal models/domains and is stripped server-side.
PORTAL_WORKBOOK_KEYS = ("version", "styles", "borders")
# Per-sheet keys the portal renderer reads.
PORTAL_SHEET_KEYS = ("id", "name", "merges", "styles", "borders")

_XC_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d{1,7})$")
# A pure translation label: ``=_t("Revenue")``. The literal may not contain an
# unescaped double quote, so a formula that merely STARTS with ``_t("`` and
# ENDS with ``")`` (``=_t("a")&ODOO.LIST.HEADER(1,"field")``) does not match
# and stays masked. o-spreadsheet only knows double-quoted strings and escapes
# a quote inside them as ``\"``.
_T_LITERAL_RE = re.compile(r'^=_t\(\s*"((?:[^"\\]|\\.)*)"\s*\)$', re.DOTALL)
# Integer literals o-spreadsheet squishes (``42``, ``-7``, ``1,000``).
_INTEGER_RE = re.compile(r"^\s*[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\s*$")
# A squished number offset as o-spreadsheet writes it (``+1``, ``-2``, ``0``).
_NUMBER_OFFSET_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_SQUISH_KEYS = ("N", "S", "R")


def _xc_position(xc):
    """Return ``(col, row)`` (0-based) of an ``A1``-style reference, or None."""
    match = _XC_RE.match(xc or "")
    if not match:
        return None
    col = 0
    for letter in match[1].upper():
        col = col * 26 + (ord(letter) - 64)
    return col - 1, int(match[2]) - 1


def _cell_sort_key(key):
    position = _xc_position(str(key).split(":")[0])
    return position if position else (float("inf"), float("inf"))


def _is_squished(value):
    return isinstance(value, dict) and any(k in value for k in _SQUISH_KEYS)


def _mask_content(content):
    """Hide formula source the portal preview never displays.

    A translation label ``=_t("Revenue")`` is kept (the preview shows its
    text); any other formula becomes a bare ``=`` so the viewer still knows the
    cell is computed without receiving field names, ids or references.
    """
    if isinstance(content, str) and content.startswith("="):
        return content if _T_LITERAL_RE.match(content) else "="
    return content


def _sanitize_cells(cells):
    """Return a copy of a sheet's ``cells`` safe to send to a portal viewer.

    Supports both storage formats:

    * legacy (o-spreadsheet < 18.1.1): ``{"A1": {"content", "style", ...}}``;
    * current (saas-19.4): ``{"A1": "text"}`` where keys may be ranges
      (``"B2:B9"``) and values may be "squished" offsets (``{"N": "+1"}``)
      relative to the previous cell of the same column.

    Squished offsets are resolved in column/row order, exactly like the
    o-spreadsheet unsquisher: offsets after a formula stay masked (only the
    label strings of a ``_t`` formula are kept), offsets after an integer keep
    their number step so the preview can show the real value. Offsets after
    any other static literal (a value the preview cannot reproduce, such as a
    formatted date typed in a hand-written file) are dropped: the cell shows
    empty instead of pretending to be a calculated value.
    """
    if not isinstance(cells, dict):
        return {}
    result = {}
    mode = None  # "label" | "formula" | "number" | "text"
    for key in sorted(cells, key=_cell_sort_key):
        value = cells[key]
        if isinstance(value, dict) and not _is_squished(value):
            # Legacy cell object: keep only what the renderer reads.
            legacy = {"content": _mask_content(value.get("content") or "")}
            for attr in ("style", "border"):
                if isinstance(value.get(attr), int):
                    legacy[attr] = value[attr]
            result[key] = legacy
            continue
        if isinstance(value, str):
            if value.startswith("="):
                mode = "label" if _T_LITERAL_RE.match(value) else "formula"
            elif _INTEGER_RE.match(value):
                mode = "number"
            else:
                mode = "text"
            result[key] = _mask_content(value)
        elif _is_squished(value):
            if mode == "label":
                # "=" means "same label as the previous cell".
                strings = value.get("S")
                label = "="
                if isinstance(strings, list) and strings:
                    label = strings[0] if isinstance(strings[0], str) else "="
                result[key] = {"S": [label]}
            elif mode == "number":
                offset = value.get("N")
                if isinstance(offset, str) and _NUMBER_OFFSET_RE.match(offset):
                    result[key] = {"N": offset}
            elif mode == "formula":
                # Offset of a real formula: the viewer only needs to know the
                # cell is computed, never its references or literals.
                result[key] = "="
            # mode "text" / None: offset of a static value the preview cannot
            # format, or a malformed file. Nothing to show, drop it.
        # None / numbers / anything else: nothing displayable, drop it.
    return result


def _sanitize_figures(figures):
    """Keep only the scorecard type and title the portal preview shows."""
    result = []
    for figure in figures if isinstance(figures, list) else []:
        if not isinstance(figure, dict):
            continue
        data = figure.get("data") if isinstance(figure.get("data"), dict) else {}
        title = data.get("title")
        if isinstance(title, dict):
            title = title.get("text")
        result.append(
            {
                "id": figure.get("id"),
                "tag": figure.get("tag"),
                "data": {
                    "type": data.get("type"),
                    "title": {"text": title if isinstance(title, str) else ""},
                },
            }
        )
    return result


def _sanitize_headers(headers):
    """Keep only size / hidden flags of ``cols`` / ``rows``."""
    result = {}
    if not isinstance(headers, dict):
        return result
    for index, header in headers.items():
        if not isinstance(header, dict):
            continue
        clean = {}
        if isinstance(header.get("size"), int | float):
            clean["size"] = header["size"]
        if header.get("isHidden"):
            clean["isHidden"] = True
        if clean:
            result[index] = clean
    return result


def sanitize_spreadsheet_for_portal(raw):
    """Reduce a spreadsheet snapshot to what the portal preview renders.

    Hidden sheets, the ``Data`` sheet, pivot / list definitions (models and
    domains), global filters, revisions and formula sources are removed so a
    portal user can never read them from the JSON response.
    """
    if not isinstance(raw, dict):
        return {}
    clean = {key: raw[key] for key in PORTAL_WORKBOOK_KEYS if key in raw}
    sheets = []
    for sheet in raw.get("sheets") or []:
        if not isinstance(sheet, dict):
            continue
        if sheet.get("isVisible") is False or sheet.get("name") in DATA_SHEET_NAMES:
            continue
        clean_sheet = {key: sheet[key] for key in PORTAL_SHEET_KEYS if key in sheet}
        clean_sheet["cells"] = _sanitize_cells(sheet.get("cells"))
        clean_sheet["cols"] = _sanitize_headers(sheet.get("cols"))
        clean_sheet["rows"] = _sanitize_headers(sheet.get("rows"))
        clean_sheet["figures"] = _sanitize_figures(sheet.get("figures"))
        sheets.append(clean_sheet)
    clean["sheets"] = sheets
    return clean


class SpreadsheetPortalDashboard(models.Model):
    _name = "spreadsheet.portal.dashboard"
    _description = "Portal Dashboard Assignment"
    _order = "sequence, name"

    name = fields.Char(
        required=True,
        compute="_compute_name",
        store=True,
        readonly=False,
        precompute=True,
        help="Title portal users see on the /my/dashboards card. Defaults to "
        "the dashboard name; change it to use a friendlier label, e.g. "
        "'Your monthly sales'.",
    )
    sequence = fields.Integer(
        default=10,
        help="Display order of this dashboard in the portal list; "
        "lower numbers appear first.",
    )
    active = fields.Boolean(
        default=True,
        help="Archive the assignment to stop sharing the dashboard on the "
        "portal immediately, without losing the partner selection.",
    )
    dashboard_id = fields.Many2one(
        "spreadsheet.dashboard",
        string="Dashboard",
        required=True,
        ondelete="cascade",
        help="The internal spreadsheet dashboard whose read-only view is "
        "shared with the selected portal partners. Example: a 'Monthly "
        "Sales' dashboard shared with dealers. You can only pick dashboards "
        "you are allowed to open yourself.",
    )
    partner_ids = fields.Many2many(
        "res.partner",
        string="Portal Partners",
        help="Partners whose users can open this dashboard at /my/dashboards. "
        "Selecting a company also gives the portal users of all its contacts "
        "access; an internal employee only gets access when their own contact "
        "is listed. When this list is empty and 'All Portal Users' is not "
        "ticked, nobody can see the dashboard.",
    )
    all_portal_users = fields.Boolean(
        default=False,
        help="Share this dashboard with every portal user (external users "
        "such as dealers or distributors), in addition to the partners "
        "listed. Internal employees are not included: they only get access "
        "when their own partner is listed in Portal Partners.",
    )
    description = fields.Text(
        help="Short explanation shown under the dashboard title in the "
        "portal, e.g. 'Your orders and deliveries of the current year'.",
    )

    @api.depends("dashboard_id.name")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.dashboard_id.name if rec.dashboard_id else ""

    # ------------------------------------------------------------------
    # Write protection: only share what you can read yourself
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        self._check_dashboards_readable(
            [vals.get("dashboard_id") for vals in vals_list]
        )
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("dashboard_id"):
            self._check_dashboards_readable([vals["dashboard_id"]])
        return super().write(vals)

    @api.model
    def _check_dashboards_readable(self, dashboard_ids):
        """Refuse to share a dashboard the current user cannot read.

        ``sudo()`` callers (controllers, automated flows) are trusted. The
        ir.access grant also carries ``('dashboard_id', 'access', 'read')``;
        this check runs first so the user gets an explanation instead of a
        bare access error, and it also covers ``write`` (ir.access only checks
        the record before the update).
        """
        if self.env.su:
            return
        ids = sorted({dashboard_id for dashboard_id in dashboard_ids if dashboard_id})
        dashboards = self.env["spreadsheet.dashboard"].browse(ids).exists()
        for dashboard in dashboards:
            if not dashboard.has_access("read"):
                raise AccessError(
                    self.env._(
                        "You cannot share dashboard #%(dashboard_id)s on the "
                        "portal because you are not allowed to open it "
                        "yourself. Sharing it would expose data your own "
                        "access rights hide from you. Ask a Dashboard "
                        "administrator to share it, or to add you to one of "
                        "the dashboard's access groups.",
                        dashboard_id=dashboard.id,
                    )
                )

    # ------------------------------------------------------------------
    # Portal access
    # ------------------------------------------------------------------
    def _is_partner_assigned(self, partner):
        """Whether ``partner`` (or its company) is explicitly listed."""
        self.ensure_one()
        if not partner:
            return False
        commercial = partner.commercial_partner_id
        return commercial in self.partner_ids or partner in self.partner_ids

    def _is_accessible_by_user(self, user):
        """Whether ``user`` may view this dashboard on the portal.

        * the assignment and its dashboard must both be active;
        * public (not logged in) users never get access;
        * PORTAL users get access through ``all_portal_users``, their own
          contact or their company (commercial partner);
        * every other logged-in user (internal employees) only through an
          EXACT match of their own contact. The company match is not enough
          for them: base lets an internal user write their own partner
          (``res_partner_rule_write_self``), so they could set its parent to a
          dealer company and read that dealer's dashboard through the portal
          routes, which run as sudo. ``all_portal_users`` never applies to
          them either, so an internal user outside the dashboard's groups
          cannot use it to read the dashboard.
        """
        self.ensure_one()
        record = self.sudo()
        if not user or not record.active:
            return False
        if not record.dashboard_id or not record.dashboard_id.active:
            return False
        user = user.sudo()
        if user._is_public():
            return False
        if user._is_portal():
            return bool(
                record.all_portal_users or record._is_partner_assigned(user.partner_id)
            )
        return bool(user.partner_id and user.partner_id in record.partner_ids)

    def _is_accessible_by_partner(self, partner):
        """Backward-compatible wrapper: accessible by one of the partner's
        active users (see :meth:`_is_accessible_by_user`)."""
        self.ensure_one()
        return any(
            self._is_accessible_by_user(user) for user in partner.sudo().user_ids
        )

    @api.model
    def _get_portal_dashboards(self, user=None):
        """Return the active assignments ``user`` (default: current user) can
        view on the portal, as a sudo recordset."""
        if user is None:
            user = self.env.user
        candidates = self.sudo().search(
            [("active", "=", True), ("dashboard_id.active", "=", True)]
        )
        if user._name == "res.partner":
            # Legacy callers passed a partner: resolve through its users.
            return candidates.filtered(lambda d: d._is_accessible_by_partner(user))
        return candidates.filtered(lambda d: d._is_accessible_by_user(user))

    def _get_portal_spreadsheet_data(self):
        """Return the read-only data the portal preview needs.

        The payload is a reduced copy of the dashboard snapshot (see
        :func:`sanitize_spreadsheet_for_portal`): no revisions, no pivot or
        list definitions, no hidden/Data sheets and no formula sources.

        Private on purpose: the payload is read with sudo, so the method must
        never be reachable through ``/web/dataset/call_kw`` (which only
        refuses ``_``-prefixed or ``@api.private`` names and checks no record
        access). As a second guard, a non-sudo caller must be allowed to view
        the assignment (:meth:`_is_accessible_by_user`); the portal
        controller checks that itself and calls this on a sudo record.
        """
        self.ensure_one()
        if not self.env.su and not self._is_accessible_by_user(self.env.user):
            raise AccessError(
                self.env._(
                    "You cannot view this portal dashboard. It is archived, or "
                    "it is not shared with your account, and its figures may "
                    "only be shown to the partners it is shared with. Open "
                    "your dashboards from /my/dashboards, or ask the person "
                    "who shared it to add your contact again."
                )
            )
        dashboard = self.sudo().dashboard_id
        try:
            raw = dashboard.spreadsheet_raw or {}
        except Exception:  # noqa: BLE001 - a corrupt file must not crash the page
            _logger.warning(
                "Portal dashboard %s: could not read the spreadsheet data of "
                "dashboard %s; showing it as empty.",
                self.id,
                dashboard.id,
                exc_info=True,
            )
            raw = {}
        return {
            "name": self.sudo().name,
            "mode": "readonly",
            "spreadsheet_raw": sanitize_spreadsheet_for_portal(raw),
        }
