# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCrmPipelineDashboard(TransactionCase):
    """Validate the shipped CRM pipeline dashboard JSON against the real ORM.

    This guards the whole "scorecard points at a non-existent field" class of
    bug (e.g. the removed ``won_count`` measure): every pivot/list field and
    every global-filter field must resolve on its declared model, otherwise the
    dashboard renders ``#ERROR`` for the end user.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env.ref(
            "spreadsheet_dashboard_crm_oca.spreadsheet_dashboard_crm_pipeline"
        )

    def _load_json(self):
        # spreadsheet_raw is the computed dict form of the dashboard; use it
        # directly instead of base64-decoding the Binary field, whose read
        # return type changed in saas-19.4.
        return self.dashboard.spreadsheet_raw

    @staticmethod
    def _strip_granularity(field):
        # "create_date:month" -> "create_date"
        return field.split(":", 1)[0]

    def _assert_field(self, model, field, where):
        self.assertIn(
            model,
            self.env,
            f"{where} references unknown model {model!r}",
        )
        self.assertIn(
            field,
            self.env[model]._fields,
            f"{where} references unknown field {field!r} on {model}",
        )

    def test_binary_decodes_to_json(self):
        self.assertTrue(self.dashboard, "Dashboard record must exist")
        data = self._load_json()
        self.assertIsInstance(data, dict)
        self.assertIn("sheets", data)

    def test_pivot_fields_resolve(self):
        data = self._load_json()
        for pivot_id, pivot in data.get("pivots", {}).items():
            model = pivot["model"]
            for measure in pivot.get("measures", []):
                field = measure.get("field")
                if not field or field == "__count":
                    continue
                self._assert_field(model, field, f"pivot {pivot_id} measure")
            for group in pivot.get("rowGroupBys", []) + pivot.get("colGroupBys", []):
                self._assert_field(
                    model, self._strip_granularity(group), f"pivot {pivot_id} groupBy"
                )

    def test_list_fields_resolve(self):
        data = self._load_json()
        for list_id, lst in data.get("lists", {}).items():
            model = lst["model"]
            for column in lst.get("columns", []):
                self._assert_field(
                    model, self._strip_granularity(column), f"list {list_id} column"
                )

    def test_global_filter_fields_resolve(self):
        data = self._load_json()
        crm_lead = "crm.lead"
        for gf in data.get("globalFilters", []):
            # Field matchings for pivots/lists/charts all target crm.lead here.
            for key in ("pivotFields", "listFields", "graphFields"):
                for obj_id, match in gf.get(key, {}).items():
                    self._assert_field(
                        crm_lead,
                        match["field"],
                        "filter {} {}[{}]".format(gf["id"], key, obj_id),
                    )
            if gf.get("type") == "relation":
                self.assertIn(
                    gf["modelName"],
                    self.env,
                    "filter {} targets unknown model {!r}".format(
                        gf["id"], gf["modelName"]
                    ),
                )
