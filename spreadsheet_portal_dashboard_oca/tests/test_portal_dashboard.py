# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import AccessDenied
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPortalDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.PortalDash = cls.env["spreadsheet.portal.dashboard"]

        # A dashboard group + two dashboards to assign.
        group = cls.env["spreadsheet.dashboard.group"].create({"name": "Test Group"})
        cls.dashboard = cls.env["spreadsheet.dashboard"].create(
            {"name": "Sales Dashboard", "dashboard_group_id": group.id}
        )
        cls.other_dashboard = cls.env["spreadsheet.dashboard"].create(
            {"name": "Ops Dashboard", "dashboard_group_id": group.id}
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

        # Portal user bound to the child contact partner.
        cls.portal_group = cls.env.ref("base.group_portal")
        cls.portal_user = cls.env["res.users"].create(
            {
                "name": "Portal Dealer",
                "login": "portal_dealer_test",
                "email": "portal_dealer_test@example.com",
                "partner_id": cls.child_partner.id,
                "group_ids": [(6, 0, [cls.portal_group.id])],
            }
        )

    def test_all_portal_users_grants_access(self):
        assignment = self.PortalDash.create(
            {"dashboard_id": self.dashboard.id, "all_portal_users": True}
        )
        self.assertTrue(assignment._is_accessible_by_partner(self.stranger))
        self.assertTrue(assignment._is_accessible_by_partner(self.child_partner))

    def test_direct_partner_match(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        self.assertTrue(assignment._is_accessible_by_partner(self.child_partner))

    def test_commercial_partner_match(self):
        # Assign to the company; the child contact must still get access via
        # its commercial_partner_id.
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.company_partner.id])],
            }
        )
        self.assertTrue(assignment._is_accessible_by_partner(self.child_partner))

    def test_unassigned_partner_denied(self):
        assignment = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.company_partner.id])],
            }
        )
        self.assertFalse(assignment._is_accessible_by_partner(self.stranger))

    def test_get_portal_dashboards_filters_inactive_and_scope(self):
        accessible = self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        inactive = self.PortalDash.create(
            {
                "dashboard_id": self.other_dashboard.id,
                "all_portal_users": True,
                "active": False,
            }
        )
        result = self.PortalDash._get_portal_dashboards(self.child_partner)
        self.assertIn(accessible, result)
        self.assertNotIn(inactive, result)
        # A stranger sees none of the partner-scoped assignments.
        self.assertNotIn(
            accessible, self.PortalDash._get_portal_dashboards(self.stranger)
        )

    def test_websocket_portal_access_no_access_denied(self):
        """Regression guard: a portal user with an assigned dashboard must be
        able to build the bus channel list without triggering AccessDenied,
        and the raw spreadsheet_oca string must be replaced by a resolved tuple.
        """
        self.PortalDash.create(
            {
                "dashboard_id": self.dashboard.id,
                "partner_ids": [(6, 0, [self.child_partner.id])],
            }
        )
        channel = f"spreadsheet_oca;spreadsheet.dashboard;{self.dashboard.id}"
        ws = self.env["ir.websocket"].with_user(self.portal_user)
        try:
            result = ws._build_bus_channel_list([channel])
        except AccessDenied:
            self.fail(
                "Portal user with an assigned dashboard should not raise "
                "AccessDenied when subscribing to its bus channel."
            )
        # Raw string dropped; resolved tuple present.
        self.assertNotIn(channel, result)
        expected_tuple = (
            self.env.registry.db_name,
            "spreadsheet.dashboard",
            self.dashboard.id,
            "spreadsheet_oca",
        )
        self.assertIn(expected_tuple, result)

    def test_websocket_portal_unassigned_dropped(self):
        """A portal user without an assignment gets the channel silently
        dropped (no tuple, no AccessDenied)."""
        channel = f"spreadsheet_oca;spreadsheet.dashboard;{self.other_dashboard.id}"
        ws = self.env["ir.websocket"].with_user(self.portal_user)
        try:
            result = ws._build_bus_channel_list([channel])
        except AccessDenied:
            self.fail("Unassigned portal channel must be dropped, not denied.")
        self.assertNotIn(channel, result)
        dropped_tuple = (
            self.env.registry.db_name,
            "spreadsheet.dashboard",
            self.other_dashboard.id,
            "spreadsheet_oca",
        )
        self.assertNotIn(dropped_tuple, result)
