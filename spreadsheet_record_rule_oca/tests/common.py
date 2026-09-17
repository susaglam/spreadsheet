# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase, new_test_user

VIEWER_PASSWORD = "rr-viewer-pass-2026"


def build_snapshot():
    """A spreadsheet that passes the core data validator run in test mode.

    One Odoo pivot and one Odoo chart on res.partner, one Odoo list on
    res.partner with its own domain, and one list on res.users (no rule).
    """
    return {
        "sheets": [
            {
                "id": "sheet1",
                "name": "Sheet1",
                "figures": [
                    {
                        "id": "figure1",
                        "tag": "chart",
                        "data": {
                            "type": "odoo_bar",
                            "metaData": {
                                "resModel": "res.partner",
                                "groupBy": [],
                                "measure": "__count",
                            },
                            "searchParams": {"groupBy": [], "domain": []},
                        },
                    }
                ],
            }
        ],
        "pivots": {
            "1": {
                "type": "ODOO",
                "name": "Partners",
                "model": "res.partner",
                "domain": [],
                "columns": [],
                "rows": [],
                "measures": [{"id": "__count", "fieldName": "__count"}],
            }
        },
        "lists": {
            "1": {
                "name": "Companies",
                "model": "res.partner",
                "domain": [["is_company", "=", True]],
                "columns": [],
                "orderBy": [],
            },
            "2": {
                "name": "Users",
                "model": "res.users",
                "domain": [],
                "columns": [],
                "orderBy": [],
            },
        },
    }


class DashboardRuleCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env["spreadsheet.dashboard.rule"]
        cls.Dashboard = cls.env["spreadsheet.dashboard"]
        dashboard_group = cls.env["spreadsheet.dashboard.group"].create(
            {"name": "Record Rule Test Section"}
        )
        # group_ids defaults to base.group_user: every internal user may read it.
        cls.dashboard = cls.Dashboard.create(
            {
                "name": "Record Rule Test Dashboard",
                "dashboard_group_id": dashboard_group.id,
            }
        )
        cls.dashboard.spreadsheet_raw = build_snapshot()
        # A plain internal user: no spreadsheet group, so no read access on
        # the rule model itself, and no write access on the dashboard.
        cls.viewer = new_test_user(
            cls.env,
            login="rr_viewer",
            groups="base.group_user",
            password=VIEWER_PASSWORD,
        )
        cls.dashboard_manager = new_test_user(
            cls.env,
            login="rr_dashboard_manager",
            groups="base.group_user,spreadsheet_dashboard.group_dashboard_manager",
        )
        cls.spreadsheet_manager = new_test_user(
            cls.env,
            login="rr_spreadsheet_manager",
            groups="base.group_user,spreadsheet_oca.group_manager",
        )

    @classmethod
    def create_rule(cls, domain, model="res.partner", **values):
        return cls.Rule.create(
            {
                "name": values.pop("name", "Test rule"),
                "dashboard_id": cls.dashboard.id,
                "model_name": model,
                "domain_extension": domain,
                **values,
            }
        )

    def force_domain(self, rule, domain):
        """Store a domain bypassing the constraint (legacy / broken data)."""
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE spreadsheet_dashboard_rule SET domain_extension = %s WHERE id = %s",
            (domain, rule.id),
        )
        rule.invalidate_recordset()
