# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import importlib.util
import os

from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged

MIGRATION_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "migrations",
    "saas~19.4.1.0.1",
    "post-migrate.py",
)
FIXED_GROUP_EXPR = "user.all_group_ids.ids"
PRE_FIX_GROUP_EXPR = "user.group_ids.ids"


@tagged("post_install", "-at_install")
class TestPostMigrate(TransactionCase):
    """saas~19.4.1.0.1 post-migrate repairs a pre-fix database, idempotently."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        spec = importlib.util.spec_from_file_location(
            "spreadsheet_oca_post_migrate_saas_19_4_1_0_1", MIGRATION_PATH
        )
        cls.migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.migration)

    def _migrate(self):
        self.migration.migrate(self.env.cr, "saas~19.4.1.0.0")
        self.env.invalidate_all()

    def _revision(self, model, res_id):
        return self.env["spreadsheet.oca.revision"].create(
            {
                "model": model,
                "res_id": res_id,
                "type": "REMOTE_REVISION",
                "commands": '{"type": "REMOTE_REVISION", "commands": []}',
            }
        )

    def _state(self):
        group_manager = self.env.ref("spreadsheet_oca.group_manager")
        return (
            group_manager.with_context(active_test=False).user_ids,
            self.env.ref("spreadsheet_oca.access_spreadsheet_oca_revision").group_id,
            tuple(
                self.env.ref(xmlid).domain
                for xmlid in self.migration.GROUP_SHARING_ACCESSES
            ),
            self.env["spreadsheet.oca.revision"].search([]),
        )

    def test_repairs_pre_fix_database_and_is_idempotent(self):
        group_manager = self.env.ref("spreadsheet_oca.group_manager")
        admin = self.env.ref("base.user_admin")
        employee_group = self.env.ref("base.group_user")
        revision_access = self.env.ref(
            "spreadsheet_oca.access_spreadsheet_oca_revision"
        )
        reader_rule = self.env.ref("spreadsheet_oca.spreadsheet_reader_rule")

        # Simulate a database installed before the fix.
        group_manager.write({"user_ids": [Command.unlink(admin.id)]})
        revision_access.group_id = employee_group
        reader_rule.domain = reader_rule.domain.replace(
            FIXED_GROUP_EXPR, PRE_FIX_GROUP_EXPR
        )
        Spreadsheet = self.env["spreadsheet.spreadsheet"]
        kept_sheet = Spreadsheet.create({"name": "Kept"})
        deleted_sheet = Spreadsheet.create({"name": "Deleted"})
        deleted_id = deleted_sheet.id
        deleted_sheet.unlink()
        kept_revision = self._revision("spreadsheet.spreadsheet", kept_sheet.id)
        orphan_revision = self._revision("spreadsheet.spreadsheet", deleted_id)
        # A model that is not loaded cannot be verified: never deleted.
        unverifiable_revision = self._revision("spreadsheet.not.loaded", 1)
        self.assertNotIn(admin, group_manager.user_ids)

        self._migrate()

        self.assertIn(admin, group_manager.user_ids)
        self.assertEqual(revision_access.group_id, self.env.ref("base.group_system"))
        self.assertIn(FIXED_GROUP_EXPR, reader_rule.domain)
        self.assertNotIn(PRE_FIX_GROUP_EXPR, reader_rule.domain)
        self.assertTrue(kept_revision.exists())
        self.assertFalse(orphan_revision.exists())
        self.assertTrue(unverifiable_revision.exists())

        # A second run finds nothing to repair and changes nothing.
        state = self._state()
        self._migrate()
        self.assertEqual(self._state(), state)

    def test_already_fixed_database_is_left_untouched(self):
        state = self._state()
        self._migrate()
        self.assertEqual(self._state(), state)
        # Only runs on upgrades, never on install.
        self.migration.migrate(self.env.cr, None)
        self.assertEqual(self._state(), state)
