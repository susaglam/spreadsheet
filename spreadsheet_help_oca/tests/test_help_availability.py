# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
from unittest.mock import patch

from lxml import etree

from odoo.fields import Command, Domain
from odoo.modules.module import load_script
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import convert_file
from odoo.tools.safe_eval import safe_eval

GUIDE_XMLIDS = (
    "spreadsheet_help_oca.guide_forecast",
    "spreadsheet_help_oca.guide_period",
    "spreadsheet_help_oca.guide_core",
    "spreadsheet_help_oca.guide_features",
)
TOUR_XMLIDS = (
    "spreadsheet_help_oca.tour_quick_start",
    "spreadsheet_help_oca.tour_save_template",
    "spreadsheet_help_oca.tour_kpi_alert",
)
MISSING_MODULE = "spreadsheet_help_oca_test_module_that_does_not_exist"
TEMPLATE_MANAGER = "spreadsheet_template_oca.group_template_manager"
POST_MIGRATE = "spreadsheet_help_oca/migrations/saas~19.4.1.0.2/post-migrate.py"
# Help & Examples cards of the OCA purchase dashboards: xml name -> module
PURCHASE_DASHBOARD_CARDS = {
    "tutorial_dashboard_purchase": "spreadsheet_dashboard_purchase_oca",
    "tutorial_dashboard_purchase_stock": "spreadsheet_dashboard_purchase_stock_oca",
}


