# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

# Guide spreadsheets whose cells call formulas registered by OPTIONAL modules.
# Without the providing module the cells render #NAME?, so the guide (its menu
# entry and every "Open Example" button pointing at it) is only offered when
# all modules listed here are installed. The guide JSON (data/files/) is never
# hand-written: it is the saas-19.4 o-spreadsheet engine's own export, so its
# cells stay loadable without a migration step.
GUIDE_REQUIRED_MODULES = {
    "spreadsheet_help_oca.guide_forecast": ("spreadsheet_forecast_oca",),
    "spreadsheet_help_oca.guide_period": ("spreadsheet_period_comparison_oca",),
    # ODOO.BALANCE / CREDIT / DEBIT / RESIDUAL / PARTNER.BALANCE / FISCALYEAR.*
    "spreadsheet_help_oca.guide_core": ("spreadsheet_account",),
    "spreadsheet_help_oca.guide_features": (),
}

# Interactive tours that need an access right on top of their module: the
# screen element they point at is hidden from users without it, so the tour
# would stop halfway. Tour name -> group xmlid.
TOUR_REQUIRED_GROUPS = {
    # File > Save as Template is only shown to template managers
    # (spreadsheet_template_oca save_as_template.esm.js isVisible).
    "spreadsheet_save_template": "spreadsheet_template_oca.group_template_manager",
}

# Help menu entry -> guide spreadsheet it opens.
GUIDE_MENUS = {
    "spreadsheet_help_oca.menu_guide_forecast": "spreadsheet_help_oca.guide_forecast",
    "spreadsheet_help_oca.menu_guide_period": "spreadsheet_help_oca.guide_period",
    "spreadsheet_help_oca.menu_guide_core": "spreadsheet_help_oca.guide_core",
    "spreadsheet_help_oca.menu_guide_features": "spreadsheet_help_oca.guide_features",
}


