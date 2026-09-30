# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from dateutil.relativedelta import relativedelta

from odoo import fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

# Every record created by the loader starts with this prefix so it is easy to
# find and delete. Databases that ran the loader before the English rewrite
# carry the legacy prefix: both are checked so a rerun never duplicates them.
SAMPLE_PREFIX = "SAMPLE"
LEGACY_SAMPLE_PREFIX = "ORNEK"


def _sample_domain(field_name):
    return [
        "|",
        (field_name, "=like", f"{SAMPLE_PREFIX}%"),
        (field_name, "=like", f"{LEGACY_SAMPLE_PREFIX}%"),
    ]


class SampleDataLoader(models.TransientModel):
    _name = "spreadsheet.sample.data.loader"
    _description = "Load Sample / Demo Data for Spreadsheet Modules"

    what_to_load = fields.Selection(
        [
            ("all", "Everything (full demo)"),
            ("template", "Template examples"),
            ("kpi_alert", "KPI alert examples"),
            ("contract", "Contract + SLA examples"),
            ("vendor", "Vendor scorecard examples"),
        ],
        required=True,
        default="all",
        string="What to load",
        help="Which demo records to create. 'Everything' loads examples for every "
        "installed spreadsheet module; modules that are not installed are "
        "skipped. Every record name starts with 'SAMPLE' so you can find and "
        "delete it afterwards.",
    )

    def action_load(self):
        self.ensure_one()
        loaders = [
            ("template", self._load_templates),
            ("kpi_alert", self._load_kpi_alerts),
            ("contract", self._load_contracts),
            ("vendor", self._load_vendors),
        ]
        labels = dict(self._fields["what_to_load"]._description_selection(self.env))
        report = []
        failures = []
        for key, loader in loaders:
            if self.what_to_load not in (key, "all"):
                continue
            try:
                with self.env.cr.savepoint():
                    report.append(loader())
            except AccessError:
                # The technical error stays in the log; the user gets the remedy.
                _logger.info("Sample data loader %s: access denied", key, exc_info=True)
                failures.append(
                    self.env._(
                        "%(examples)s (your access rights do not allow creating "
                        "them; a Spreadsheet manager can run the loader)",
                        examples=labels.get(key, key),
                    )
                )
            except Exception:  # one broken optional module must not
                # block the other examples (graceful degradation)
                _logger.warning("Sample data loader %s failed", key, exc_info=True)
                failures.append(labels.get(key, key))

        loaded = " | ".join(filter(None, report))
        if failures:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Some sample data could not be loaded"),
                    "message": self.env._(
                        "Loaded: %(loaded)s. Not loaded: %(failed)s. These examples "
                        "were skipped and nothing else was changed. The server log "
                        "has the technical details: fix the problem (for example a "
                        "missing access right or required setting) and run the "
                        "loader again.",
                        loaded=loaded or self.env._("nothing"),
                        failed="; ".join(failures),
                    ),
                    "type": "warning",
                    "sticky": True,
                },
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Sample data loaded"),
                "message": loaded
                or self.env._(
                    "Nothing new to load: the sample records already exist or the "
                    "related modules are not installed."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def _load_templates(self):
        if "spreadsheet.template" not in self.env:
            return ""
        Template = self.env["spreadsheet.template"]
        if Template.search_count(_sample_domain("name")) > 0:
            return ""
        cat_sales = self.env.ref(
            "spreadsheet_template_oca.category_sales", raise_if_not_found=False
        )
        Template.create(
            {
                "name": f"{SAMPLE_PREFIX} - Template created by the Sample Data Loader",
                "description": "Created by the Sample Data Loader. Safe to delete.",
                "category_id": cat_sales.id if cat_sales else False,
            }
        )
        return self.env._("1 template added")

    def _load_kpi_alerts(self):
        if "spreadsheet.kpi.alert" not in self.env:
            return ""
        Alert = self.env["spreadsheet.kpi.alert"]
        if Alert.search_count(_sample_domain("name")) > 0:
            return ""
        sheet = self._get_kpi_anchor_spreadsheet()
        if not sheet:
            return ""
        Alert.create(
            {
                "name": f"{SAMPLE_PREFIX} - KPI Alert",
                "spreadsheet_id": sheet.id,
                "sheet_name": "Sheet1",
                "cell_ref": "B2",
                "operator": ">",
                "threshold_value": 1000,
                "last_value": 1200,
            }
        )
        return self.env._("1 KPI alert added")

    def _get_kpi_anchor_spreadsheet(self):
        """Spreadsheet the sample KPI alert watches.

        Never one of the Help guides: they are shared read-only with every
        Spreadsheet user, so a sample alert there would sit on a reference
        sheet ordinary users cannot edit. The user's own spreadsheet comes
        first, then any spreadsheet the user may edit. Returns an empty
        recordset when there is none.
        """
        Spreadsheet = self.env["spreadsheet.spreadsheet"]
        guide_ids = self.env["spreadsheet.tutorial"]._get_guide_spreadsheet_ids()
        domain = [("id", "not in", guide_ids)]
        sheet = Spreadsheet.search(domain + [("owner_id", "=", self.env.uid)], limit=1)
        if not sheet:
            sheet = Spreadsheet.search(domain, limit=50)._filtered_access("write")[:1]
        return sheet

    def _load_contracts(self):
        if "spreadsheet.contract" not in self.env:
            return ""
        Contract = self.env["spreadsheet.contract"]
        if Contract.search_count(_sample_domain("name")) > 0:
            return ""
        partner = self.env["res.partner"].search([("is_company", "=", True)], limit=1)
        if not partner:
            return ""
        today = fields.Date.context_today(self)
        contract = Contract.create(
            {
                "name": f"{SAMPLE_PREFIX} - Service Contract",
                "partner_id": partner.id,
                "contract_type": "service",
                "date_start": today,
                "date_end": today + relativedelta(years=1),
                "amount": 5000,
                "responsible_id": self.env.uid,
            }
        )
        self.env["spreadsheet.contract.sla"].create(
            {
                "name": "Uptime",
                "contract_id": contract.id,
                "target_value": 99.9,
                "actual_value": 99.95,
                "unit": "%",
            }
        )
        return self.env._("1 contract + 1 SLA added")

    def _load_vendors(self):
        if "spreadsheet.vendor.scorecard" not in self.env:
            return ""
        Scorecard = self.env["spreadsheet.vendor.scorecard"]
        if Scorecard.search_count(_sample_domain("notes")) > 0:
            return ""
        vendor = self.env["res.partner"].search([("supplier_rank", ">", 0)], limit=1)
        if not vendor:
            vendor = self.env["res.partner"].create(
                {
                    "name": f"{SAMPLE_PREFIX} Supplier",
                    "supplier_rank": 1,
                    "is_company": True,
                }
            )
        Scorecard.create(
            {
                "partner_id": vendor.id,
                "date": fields.Date.context_today(self),
                "on_time_delivery_rate": 88,
                "quality_rate": 94,
                "avg_lead_time": 7,
                "total_orders": 15,
                "total_amount": 20000,
                "notes": f"{SAMPLE_PREFIX} - Sample scorecard",
            }
        )
        return self.env._("1 vendor scorecard added")