@tagged("post_install", "-at_install")
class TestHelpAvailability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tutorial = cls.env["spreadsheet.tutorial"]
        cls.sheet_user = new_test_user(
            cls.env,
            login="help_oca_plain_sheet_user",
            groups="base.group_user,spreadsheet_oca.group_user",
        )

    def _patch_installed(self, modules):
        return patch.object(
            type(self.Tutorial),
            "_get_installed_module_names",
            return_value=set(modules),
        )

    # ------------------------------------------------------------------
    # [7] guide spreadsheets are shared with every Spreadsheet user
    # ------------------------------------------------------------------
    def test_plain_spreadsheet_user_can_read_guides(self):
        guides = self.env["spreadsheet.spreadsheet"]
        for xmlid in GUIDE_XMLIDS:
            guides |= self.env.ref(xmlid)
        as_user = guides.with_user(self.sheet_user)
        # record rules: a search as the user must see all four guides
        self.assertEqual(
            self.env["spreadsheet.spreadsheet"]
            .with_user(self.sheet_user)
            .search([("id", "in", guides.ids)]),
            as_user,
        )
        for guide in as_user:
            guide.check_access("read")
            data = guide.get_spreadsheet_data()
            self.assertEqual(guide.name, data["name"])
            # shared read-only: ordinary users must not be able to edit them
            self.assertEqual(data["mode"], "readonly")

    def test_help_menu_server_action_opens_guide_for_plain_user(self):
        action = self.env.ref("spreadsheet_help_oca.action_guide_features")
        result = action.with_user(self.sheet_user).run()
        self.assertEqual(result.get("tag"), "action_spreadsheet_oca")
        self.assertEqual(
            result["params"]["spreadsheet_id"],
            self.env.ref("spreadsheet_help_oca.guide_features").id,
        )

    # ------------------------------------------------------------------
    # [20] tutorials of modules that are not installed are unavailable
    # ------------------------------------------------------------------
    def test_tutorial_for_uninstalled_module_is_unavailable(self):
        missing = self.Tutorial.create(
            {
                "name": "Missing module tutorial",
                "module_name": MISSING_MODULE,
                "tour_name": "spreadsheet_quick_start",
                "guide_spreadsheet_id": self.env.ref(
                    "spreadsheet_help_oca.guide_features"
                ).id,
            }
        )
        installed = self.Tutorial.create(
            {"name": "Installed module tutorial", "module_name": "spreadsheet_oca"}
        )
        no_module = self.Tutorial.create({"name": "No module tutorial"})

        self.assertFalse(missing.is_available)
        self.assertTrue(installed.is_available)
        self.assertTrue(no_module.is_available)

        records = missing | installed | no_module
        available = self.Tutorial.search(
            [("id", "in", records.ids), ("is_available", "=", True)]
        )
        self.assertEqual(available, installed | no_module)
        unavailable = self.Tutorial.search(
            [("id", "in", records.ids), ("is_available", "=", False)]
        )
        self.assertEqual(unavailable, missing)

        for result in (missing.action_start_tour(), missing.action_open_example()):
            self.assertEqual(result["tag"], "display_notification")
            self.assertEqual(result["params"]["type"], "warning")

    def test_blank_or_padded_module_name_agrees_in_compute_and_search(self):
        padded = self.Tutorial.create(
            {"name": "Padded module", "module_name": "  spreadsheet_oca  "}
        )
        blank = self.Tutorial.create({"name": "Blank module", "module_name": "   "})
        padded_missing = self.Tutorial.create(
            {"name": "Padded missing", "module_name": f" {MISSING_MODULE} "}
        )
        self.assertEqual(padded.module_name, "spreadsheet_oca")
        self.assertFalse(blank.module_name)
        blank.write({"module_name": " spreadsheet_oca "})
        self.assertEqual(blank.module_name, "spreadsheet_oca")

        records = padded | blank | padded_missing
        for record in records:
            found = self.Tutorial.search(
                [("id", "=", record.id), ("is_available", "=", True)]
            )
            self.assertEqual(bool(found), record.is_available, record.name)
        self.assertEqual(
            self.Tutorial.search(
                [("id", "in", records.ids), ("is_available", "=", True)]
            ),
            padded | blank,
        )

    def test_tutorial_action_hides_unavailable_by_default(self):
        action = self.env.ref("spreadsheet_help_oca.tutorial_action")
        context = safe_eval(action.context or "{}")
        self.assertTrue(context.get("search_default_available"))

        # The default filter must actually exclude unavailable tutorials.
        search_view = self.env.ref("spreadsheet_help_oca.tutorial_view_search")
        filters = etree.fromstring(search_view.arch.encode()).xpath(
            "//filter[@name='available']"
        )
        self.assertEqual(len(filters), 1)
        filter_domain = safe_eval(filters[0].get("domain"))

        missing = self.Tutorial.create(
            {"name": "Hidden by default", "module_name": MISSING_MODULE}
        )
        installed = self.Tutorial.create(
            {"name": "Shown by default", "module_name": "spreadsheet_oca"}
        )
        found = self.Tutorial.search(
            Domain(filter_domain) & Domain("id", "in", (missing | installed).ids)
        )
        self.assertEqual(found, installed)

    # ------------------------------------------------------------------
    # [16] purchase dashboards have a Help & Examples card
    # ------------------------------------------------------------------
    def _purchase_dashboard_cards(self):
        cards = self.Tutorial
        for name, module in PURCHASE_DASHBOARD_CARDS.items():
            card = self.env.ref(f"spreadsheet_help_oca.{name}")
            self.assertEqual(card._name, "spreadsheet.tutorial")
            self.assertEqual(card.module_name, module, name)
            self.assertTrue(card.active, name)
            self.assertTrue(card.description, name)
            cards |= card
        return cards

    def _available_cards(self, cards):
        """Available cards, checked to agree between compute and search."""
        cards.invalidate_recordset(["is_available"])
        computed = cards.filtered("is_available")
        searched = self.Tutorial.search(
            [("id", "in", cards.ids), ("is_available", "=", True)]
        )
        self.assertEqual(computed, searched)
        return computed

    def test_purchase_dashboard_cards_follow_their_module(self):
        cards = self._purchase_dashboard_cards()
        vendors = self.env.ref("spreadsheet_help_oca.tutorial_dashboard_purchase")
        receipts = cards - vendors

        with self._patch_installed({"spreadsheet_oca", "purchase", "stock"}):
            self.assertFalse(self._available_cards(cards))
            self.assertEqual(
                self.Tutorial.search(
                    [("id", "in", cards.ids), ("is_available", "=", False)]
                ),
                cards,
            )
            # the default "Available" filter of the Help menu hides both cards
            search_view = self.env.ref("spreadsheet_help_oca.tutorial_view_search")
            available_filter = etree.fromstring(search_view.arch.encode()).xpath(
                "//filter[@name='available']"
            )[0]
            filter_domain = Domain(safe_eval(available_filter.get("domain")))
            self.assertFalse(
                self.Tutorial.search(filter_domain & Domain("id", "in", cards.ids))
            )
            for card in cards:
                result = card.action_open_example()
                self.assertEqual(result["tag"], "display_notification")
                self.assertEqual(result["params"]["type"], "warning")
                self.assertIn(card.module_name, result["params"]["message"])

        # each card only needs its own module
        with self._patch_installed({"spreadsheet_dashboard_purchase_oca"}):
            self.assertEqual(self._available_cards(cards), vendors)
        with self._patch_installed({"spreadsheet_dashboard_purchase_stock_oca"}):
            self.assertEqual(self._available_cards(cards), receipts)
        with self._patch_installed(PURCHASE_DASHBOARD_CARDS.values()):
            self.assertEqual(self._available_cards(cards), cards)

        # unpatched: availability follows the modules really installed here
        installed = self.Tutorial._get_installed_module_names()
        cards.invalidate_recordset(["is_available"])
        for card in cards:
            self.assertEqual(card.is_available, card.module_name in installed)

    def test_update_creates_missing_cards(self):
        """tutorials.xml is noupdate="1", but noupdate only protects cards whose
        xmlid already exists: upgrading a database installed before the
        purchase dashboard cards must create them, without touching the cards
        users edited. No post-migrate script is needed for new cards."""
        cards = self._purchase_dashboard_cards()
        modules = list(PURCHASE_DASHBOARD_CARDS.values())
        Tutorial = self.Tutorial.with_context(active_test=False)
        count_before = Tutorial.search_count([("module_name", "in", modules)])
        edited = self.env.ref("spreadsheet_help_oca.tutorial_dashboard_stock")
        edited.name = "My own stock dashboard card"
        cards.unlink()  # also removes their ir.model.data rows
        self.env.flush_all()
        for name in PURCHASE_DASHBOARD_CARDS:
            self.assertFalse(
                self.env.ref(f"spreadsheet_help_oca.{name}", raise_if_not_found=False)
            )

        for _run in range(2):  # a second update neither duplicates nor fails
            convert_file(
                self.env, "spreadsheet_help_oca", "data/tutorials.xml", {}, "update"
            )
            self.env.invalidate_all()
            self._purchase_dashboard_cards()
            self.assertEqual(
                Tutorial.search_count([("module_name", "in", modules)]),
                count_before,
            )
            self.assertEqual(edited.name, "My own stock dashboard card")

        xml_ids = self.env["ir.model.data"].search(
            [
                ("module", "=", "spreadsheet_help_oca"),
                ("name", "in", list(PURCHASE_DASHBOARD_CARDS)),
            ]
        )
        self.assertEqual(len(xml_ids), len(PURCHASE_DASHBOARD_CARDS))
        self.assertTrue(all(xml_ids.mapped("noupdate")))

    # ------------------------------------------------------------------
    # [16F] guides whose formulas come from a missing module never open
    # ------------------------------------------------------------------
    def test_guide_menu_hidden_when_formula_module_missing(self):
        Menu = self.env["ir.ui.menu"]
        core_menu = self.env.ref("spreadsheet_help_oca.menu_guide_core")
        forecast_menu = self.env.ref("spreadsheet_help_oca.menu_guide_forecast")
        features_menu = self.env.ref("spreadsheet_help_oca.menu_guide_features")
        with self._patch_installed({"spreadsheet_oca"}):
            hidden = Menu._load_menus_blacklist()
            self.assertIn(core_menu.id, hidden)
            self.assertIn(forecast_menu.id, hidden)
            self.assertNotIn(features_menu.id, hidden)
            result = self.Tutorial._action_open_guide(
                "spreadsheet_help_oca.guide_forecast"
            )
            self.assertEqual(result["tag"], "display_notification")
        with self._patch_installed(
            {
                "spreadsheet_oca",
                "spreadsheet_account",
                "spreadsheet_forecast_oca",
                "spreadsheet_period_comparison_oca",
            }
        ):
            hidden = Menu._load_menus_blacklist()
            self.assertNotIn(core_menu.id, hidden)
            self.assertNotIn(forecast_menu.id, hidden)
            result = self.Tutorial._action_open_guide(
                "spreadsheet_help_oca.guide_forecast"
            )
            self.assertEqual(result["tag"], "action_spreadsheet_oca")

    def test_guide_does_not_open_from_spreadsheet_views_without_its_module(self):
        """The guides are shared with every user, so they also appear in the
        Spreadsheets kanban / list, whose Edit buttons call open_spreadsheet
        directly. That path must apply the same missing-module check."""
        Spreadsheet = self.env["spreadsheet.spreadsheet"].with_user(self.sheet_user)
        forecast = Spreadsheet.browse(
            self.env.ref("spreadsheet_help_oca.guide_forecast").id
        )
        features = Spreadsheet.browse(
            self.env.ref("spreadsheet_help_oca.guide_features").id
        )
        own_sheet = Spreadsheet.create({"name": "Help test own sheet"})
        with self._patch_installed({"spreadsheet_oca"}):
            result = forecast.open_spreadsheet()
            self.assertEqual(result["tag"], "display_notification")
            self.assertEqual(result["params"]["type"], "warning")
            self.assertEqual(
                features.open_spreadsheet()["tag"], "action_spreadsheet_oca"
            )
            self.assertEqual(
                own_sheet.open_spreadsheet()["tag"], "action_spreadsheet_oca"
            )
        with self._patch_installed({"spreadsheet_oca", "spreadsheet_forecast_oca"}):
            self.assertEqual(
                forecast.open_spreadsheet()["tag"], "action_spreadsheet_oca"
            )

    # ------------------------------------------------------------------
    # [TOURS] tour rows are custom (never auto-played) and carry their url
    # ------------------------------------------------------------------
    def test_tour_records_are_custom(self):
        Tour = self.env["web_tour.tour"]
        tours = Tour
        for xmlid in TOUR_XMLIDS:
            tours |= self.env.ref(xmlid)
        self.assertTrue(all(tours.mapped("custom")))
        self.assertFalse(tours.step_ids, "steps come from the JS registry only")

        # Consume every OTHER onboarding tour: if one of ours were not custom,
        # get_current_tour() would now return it.
        self.sheet_user.tour_enabled = True
        Tour.search([("custom", "=", False), ("id", "not in", tours.ids)]).write(
            {"user_consumed_ids": [Command.link(self.sheet_user.id)]}
        )
        self.assertFalse(Tour.with_user(self.sheet_user).get_current_tour())

    def test_start_tour_passes_the_tour_url(self):
        tour = self.env.ref("spreadsheet_help_oca.tour_quick_start")
        tutorial = self.env.ref("spreadsheet_help_oca.tutorial_quick_start")
        result = tutorial.with_user(self.sheet_user).action_start_tour()
        self.assertEqual(result["tag"], "spreadsheet_help_start_tour")
        self.assertEqual(result["params"]["tour_name"], tour.name)
        self.assertEqual(result["params"]["url"], tour.url)

    def test_start_tour_unknown_tour_returns_warning(self):
        tutorial = self.Tutorial.create(
            {"name": "Ghost tour", "tour_name": "spreadsheet_help_oca_no_such_tour"}
        )
        result = tutorial.action_start_tour()
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "warning")

    def test_save_template_tour_needs_template_manager(self):
        """The File > Save as Template entry is hidden from non template
        managers: the tour must explain that instead of starting and getting
        stuck at step 3."""
        tutorial = self.Tutorial.create(
            {"name": "Save template tour", "tour_name": "spreadsheet_save_template"}
        )
        result = tutorial.with_user(self.sheet_user).action_start_tour()
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "warning")

        if not self.env.ref(TEMPLATE_MANAGER, raise_if_not_found=False):
            return  # spreadsheet_template_oca not installed: nobody can pass
        template_manager = new_test_user(
            self.env,
            login="help_oca_template_manager",
            groups=f"base.group_user,spreadsheet_oca.group_user,{TEMPLATE_MANAGER}",
        )
        result = tutorial.with_user(template_manager).action_start_tour()
        self.assertEqual(result["tag"], "spreadsheet_help_start_tour")
        self.assertEqual(result["params"]["tour_name"], "spreadsheet_save_template")

    # ------------------------------------------------------------------
    # Upgrade from saas~19.4.1.0.1 (noupdate records)
    # ------------------------------------------------------------------
    def test_post_migrate_brings_old_records_in_line(self):
        cr = self.env.cr
        group = self.env.ref("spreadsheet_oca.group_user")
        guide = self.env.ref("spreadsheet_help_oca.guide_forecast")
        guide.write(
            {
                "reader_group_ids": [Command.unlink(group.id)],
                "name": "📈 Rehber: Tahminleme Fonksiyonlari",
            }
        )
        tour = self.env.ref("spreadsheet_help_oca.tour_kpi_alert")
        tour.custom = False
        shipped = self.env.ref("spreadsheet_help_oca.tutorial_kpi_alert")
        edited = self.env.ref("spreadsheet_help_oca.tutorial_forecast")
        padded = self.Tutorial.create({"name": "Padded", "module_name": "x"})
        self.env.flush_all()
        old_name = "🔔 KPI Alert kurun"
        cr.execute(
            "UPDATE spreadsheet_tutorial SET name = %s::jsonb WHERE id = %s",
            (json.dumps({"en_US": old_name, "nl_NL": old_name}), shipped.id),
        )
        cr.execute(
            "UPDATE spreadsheet_tutorial SET name = %s::jsonb WHERE id = %s",
            (json.dumps({"en_US": "My own forecasting title"}), edited.id),
        )
        cr.execute(
            "UPDATE spreadsheet_tutorial SET module_name = '  spreadsheet_oca '"
            " WHERE id = %s",
            (padded.id,),
        )
        self.env.invalidate_all()

        migration = load_script(POST_MIGRATE, "spreadsheet_help_oca_test_post_migrate")
        migration.migrate(cr, "saas~19.4.1.0.1")
        self.env.invalidate_all()

        self.assertIn(group, guide.reader_group_ids)
        self.assertEqual(guide.name, "📈 Guide: Forecasting Functions")
        self.assertTrue(tour.custom)
        cr.execute("SELECT name FROM spreadsheet_tutorial WHERE id = %s", (shipped.id,))
        self.assertEqual(cr.fetchone()[0], {"en_US": "🔔 Set up a KPI alert"})
        cr.execute("SELECT name FROM spreadsheet_tutorial WHERE id = %s", (edited.id,))
        self.assertEqual(cr.fetchone()[0], {"en_US": "My own forecasting title"})
        self.assertEqual(padded.module_name, "spreadsheet_oca")

        # Idempotent: a second run changes nothing and does not fail.
        migration.migrate(cr, "saas~19.4.1.0.1")
        self.env.invalidate_all()
        self.assertEqual(guide.reader_group_ids.filtered(lambda g: g == group), group)
        self.assertEqual(guide.name, "📈 Guide: Forecasting Functions")
