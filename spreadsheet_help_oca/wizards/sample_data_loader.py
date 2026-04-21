# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, fields, models


class SampleDataLoader(models.TransientModel):
    _name = "spreadsheet.sample.data.loader"
    _description = "Load Sample / Demo Data for Spreadsheet Modules"

    what_to_load = fields.Selection(
        [
            ("template", "Template ornekleri"),
            ("kpi_alert", "KPI Alert ornekleri"),
            ("contract", "Sozlesme + SLA ornekleri"),
            ("vendor", "Tedarikci karnesi ornekleri"),
            ("all", "Hepsi (Full Demo)"),
        ],
        required=True,
        default="all",
        string="Ne yuklensin?",
    )

    def action_load(self):
        self.ensure_one()
        report = []
        if self.what_to_load in ("template", "all"):
            report.append(self._load_templates())
        if self.what_to_load in ("kpi_alert", "all"):
            report.append(self._load_kpi_alerts())
        if self.what_to_load in ("contract", "all"):
            report.append(self._load_contracts())
        if self.what_to_load in ("vendor", "all"):
            report.append(self._load_vendors())

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Ornek veri yuklendi"),
                "message": " | ".join(filter(None, report)) or _("Zaten mevcut"),
                "type": "success",
                "sticky": False,
            },
        }

    def _load_templates(self):
        Template = self.env["spreadsheet.template"]
        if Template.search_count([("name", "like", "ORNEK%")]) > 0:
            return ""
        cat_sales = self.env.ref(
            "spreadsheet_template_oca.category_sales", raise_if_not_found=False
        )
        Template.create(
            {
                "name": "ORNEK - Sample Data ile uretilen sablon",
                "description": "Sample Data Loader ile olusturuldu. Silinebilir.",
                "category_id": cat_sales.id if cat_sales else False,
            }
        )
        return _("1 sablon eklendi")

    def _load_kpi_alerts(self):
        Alert = self.env["spreadsheet.kpi.alert"]
        if Alert.search_count([("name", "like", "ORNEK%")]) > 0:
            return ""
        # Find a spreadsheet to anchor on
        sheet = self.env["spreadsheet.spreadsheet"].search([], limit=1)
        if not sheet:
            return ""
        Alert.create(
            {
                "name": "ORNEK - Sample KPI Alert",
                "spreadsheet_id": sheet.id,
                "sheet_name": "Sheet1",
                "cell_ref": "B2",
                "operator": ">",
                "threshold_value": 1000,
                "last_value": 1200,
            }
        )
        return _("1 KPI alert eklendi")

    def _load_contracts(self):
        if "spreadsheet.contract" not in self.env:
            return ""
        Contract = self.env["spreadsheet.contract"]
        if Contract.search_count([("name", "like", "ORNEK%")]) > 0:
            return ""
        partner = self.env["res.partner"].search([("is_company", "=", True)], limit=1)
        if not partner:
            return ""
        today = fields.Date.context_today(self)
        contract = Contract.create(
            {
                "name": "ORNEK - Sample Sozlesme",
                "partner_id": partner.id,
                "contract_type": "service",
                "date_start": today,
                "date_end": today.replace(year=today.year + 1),
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
        return _("1 sozlesme + 1 SLA eklendi")

    def _load_vendors(self):
        if "spreadsheet.vendor.scorecard" not in self.env:
            return ""
        Scorecard = self.env["spreadsheet.vendor.scorecard"]
        if Scorecard.search_count([("notes", "like", "ORNEK%")]) > 0:
            return ""
        vendor = self.env["res.partner"].search([("supplier_rank", ">", 0)], limit=1)
        if not vendor:
            vendor = self.env["res.partner"].create(
                {
                    "name": "ORNEK Tedarikci",
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
                "notes": "ORNEK - Sample scorecard",
            }
        )
        return _("1 vendor scorecard eklendi")
