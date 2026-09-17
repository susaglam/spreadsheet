# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestSaveAsTemplateAccess(TransactionCase):
    """'Save as Template' is reserved for Template Managers.

    A plain spreadsheet user must get a teaching UserError (what / why / how),
    never Odoo's raw AccessError on spreadsheet.template. Note that
    AccessError is a subclass of UserError, so every test asserts the exact
    exception type — ``assertRaises(UserError)`` alone would also pass on the
    raw AccessError this suite guards against.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.raw_data = {
            "sheets": [{"id": "sheet1", "name": "Budget"}],
            "revisionId": "START_REVISION",
        }
        cls.plain_user = new_test_user(
            cls.env,
            login="tmpl_plain_saver",
            groups="base.group_user,spreadsheet_oca.group_user",
        )
        cls.manager = new_test_user(
            cls.env,
            login="tmpl_manager_saver",
            groups="base.group_user,spreadsheet_template_oca.group_template_manager",
        )
        cls.plain_spreadsheet = cls.env["spreadsheet.spreadsheet"].create(
            {
                "name": "Plain user budget",
                "owner_id": cls.plain_user.id,
                "spreadsheet_raw": cls.raw_data,
            }
        )
        cls.manager_spreadsheet = cls.env["spreadsheet.spreadsheet"].create(
            {
                "name": "Manager budget",
                "owner_id": cls.manager.id,
                "spreadsheet_raw": cls.raw_data,
            }
        )

    def _assert_teaching_error(self, exception):
        self.assertIs(
            type(exception),
            UserError,
            f"Expected the wizard's teaching UserError, got {type(exception)}",
        )
        self.assertNotIsInstance(exception, AccessError)
        message = str(exception)
        # The message content IS the feature under test, so the language is
        # pinned to en_US by the callers (see field manual: assert message
        # content only when the content is the feature).
        self.assertIn("reserved for Template Managers", message)  # what
        self.assertIn("shared with every spreadsheet user", message)  # why
        self.assertIn("Template Manager' access right", message)  # how

    def test_plain_user_cannot_open_wizard_gets_teaching_error(self):
        """Opening the dialog (default_get) already teaches the plain user."""
        self.assertFalse(
            self.env["spreadsheet.template"]
            .with_user(self.plain_user)
            .has_access("create")
        )
        wizard_model = (
            self.env["spreadsheet.to.template"]
            .with_user(self.plain_user)
            .with_context(lang="en_US")
        )
        with self.assertRaises(UserError) as caught:
            wizard_model.create({"spreadsheet_id": self.plain_spreadsheet.id})
        self._assert_teaching_error(caught.exception)

    def test_plain_user_create_template_gets_teaching_error(self):
        """create_template re-checks, even when the dialog was bypassed."""
        wizard = self.env["spreadsheet.to.template"].create(
            {"spreadsheet_id": self.plain_spreadsheet.id, "name": "Sneaky"}
        )
        templates_before = self.env["spreadsheet.template"].search_count([])
        with self.assertRaises(UserError) as caught:
            wizard.with_user(self.plain_user).with_context(
                lang="en_US"
            ).create_template()
        self._assert_teaching_error(caught.exception)
        self.assertEqual(
            self.env["spreadsheet.template"].search_count([]), templates_before
        )

    def test_manager_can_save_spreadsheet_as_template(self):
        wizard = (
            self.env["spreadsheet.to.template"]
            .with_user(self.manager)
            .create(
                {
                    "spreadsheet_id": self.manager_spreadsheet.id,
                    "description": "Yearly budget layout",
                }
            )
        )
        # Name is precomputed from the spreadsheet name.
        self.assertEqual(wizard.name, "Manager budget")
        action = wizard.create_template()
        self.assertEqual(action["params"]["type"], "success")
        next_action = action["params"]["next"]
        self.assertEqual(next_action["params"]["model"], "spreadsheet.template")
        template = self.env["spreadsheet.template"].browse(
            next_action["params"]["spreadsheet_id"]
        )
        self.assertTrue(template.exists())
        self.assertEqual(template.name, "Manager budget")
        self.assertEqual(template.description, "Yearly budget layout")
        self.assertEqual(template.create_uid, self.manager)
        self.assertEqual(
            template.get_spreadsheet_data()["spreadsheet_raw"], self.raw_data
        )