class SpreadsheetTutorial(models.Model):
    _name = "spreadsheet.tutorial"
    _description = "Spreadsheet Tutorial / Video Guide"
    _order = "sequence, name"

    name = fields.Char(
        required=True,
        translate=True,
        help="Title shown on the tutorial card, e.g. 'Quick Start - create your "
        "first spreadsheet'.",
    )
    sequence = fields.Integer(
        default=10,
        help="Lower numbers are shown first in the Tutorials & Videos list.",
    )
    active = fields.Boolean(
        default=True,
        help="Archive a tutorial to hide it from the Help menu without deleting it.",
    )
    description = fields.Text(
        translate=True,
        help="What the tutorial teaches and when it is useful, shown on the card. "
        "Example: 'Save a report layout once and recreate it in one click.'",
    )
    module_name = fields.Char(
        string="Related Module",
        help="Technical name of the module this tutorial covers (e.g. "
        "spreadsheet_template_oca). When that module is not installed, the "
        "tutorial is marked as unavailable and its tour and example are hidden. "
        "Leave empty for tutorials that only need the Spreadsheets app.",
    )
    is_available = fields.Boolean(
        string="Available",
        compute="_compute_is_available",
        search="_search_is_available",
        help="True when the Related Module is installed (or no module is "
        "required). Unavailable tutorials cannot start their tour or open their "
        "example, because the screens and formulas they rely on do not exist.",
    )
    duration_minutes = fields.Integer(
        default=5,
        help="Estimated time to complete this tutorial, in minutes (e.g. 5).",
    )
    video_url = fields.Char(
        string="Video URL",
        help="YouTube, Vimeo or any embeddable video URL. "
        "Leave empty for text-only tutorials.",
    )
    tour_name = fields.Char(
        string="Interactive Tour Name",
        help="Technical name of a tour registered under Settings > Technical > "
        "Tours (e.g. spreadsheet_quick_start). If set, the 'Interactive Tour' "
        "button launches it.",
    )
    guide_spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        string="Example Spreadsheet",
        help="A pre-built spreadsheet with live examples for this feature.",
    )
    difficulty = fields.Selection(
        [
            ("beginner", "Beginner"),
            ("intermediate", "Intermediate"),
            ("advanced", "Advanced"),
        ],
        default="beginner",
        help="Skill level shown as a badge so users can pick tutorials matching "
        "their experience (e.g. 'Beginner' for first-time users).",
    )
    tags = fields.Char(
        help="Comma-separated tags for search (e.g., 'formula,forecast,template').",
    )

    # ------------------------------------------------------------------
    # CRUD: keep module / tour names clean so the availability compute and
    # its search method always agree (both compare the stripped name).
    # ------------------------------------------------------------------
    @api.model
    def _normalize_technical_names(self, vals):
        for field_name in ("module_name", "tour_name"):
            if isinstance(vals.get(field_name), str):
                vals[field_name] = vals[field_name].strip() or False
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._normalize_technical_names(vals)
        return super().create(vals_list)

    def write(self, vals):
        return super().write(self._normalize_technical_names(dict(vals)))

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    @api.model
    def _get_installed_module_names(self):
        """Names of the installed modules (cached by the core, sudo inside)."""
        return set(self.env["ir.module.module"]._installed())

    @api.depends("module_name")
    def _compute_is_available(self):
        installed = self._get_installed_module_names()
        for tutorial in self:
            module = (tutorial.module_name or "").strip()
            tutorial.is_available = not module or module in installed

    def _search_is_available(self, operator, value):
        # saas-19.4 normalises boolean conditions to ('in' / 'not in', {True})
        # before calling the search method; anything else falls back to the ORM.
        if operator not in ("in", "not in"):
            return NotImplemented
        wanted = {bool(v) for v in value}
        if len(wanted) != 1:
            match_all = (operator == "in") == (len(wanted) == 2)
            return Domain.TRUE if match_all else Domain.FALSE
        want_available = (True in wanted) == (operator == "in")
        available = Domain(
            "module_name", "in", [False, *sorted(self._get_installed_module_names())]
        )
        return available if want_available else ~available

    @api.model
    def _get_missing_guide_modules(self, spreadsheet):
        """Modules a guide spreadsheet needs that are not installed ([] if none).

        Any spreadsheet can be passed: ordinary spreadsheets are not guides and
        need nothing. ``env.ref`` is ormcached, so this costs no query per call.
        """
        if not spreadsheet:
            return []
        for guide_xmlid, required in GUIDE_REQUIRED_MODULES.items():
            if not required:
                continue
            guide = self.env.ref(guide_xmlid, raise_if_not_found=False)
            if (
                guide
                and guide._name == spreadsheet._name
                and guide.id == spreadsheet.id
            ):
                installed = self._get_installed_module_names()
                return [module for module in required if module not in installed]
        return []

    @api.model
    def _get_guide_spreadsheet_ids(self):
        """Ids of the help guide spreadsheets that still exist."""
        ids = []
        for guide_xmlid in GUIDE_REQUIRED_MODULES:
            guide = self.env.ref(guide_xmlid, raise_if_not_found=False)
            if guide and guide._name == "spreadsheet.spreadsheet":
                ids.append(guide.id)
        return ids

    @api.model
    def _get_unavailable_guide_menu_ids(self):
        """Help menu entries whose guide needs a module that is not installed."""
        installed = self._get_installed_module_names()
        menu_ids = []
        for menu_xmlid, guide_xmlid in GUIDE_MENUS.items():
            required = GUIDE_REQUIRED_MODULES.get(guide_xmlid, ())
            if all(module in installed for module in required):
                continue
            menu = self.env.ref(menu_xmlid, raise_if_not_found=False)
            if menu:
                menu_ids.append(menu.id)
        return menu_ids

    @api.model
    def _get_missing_tour_group(self, tour_name):
        """Name of the group a tour needs and the user lacks (False if none)."""
        group_xmlid = TOUR_REQUIRED_GROUPS.get(tour_name)
        if not group_xmlid:
            return False
        try:
            if self.env.user.has_group(group_xmlid):
                return False
            group = self.env.ref(group_xmlid, raise_if_not_found=False)
            return group.sudo().display_name if group else group_xmlid
        except Exception:  # the check itself must never block the Help screen
            _logger.warning(
                "spreadsheet_help_oca: could not check group %s for tour %s",
                group_xmlid,
                tour_name,
                exc_info=True,
            )
            return False

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    @api.model
    def _notification(self, title, message, notif_type="warning"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": notif_type,
                "sticky": notif_type in ("warning", "danger"),
            },
        }

    def _notify_module_missing(self):
        self.ensure_one()
        module = (self.module_name or "").strip()
        return self._notification(
            self.env._("Module not installed"),
            self.env._(
                "This tutorial needs the module %(module)s, which is not installed "
                "in this database, so its tour and example cannot run. Ask an "
                "administrator to install %(module)s from the Apps menu; the "
                "tutorial becomes available right after.",
                module=module,
            ),
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    @api.model
    def _guide_unavailable_notification(self, spreadsheet):
        """Warning shown instead of opening a guide whose formulas are missing.

        Returns ``None`` when ``spreadsheet`` is not a guide or can be opened.
        """
        missing = self._get_missing_guide_modules(spreadsheet)
        if not missing:
            return None
        modules = ", ".join(missing)
        return self._notification(
            self.env._("Example not available yet"),
            self.env._(
                "This example uses formulas from %(modules)s, which is not "
                "installed. Without it the cells would only show #NAME? errors. "
                "Ask an administrator to install %(modules)s from the Apps menu, "
                "then open the example again.",
                modules=modules,
            ),
        )

    @api.model
    def _open_guide_spreadsheet(self, spreadsheet):
        """Open a guide spreadsheet, or explain why it cannot be opened."""
        notification = self._guide_unavailable_notification(spreadsheet)
        if notification:
            return notification
        try:
            spreadsheet.check_access("read")
        except AccessError:
            return self._notification(
                self.env._("No access to the example"),
                self.env._(
                    "You are not allowed to read this example spreadsheet, so it "
                    "cannot be opened. The guides are shared with every Spreadsheet "
                    "user by default; ask a Spreadsheet manager to add your group "
                    "under Read Access on the spreadsheet."
                ),
            )
        return spreadsheet.open_spreadsheet()

    @api.model
    def _action_open_guide(self, xmlid):
        """Entry point of the Help menu server actions."""
        spreadsheet = self.env.ref(xmlid, raise_if_not_found=False)
        if not spreadsheet or spreadsheet._name != "spreadsheet.spreadsheet":
            _logger.warning("Guide spreadsheet %s not found", xmlid)
            return self._notification(
                self.env._("Example spreadsheet missing"),
                self.env._(
                    "The example spreadsheet behind this menu was deleted, so there "
                    "is nothing to open. Upgrade the Spreadsheet Help & Examples "
                    "module from the Apps menu to restore it."
                ),
            )
        return self._open_guide_spreadsheet(spreadsheet)

    def action_open_example(self):
        """Open the associated guide spreadsheet if set."""
        self.ensure_one()
        if not self.is_available:
            return self._notify_module_missing()
        if not self.guide_spreadsheet_id:
            return self._notification(
                self.env._("No example available"),
                self.env._(
                    "This tutorial does not have an example spreadsheet yet, so there "
                    "is nothing to open. A Spreadsheet manager can link one in the "
                    "Example Spreadsheet field of this tutorial."
                ),
            )
        return self._open_guide_spreadsheet(self.guide_spreadsheet_id)

    def action_start_tour(self):
        """Launch the associated web_tour interactive tour."""
        self.ensure_one()
        if not self.tour_name:
            return self._notification(
                self.env._("No tour available"),
                self.env._(
                    "This tutorial does not have an interactive tour, so there is "
                    "nothing to start. A Spreadsheet manager can set one in the "
                    "Interactive Tour Name field of this tutorial (for example "
                    "spreadsheet_quick_start)."
                ),
                notif_type="info",
            )
        if not self.is_available:
            return self._notify_module_missing()
        tour = self.env["web_tour.tour"].search(
            [("name", "=", self.tour_name.strip())], limit=1
        )
        if not tour:
            return self._notification(
                self.env._("Tour not found"),
                self.env._(
                    "The interactive tour %(tour)s is not registered in the "
                    "database, so it cannot start. Upgrade the Spreadsheet Help & "
                    "Examples module, or check the tour name under Settings > "
                    "Technical > Tours.",
                    tour=self.tour_name,
                ),
            )
        missing_group = self._get_missing_tour_group(tour.name)
        if missing_group:
            return self._notification(
                self.env._("Access right missing"),
                self.env._(
                    "This tour needs the %(group)s access right: the menu entry it "
                    "guides you to is only shown to users who have it, so the tour "
                    "would stop halfway. Ask an administrator to grant you "
                    "%(group)s under Settings > Users, then start the tour again.",
                    group=missing_group,
                ),
            )
        # saas-19.4 startTour() only redirects through options.url: the tour's
        # starting URL must travel with the client action.
        return {
            "type": "ir.actions.client",
            "tag": "spreadsheet_help_start_tour",
            "params": {"tour_name": tour.name, "url": tour.url or False},
        }
