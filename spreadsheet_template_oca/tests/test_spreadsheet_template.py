# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestSpreadsheetTemplate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.raw_data = {
            "sheets": [{"id": "sheet1", "name": "Test"}],
            "revisionId": "START_REVISION",
        }
        # Unique name so it cannot collide with the module's shipped
        # spreadsheet.template.category demo/data records (which also has "Sales").
        cls.category = cls.env["spreadsheet.template.category"].create(
            {"name": "Test Sales (unit)"}
        )
        cls.template = cls.env["spreadsheet.template"].create(
            {
                "name": "Monthly Sales Report",
                "category_id": cls.category.id,
                "spreadsheet_raw": cls.raw_data,
            }
        )

    def _create_spreadsheet_from(self, template):
        wizard = self.env["spreadsheet.from.template"].create(
            {"template_id": template.id}
        )
        action = wizard.create_spreadsheet()
        spreadsheet_id = action["params"]["spreadsheet_id"]
        return self.env["spreadsheet.spreadsheet"].browse(spreadsheet_id)

    def test_create_spreadsheet_from_template_copies_raw_data(self):
        spreadsheet = self._create_spreadsheet_from(self.template)
        self.assertTrue(spreadsheet.exists())
        self.assertEqual(
            spreadsheet.get_spreadsheet_data()["spreadsheet_raw"],
            self.template.get_spreadsheet_data()["spreadsheet_raw"],
        )

    def test_create_spreadsheet_default_name_from_template(self):
        wizard = self.env["spreadsheet.from.template"].create(
            {"template_id": self.template.id}
        )
        # The name is computed/precomputed from the template name.
        self.assertEqual(wizard.name, self.template.name)

    def test_usage_count_increments_on_use(self):
        self.assertEqual(self.template.usage_count, 0)
        self._create_spreadsheet_from(self.template)
        self.assertEqual(self.template.usage_count, 1)
        self._create_spreadsheet_from(self.template)
        self.assertEqual(self.template.usage_count, 2)

    def test_create_template_sets_category_and_description(self):
        spreadsheet = self.env["spreadsheet.spreadsheet"].create(
            {"name": "Source", "spreadsheet_raw": self.raw_data}
        )
        wizard = self.env["spreadsheet.to.template"].create(
            {
                "spreadsheet_id": spreadsheet.id,
                "name": "New Template",
                "description": "A reusable layout",
                "category_id": self.category.id,
            }
        )
        action = wizard.create_template()
        new_template = self.env["spreadsheet.template"].browse(
            action["params"]["next"]["params"]["spreadsheet_id"]
        )
        self.assertEqual(new_template.name, "New Template")
        self.assertEqual(new_template.description, "A reusable layout")
        self.assertEqual(new_template.category_id, self.category)
        self.assertEqual(
            new_template.get_spreadsheet_data()["spreadsheet_raw"],
            self.raw_data,
        )

    def test_compute_template_count(self):
        cat = self.env["spreadsheet.template.category"].create({"name": "HR"})
        self.assertEqual(cat.template_count, 0)
        self.env["spreadsheet.template"].create(
            {"name": "T1", "category_id": cat.id, "spreadsheet_raw": self.raw_data}
        )
        self.env["spreadsheet.template"].create(
            {"name": "T2", "category_id": cat.id, "spreadsheet_raw": self.raw_data}
        )
        cat.invalidate_recordset(["template_ids", "template_count"])
        self.assertEqual(cat.template_count, 2)

    def test_category_name_must_be_unique(self):
        # UNIQUE(name) requires a real DB flush to surface the violation.
        from psycopg2 import IntegrityError

        from odoo.tools import mute_logger

        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                # Duplicate of the category created in setUpClass -> guaranteed
                # UNIQUE(name) violation without depending on shipped data.
                self.env["spreadsheet.template.category"].create(
                    {"name": "Test Sales (unit)"}
                )
                self.env.flush_all()

    def test_group_user_cannot_write_template(self):
        user = new_test_user(
            self.env,
            login="tmpl_reader",
            groups="spreadsheet_oca.group_user",
        )
        with self.assertRaises(AccessError):
            self.template.with_user(user).write({"name": "Hacked"})

    def test_template_manager_can_crud(self):
        user = new_test_user(
            self.env,
            login="tmpl_manager",
            groups="spreadsheet_template_oca.group_template_manager",
        )
        template = (
            self.env["spreadsheet.template"]
            .with_user(user)
            .create({"name": "Mgr Template", "spreadsheet_raw": self.raw_data})
        )
        template.write({"name": "Mgr Template Renamed"})
        self.assertEqual(template.name, "Mgr Template Renamed")
        template.unlink()
        self.assertFalse(template.exists())
