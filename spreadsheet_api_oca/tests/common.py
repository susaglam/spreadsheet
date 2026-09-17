# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import new_test_user

from ..tools.rate_limit import FAILED_AUTH_LIMITER, TOKEN_LIMITER


class SpreadsheetApiCommonMixin:
    @classmethod
    def _setup_api_data(cls):
        cls.Token = cls.env["spreadsheet.api.token"]
        cls.Event = cls.env["spreadsheet.api.webhook.event"]
        cls.Spreadsheet = cls.env["spreadsheet.spreadsheet"]
        cls.sheet_user = new_test_user(
            cls.env,
            login="api_sheet_user",
            groups="base.group_user,spreadsheet_oca.group_user",
        )
        cls.other_sheet_user = new_test_user(
            cls.env,
            login="api_other_sheet_user",
            groups="base.group_user,spreadsheet_oca.group_user",
        )
        cls.sheet_manager = new_test_user(
            cls.env,
            login="api_sheet_manager",
            groups="base.group_user,spreadsheet_oca.group_manager",
        )
        cls.portal_user = new_test_user(
            cls.env, login="api_portal_user", groups="base.group_portal"
        )

    def setUp(self):
        super().setUp()
        # The limiters are process-wide: start every test from a clean slate.
        TOKEN_LIMITER.reset()
        FAILED_AUTH_LIMITER.reset()
