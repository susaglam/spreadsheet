# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import inspect
import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from odoo.exceptions import AccessDenied, AccessError
from odoo.service.model import call_kw
from odoo.tests.common import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.spreadsheet_portal_dashboard_oca.models.ir_http import (
    IrHttp as PortalDashboardIrHttp,
)
from odoo.addons.spreadsheet_portal_dashboard_oca.models.spreadsheet_portal_dashboard import (  # noqa: E501
    sanitize_spreadsheet_for_portal,
)

MODULE = "spreadsheet_portal_dashboard_oca"


class PortalDashboardCommon:
    @classmethod
    def _setup_portal_dashboard_data(cls):
        cls.PortalDash = cls.env["spreadsheet.portal.dashboard"]

        # A dashboard group + dashboards to assign.
        group = cls.env["spreadsheet.dashboard.group"].create({"name": "Test Group"})
        cls.dashboard = cls.env["spreadsheet.dashboard"].create(
            {"name": "Sales Dashboard", "dashboard_group_id": group.id}
        )
        cls.other_dashboard = cls.env["spreadsheet.dashboard"].create(
            {"name": "Ops Dashboard", "dashboard_group_id": group.id}
        )
        # Only Settings administrators may open this one in the backend.
        cls.restricted_dashboard = cls.env["spreadsheet.dashboard"].create(
            {
                "name": "Accounting Dashboard",
                "dashboard_group_id": group.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_system").id])],
            }
        )

        # A commercial (company) partner with a child contact partner.
        cls.company_partner = cls.env["res.partner"].create(
            {"name": "Dealer Co", "is_company": True}
        )
        cls.child_partner = cls.env["res.partner"].create(
            {"name": "Dealer Contact", "parent_id": cls.company_partner.id}
        )
        # A completely unrelated partner (should never get access).
        cls.stranger = cls.env["res.partner"].create({"name": "Stranger"})

        cls.portal_user = new_test_user(
            cls.env,
            login="portal_dealer_test",
            groups="base.group_portal",
            partner_id=cls.child_partner.id,
        )
        cls.internal_user = new_test_user(
            cls.env, login="internal_dash_test", groups="base.group_user"
        )
        cls.spreadsheet_user = new_test_user(
            cls.env,
            login="spreadsheet_dash_test",
            groups="base.group_user,spreadsheet_oca.group_user",
        )
        cls.dashboard_manager = new_test_user(
            cls.env,
            login="dashboard_manager_test",
            groups="base.group_user,spreadsheet_dashboard.group_dashboard_manager",
        )


