# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class SpreadsheetConsolidationProfile(models.Model):
    _name = "spreadsheet.consolidation.profile"
    _description = "Multi-Company Consolidation Profile"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_ids = fields.Many2many(
        "res.company",
        string="Companies to Consolidate",
        required=True,
    )
    elimination_account_ids = fields.Many2many(
        "account.account",
        string="Inter-Company Elimination Accounts",
        help="Accounts used for inter-company transactions. "
        "Balances on these accounts will be eliminated in the consolidated report.",
    )
    elimination_partner_ids = fields.Many2many(
        "res.partner",
        string="Inter-Company Partners",
        help="Partner records representing inter-company entities. "
        "Transactions between these partners are eliminated.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Consolidation Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    def action_generate_report(self):
        """Generate a consolidated report and open it in a new spreadsheet."""
        self.ensure_one()
        data = self._compute_consolidation_data()

        # Create a spreadsheet with the consolidated data
        spreadsheet = self.env["spreadsheet.spreadsheet"].create(
            {
                "name": self.env._("Consolidated Report - %(name)s", name=self.name),
                "spreadsheet_raw": self._build_spreadsheet_data(data),
            }
        )
        return spreadsheet.open_spreadsheet()

    def _compute_consolidation_data(self):
        """Compute consolidated financial data across all companies."""
        self.ensure_one()
        result = {
            "companies": [],
            "accounts": {},
            "consolidated": {},
            "eliminations": {},
        }

        for company in self.company_ids:
            company_data = {"id": company.id, "name": company.name, "accounts": {}}

            # Get account balances for this company
            # saas-19.2: account.account.company_id -> company_ids (M2M, multi-company)
            accounts = (
                self.env["account.account"]
                .with_company(company)
                .search([("company_ids", "=", company.id)])
            )

            for account in accounts:
                balance = account.current_balance
                if self.currency_id != company.currency_id:
                    balance = company.currency_id._convert(
                        balance,
                        self.currency_id,
                        company,
                        fields.Date.context_today(self),
                    )

                key = account.code
                company_data["accounts"][key] = {
                    "name": account.name,
                    "code": account.code,
                    "balance": balance,
                }

                # Accumulate in consolidated
                if key not in result["consolidated"]:
                    result["consolidated"][key] = {
                        "name": account.name,
                        "code": account.code,
                        "balance": 0,
                    }
                result["consolidated"][key]["balance"] += balance

            result["companies"].append(company_data)

        # Calculate eliminations
        for account in self.elimination_account_ids:
            key = account.code
            if key in result["consolidated"]:
                result["eliminations"][key] = {
                    "name": account.name,
                    "code": account.code,
                    "balance": -result["consolidated"][key]["balance"],
                }
                result["consolidated"][key]["balance"] = 0

        return result

    def _build_spreadsheet_data(self, data):
        """Build o-spreadsheet JSON from consolidation data."""
        cells = {}
        styles = {
            "1": {"bold": True, "fontSize": 14, "textColor": "#01666b"},
            "2": {"bold": True, "fillColor": "#f0f0f0"},
            "3": {"fillColor": "#f2f2f2"},
        }

        # Header row
        col = 0
        cells["A1"] = {"style": 1, "content": "Account"}
        cells["B1"] = {"style": 1, "content": "Code"}
        col = 2
        for comp in data["companies"]:
            col_letter = chr(65 + col)
            cells[f"{col_letter}1"] = {"style": 1, "content": comp["name"]}
            col += 1
        elim_col = chr(65 + col)
        cells[f"{elim_col}1"] = {"style": 1, "content": "Eliminations"}
        cons_col = chr(65 + col + 1)
        cells[f"{cons_col}1"] = {"style": 1, "content": "Consolidated"}

        # Data rows
        row = 2
        all_codes = sorted(data["consolidated"].keys())
        for code in all_codes:
            account = data["consolidated"][code]
            style_id = "3" if row % 2 == 0 else None

            cells[f"A{row}"] = {"content": account["name"]}
            cells[f"B{row}"] = {"content": code}
            if style_id:
                cells[f"A{row}"]["style"] = 3
                cells[f"B{row}"]["style"] = 3

            col = 2
            for comp in data["companies"]:
                col_letter = chr(65 + col)
                comp_balance = comp["accounts"].get(code, {}).get("balance", 0)
                cells[f"{col_letter}{row}"] = {"content": str(round(comp_balance, 2))}
                if style_id:
                    cells[f"{col_letter}{row}"]["style"] = 3
                col += 1

            # Elimination
            elim_balance = data["eliminations"].get(code, {}).get("balance", 0)
            cells[f"{elim_col}{row}"] = {"content": str(round(elim_balance, 2))}

            # Consolidated total
            cells[f"{cons_col}{row}"] = {
                "style": 2,
                "content": str(round(account["balance"] + elim_balance, 2)),
            }

            row += 1

        return {
            "version": 12,
            "sheets": [
                {
                    "id": "sheet1",
                    "name": "Consolidated",
                    "colNumber": col + 3,
                    "rowNumber": row + 10,
                    "rows": {},
                    "cols": {"0": {"size": 200}, "1": {"size": 80}},
                    "merges": [],
                    "cells": cells,
                    "figures": [],
                    "areGridLinesVisible": True,
                    "headerGroups": {"ROW": [], "COL": []},
                }
            ],
            "entities": {},
            "styles": styles,
            "formats": {},
            "borders": {},
            "revisionId": "START_REVISION",
            "settings": {
                "locale": {
                    "name": "English (US)",
                    "code": "en_US",
                    "thousandsSeparator": ",",
                    "decimalSeparator": ".",
                    "dateFormat": "m/d/yyyy",
                    "timeFormat": "hh:mm:ss a",
                    "formulaArgSeparator": ",",
                }
            },
            "chartOdooMenusReferences": {},
            "odooVersion": 4,
            "lists": {},
            "listNextId": 1,
            "pivots": {},
            "pivotNextId": 1,
            "globalFilters": [],
        }