@tagged("post_install", "-at_install")
class TestPortalDashboard(PortalDashboardCommon, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_portal_dashboard_data()

    # ------------------------------------------------------------------
    # ir.http translation hook
    # ------------------------------------------------------------------
    def test_translation_frontend_modules_is_classmethod(self):
        """Every core override is a classmethod and their super() chain calls
        it without an instance: an instance method here 500s the site."""
        self.assertIsInstance(
            inspect.getattr_static(
                PortalDashboardIrHttp, "_get_translation_frontend_modules_name"
            ),
            classmethod,
        )
        # Called on the registry CLASS, exactly like core does: raises
        # TypeError if any override in the MRO is an instance method.
        # website's override reads http.request.registry, which is unbound in a
        # TransactionCase: mock it only when website is installed.
        with ExitStack() as stack:
            if "website" in self.env.registry._init_modules:
                stack.enter_context(
                    patch(
                        "odoo.addons.website.models.ir_http.request",
                        new=MagicMock(registry=self.env.registry),
                    )
                )
            modules = self.env.registry[
                "ir.http"
            ]._get_translation_frontend_modules_name()
        self.assertIn(MODULE, modules)
        self.assertIn("portal", modules)

    # ------------------------------------------------------------------
    # Access scope
    # ------------------------------------------------------------------
    def test_portal_user_sees_active_assignment(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.company_partner.id])],
            }
        )
        # Company assignment reaches the child contact's portal user.
        self.assertTrue(assignment._is_accessible_by_user(self.portal_user))
        self.assertIn(
            assignment, self.PortalDash._get_portal_dashboards(self.portal_user)
        )

    def test_direct_partner_match(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        self.assertTrue(assignment._is_accessible_by_user(self.portal_user))
        self.assertTrue(assignment._is_accessible_by_partner(self.child_partner))

    def test_unassigned_user_denied(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.stranger.id])],
            }
        )
        self.assertFalse(assignment._is_accessible_by_user(self.portal_user))
        self.assertNotIn(
            assignment, self.PortalDash._get_portal_dashboards(self.portal_user)
        )

    def test_archived_assignment_denied(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        assignment.action_archive()
        self.assertFalse(assignment._is_accessible_by_user(self.portal_user))
        self.assertNotIn(
            assignment, self.PortalDash._get_portal_dashboards(self.portal_user)
        )

    def test_archived_dashboard_denied(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.other_dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        self.other_dashboard.active = False
        self.assertFalse(assignment._is_accessible_by_user(self.portal_user))
        self.assertNotIn(
            assignment, self.PortalDash._get_portal_dashboards(self.portal_user)
        )

    def test_all_portal_users_only_grants_portal_users(self):
        assignment = self.PortalDash.create(
            {"dashboard_id": self.restricted_dashboard.id, "all_portal_users": True}
        )
        self.assertTrue(assignment._is_accessible_by_user(self.portal_user))
        # An internal user outside the dashboard's groups must NOT reach its
        # (sudo) data through the portal routes.
        self.assertFalse(assignment._is_accessible_by_user(self.internal_user))
        self.assertNotIn(
            assignment, self.PortalDash._get_portal_dashboards(self.internal_user)
        )
        self.assertFalse(
            assignment._is_accessible_by_user(self.env.ref("base.public_user"))
        )

    def test_internal_user_explicitly_assigned(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.internal_user.partner_id.id])],
            }
        )
        self.assertTrue(assignment._is_accessible_by_user(self.internal_user))

    def test_internal_user_reparenting_own_partner_denied(self):
        """Base lets an internal user write their own partner
        (res_partner_rule_write_self). Moving it under a dealer company must
        not unlock that dealer's dashboards: the company match is for portal
        users only."""
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.restricted_dashboard.id,
                "partner_ids": [(6, 0, [self.company_partner.id])],
            }
        )
        self.internal_user.partner_id.parent_id = self.company_partner
        self.assertEqual(
            self.internal_user.partner_id.commercial_partner_id, self.company_partner
        )
        self.assertFalse(assignment._is_accessible_by_user(self.internal_user))
        self.assertNotIn(
            assignment, self.PortalDash._get_portal_dashboards(self.internal_user)
        )
        # The dealer's real portal contact keeps access.
        self.assertTrue(assignment._is_accessible_by_user(self.portal_user))

    def test_portal_user_has_no_orm_access(self):
        """Portal pages read assignments with sudo; a portal user must not be
        able to list them (partner_ids of other dealers) over RPC."""
        self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "all_portal_users": True,
                "partner_ids": [(6, 0, [self.stranger.id])],
            }
        )
        with self.assertRaises(AccessError):
            self.PortalDash.with_user(self.portal_user).search_read([], ["partner_ids"])

    # ------------------------------------------------------------------
    # Payload builder: never reachable over RPC, guarded for direct calls
    # ------------------------------------------------------------------
    def test_payload_builder_not_callable_over_rpc(self):
        """/web/dataset/call_kw is auth='user' and browses any id without a
        record check: the sudo payload builder must not be reachable."""
        assignment = self.PortalDash.create(
            {"dashboard_id": self.restricted_dashboard.id, "all_portal_users": True}
        )
        for user in (self.portal_user, self.internal_user):
            model = self.PortalDash.with_user(user)
            with self.assertRaises(AccessError):
                call_kw(model, "_get_portal_spreadsheet_data", [[assignment.id]], {})
            # The former public name no longer exists at all.
            with self.assertRaises((AccessError, AttributeError)):
                call_kw(model, "get_portal_spreadsheet_data", [[assignment.id]], {})

    def test_payload_builder_guard(self):
        shared = self.PortalDash.create(
            {"dashboard_id": self.restricted_dashboard.id, "all_portal_users": True}
        )
        unshared = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.stranger.id])],
            }
        )
        archived = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
                "active": False,
            }
        )
        # Allowed portal user, non-sudo call: works.
        payload = shared.with_user(self.portal_user)._get_portal_spreadsheet_data()
        self.assertEqual(payload["mode"], "readonly")
        # Internal user outside the dashboard's groups (all_portal_users does
        # not apply to them), portal user not in the list, archived record.
        for record, user in (
            (shared, self.internal_user),
            (unshared, self.portal_user),
            (archived, self.portal_user),
        ):
            with self.assertRaises(AccessError):
                record.with_user(user)._get_portal_spreadsheet_data()

    # ------------------------------------------------------------------
    # Write protection
    # ------------------------------------------------------------------
    def test_non_manager_cannot_create_assignment(self):
        with self.assertRaises(AccessError):
            self.PortalDash.with_user(self.spreadsheet_user).create(
                {
                    "dashboard_id": self.dashboard.id,
                    "partner_ids": [(6, 0, [self.spreadsheet_user.partner_id.id])],
                }
            )

    def test_non_manager_cannot_edit_assignment(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        as_user = assignment.with_user(self.spreadsheet_user)
        # Read-only visibility for dashboards they can open themselves.
        self.assertEqual(as_user.name, "Sales Dashboard")
        with self.assertRaises(AccessError):
            as_user.write({"all_portal_users": True})
        with self.assertRaises(AccessError):
            as_user.unlink()

    def test_manager_can_create_assignment(self):
        assignment = self.PortalDash.with_user(self.dashboard_manager).create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        self.assertTrue(assignment.exists())

    def test_manager_cannot_share_unreadable_dashboard(self):
        other_company = self.env["res.company"].create({"name": "Other Portal Co"})
        foreign_dashboard = self.env["spreadsheet.dashboard"].create(
            {
                "name": "Foreign Dashboard",
                "dashboard_group_id": self.dashboard.dashboard_group_id.id,
                "company_ids": [(6, 0, [other_company.id])],
            }
        )
        PortalDash = self.PortalDash.with_user(self.dashboard_manager)
        with self.assertRaises(AccessError):
            PortalDash.create({"dashboard_id": foreign_dashboard.id})
        assignment = PortalDash.create({"dashboard_id": self.dashboard.id})
        with self.assertRaises(AccessError):
            assignment.write({"dashboard_id": foreign_dashboard.id})

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    def test_portal_payload_strips_internal_data(self):
        self.dashboard.spreadsheet_raw = {
            "version": "19.3.2",
            "sheets": [
                {
                    "id": "sheet1",
                    "name": "Overview",
                    "cells": {
                        "A1": '=_t("Revenue")',
                        "B1": '=PIVOT.VALUE(1,"__count")',
                        "C1": "Plain text",
                    },
                    "figures": [
                        {
                            "id": "fig1",
                            "tag": "chart",
                            "data": {
                                "type": "scorecard",
                                "title": {"text": "Orders"},
                                "keyValue": "Data!A1",
                            },
                        }
                    ],
                },
                {"id": "sheet2", "name": "Data", "cells": {"A1": "SECRET-DATA"}},
                {
                    "id": "sheet3",
                    "name": "Hidden",
                    "isVisible": False,
                    "cells": {"A1": "SECRET-HIDDEN"},
                },
            ],
            "pivots": {
                "1": {
                    "type": "ODOO",
                    "model": "res.partner",
                    "domain": [["name", "=", "SECRET-DOMAIN"]],
                    "measures": ["__count"],
                    "columns": [],
                    "rows": [],
                }
            },
            "styles": {},
            "borders": {},
        }
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        payload = assignment.sudo()._get_portal_spreadsheet_data()
        self.assertNotIn("revisions", payload)
        self.assertEqual(payload["mode"], "readonly")
        dumped = json.dumps(payload)
        for secret in ("SECRET-DATA", "SECRET-HIDDEN", "SECRET-DOMAIN", "res.partner"):
            self.assertNotIn(secret, dumped)
        raw = payload["spreadsheet_raw"]
        self.assertNotIn("pivots", raw)
        self.assertEqual([s["name"] for s in raw["sheets"]], ["Overview"])
        cells = raw["sheets"][0]["cells"]
        self.assertEqual(cells["A1"], '=_t("Revenue")')
        self.assertEqual(cells["B1"], "=")
        self.assertEqual(cells["C1"], "Plain text")
        figure = raw["sheets"][0]["figures"][0]
        self.assertEqual(
            figure["data"], {"type": "scorecard", "title": {"text": "Orders"}}
        )

    # ------------------------------------------------------------------
    # Sanitizer edge cases
    # ------------------------------------------------------------------
    def test_sanitizer_masks_concatenated_label_formula(self):
        """A formula that only starts like a label must stay masked."""
        raw = {
            "sheets": [
                {
                    "name": "Overview",
                    "cells": {
                        "A1": '=_t("Rev")&ODOO.LIST.HEADER(1,"secret_margin_field")',
                        "A2": '=_t("Plain label")',
                        "A3": '=_t("Say \\"hi\\"")',
                    },
                }
            ]
        }
        cells = sanitize_spreadsheet_for_portal(raw)["sheets"][0]["cells"]
        self.assertEqual(cells["A1"], "=")
        self.assertNotIn("secret_margin_field", json.dumps(cells))
        self.assertEqual(cells["A2"], '=_t("Plain label")')
        self.assertEqual(cells["A3"], '=_t("Say \\"hi\\"")')

    def test_sanitizer_squished_offsets(self):
        raw = {
            "sheets": [
                {
                    "name": "Overview",
                    "cells": {
                        # Integer (also thousands-grouped) + number offsets.
                        "A1": "1,000",
                        "A2:A3": {"N": "+1"},
                        # Formula + offsets: masked.
                        "B1": "=SUM(Data!A1)",
                        "B2": {"R": "+1R"},
                        # Static text + offsets: nothing to show.
                        "C1": "01/01/2026",
                        "C2": {"N": "+1"},
                        # Label + string offsets: labels kept.
                        "D1": '=_t("North")',
                        "D2": {"S": ["South"]},
                    },
                }
            ]
        }
        cells = sanitize_spreadsheet_for_portal(raw)["sheets"][0]["cells"]
        self.assertEqual(cells["A2:A3"], {"N": "+1"})
        self.assertEqual(cells["B2"], "=")
        self.assertNotIn("C2", cells)
        self.assertEqual(cells["D2"], {"S": ["South"]})

    # ------------------------------------------------------------------
    # Websocket
    # ------------------------------------------------------------------
    def _build_channels_as(self, user, channels):
        """Call _build_bus_channel_list like the websocket does. The core
        implementation reads ``(request or wsrequest).session.uid``, which is
        unbound in a TransactionCase: mock it as core bus tests do."""
        mock_wsrequest = MagicMock()
        mock_wsrequest.session.uid = user.id
        with patch("odoo.addons.bus.models.ir_websocket.wsrequest", new=mock_wsrequest):
            return (
                self.env["ir.websocket"]
                .with_user(user)
                ._build_bus_channel_list(list(channels))
            )

    def _spreadsheet_bus_tuple(self, dashboard):
        return (
            self.env.registry.db_name,
            "spreadsheet.dashboard",
            dashboard.id,
            "spreadsheet_oca",
        )

    def test_websocket_portal_assigned_channel_dropped(self):
        """The spreadsheet_oca channel streams raw revisions (formulas, pivot
        models and domains). Even with an active assignment a portal user
        must not be subscribed, and must not get AccessDenied either (that
        would kill the session's whole bus subscription)."""
        self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        channel = f"spreadsheet_oca;spreadsheet.dashboard;{self.dashboard.id}"
        try:
            result = self._build_channels_as(self.portal_user, [channel, "other"])
        except AccessDenied:
            self.fail("A spreadsheet channel must be dropped, not denied.")
        self.assertNotIn(channel, result)
        self.assertNotIn(self._spreadsheet_bus_tuple(self.dashboard), result)
        # Unrelated channels are untouched.
        self.assertIn("other", result)

    def test_websocket_portal_unassigned_dropped(self):
        """A portal user without an assignment gets the channel silently
        dropped (no tuple, no AccessDenied)."""
        channel = f"spreadsheet_oca;spreadsheet.dashboard;{self.other_dashboard.id}"
        try:
            result = self._build_channels_as(self.portal_user, [channel])
        except AccessDenied:
            self.fail("Unassigned portal channel must be dropped, not denied.")
        self.assertNotIn(channel, result)
        self.assertNotIn(self._spreadsheet_bus_tuple(self.other_dashboard), result)

    def test_websocket_internal_user_keeps_spreadsheet_channel(self):
        """The filter only targets non-internal users: an internal user who
        can read the dashboard still joins its collaborative channel."""
        channel = f"spreadsheet_oca;spreadsheet.dashboard;{self.dashboard.id}"
        result = self._build_channels_as(self.dashboard_manager, [channel])
        self.assertIn(self._spreadsheet_bus_tuple(self.dashboard), result)


@tagged("post_install", "-at_install")
class TestPortalDashboardHttp(PortalDashboardCommon, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_portal_dashboard_data()

    def _data_url(self, assignment):
        return f"/my/dashboards/{assignment.id}/data"

    def test_portal_user_gets_active_assignment_data(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        self.authenticate(self.portal_user.login, self.portal_user.login)
        result = self.make_jsonrpc_request(self._data_url(assignment))
        self.assertNotIn("error", result)
        self.assertIn("spreadsheet_raw", result)
        self.assertNotIn("revisions", result)

        response = self.url_open("/my/dashboards")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sales Dashboard", response.text)

    def test_archived_assignment_data_denied(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
                "active": False,
            }
        )
        self.authenticate(self.portal_user.login, self.portal_user.login)
        result = self.make_jsonrpc_request(self._data_url(assignment))
        self.assertIn("error", result)
        self.assertNotIn("spreadsheet_raw", result)
        # The detail page does not bounce silently: the list explains why.
        response = self.url_open(f"/my/dashboards/{assignment.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/my/dashboards?unavailable=1", response.url)
        self.assertIn("is no longer available", response.text)

    def test_my_home_dashboards_card(self):
        """/my renders (the pre-19.4 card inherit crashed it) and the
        portal.entry card gets its counter from /my/counters."""
        entry = self.env.ref(f"{MODULE}.portal_entry_dashboards")
        self.assertEqual(entry.url, "/my/dashboards")
        self.assertEqual(entry.placeholder_count, "portal_dashboard_count")
        self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        self.authenticate(self.portal_user.login, self.portal_user.login)
        response = self.url_open("/my")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/my/dashboards"', response.text)
        counters = self.make_jsonrpc_request(
            "/my/counters", {"counters": ["portal_dashboard_count"]}
        )
        self.assertEqual(counters.get("portal_dashboard_count"), 1)

    def test_internal_user_outside_group_denied_with_all_portal_users(self):
        assignment = self.PortalDash.create(
            {"dashboard_id": self.restricted_dashboard.id, "all_portal_users": True}
        )
        self.authenticate(self.internal_user.login, self.internal_user.login)
        result = self.make_jsonrpc_request(self._data_url(assignment))
        self.assertIn("error", result)
        self.assertNotIn("spreadsheet_raw", result)
