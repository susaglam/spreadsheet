# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class SpreadsheetConsolidationProfile(models.Model):
    _name = "spreadsheet.consolidation.profile"
    _description = "Multi-Company Consolidation Profile"
    _order = "name"

    name = fields.Char(
        required=True,
        help="A label for this consolidation setup. Example: Group Consolidation Q1.",
    )
    active = fields.Boolean(
        default=True,
        help="Uncheck to archive this profile: it disappears from the list but "
        "keeps its settings, so you can restore it later.",
    )
    company_ids = fields.Many2many(
        "res.company",
        string="Companies to Consolidate",
        required=True,
        help="The legal entities whose posted journal items are summed into this "
        "consolidation, one column per company. A branch that is not listed "
        "itself is included in the column of its parent company; list the "
        "branch as well to give it its own column. Example: pick the parent "
        "plus each subsidiary in the group report.",
    )
    elimination_account_ids = fields.Many2many(
        "account.account",
        string="Inter-Company Elimination Accounts",
        help="Accounts used for inter-company transactions. The report row with "
        "the code of a selected account is cancelled in the Eliminations column "
        "for all consolidated companies together; the code is looked up in the "
        "chart of accounts of each consolidated company. Example: select the "
        "inter-company receivable account 1100 of one group company, and the "
        "1100 balances of every consolidated company net out to zero.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Consolidation Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
        help="All company balances are converted to this currency before "
        "consolidating. Example: set EUR to report a mixed EUR/USD group in euros.",
    )

    def action_generate_report(self):
        """Generate a consolidated report and open it in a new spreadsheet."""
        self.ensure_one()
        if not self.env["spreadsheet.spreadsheet"].has_access("create"):
            raise UserError(
                self.env._(
                    "You need Spreadsheet access to generate a consolidated "
                    "report. Ask an administrator to add you to the Spreadsheet "
                    "users group."
                )
            )
        data = self._compute_consolidation_data()

        # Create a spreadsheet with the consolidated data
        spreadsheet = self.env["spreadsheet.spreadsheet"].create(
            {
                "name": self.env._("Consolidated Report - %(name)s", name=self.name),
                "spreadsheet_raw": self._build_spreadsheet_data(data),
            }
        )
        return spreadsheet.open_spreadsheet()

    # -- scope resolution -----------------------------------------------------

    def _get_accessible_company_ids(self):
        """Ids of the active companies whose accounting data the user may read.

        ``res.users._get_company_ids`` only returns active companies, so an
        archived company is never accessible, not even to its members.
        """
        if self.env.su:
            return set(self.env["res.company"].sudo().search([], limit=None).ids)
        return set(self.env.user._get_company_ids())

    @staticmethod
    def _company_chain(company):
        """Ids of ``company`` and all its ancestors, the root company first."""
        return [int(cid) for cid in (company.parent_path or "").split("/") if cid]

    def _get_consolidation_scopes(self):
        """Decide which companies' journal items feed each company column.

        A column reports the journal items of its company plus those of its
        branches (at any depth) that are not listed on the profile themselves:
        every branch is attributed to its nearest ancestor on the profile. A
        parent and a branch listed together are therefore never double-counted,
        and a parent listed alone still includes its branches.

        A company is usable when it is active and the user may access it. An
        unusable listed company is always excluded (and reported). Its usable
        unlisted branches are not dropped with it: each top-most one gets its
        own column. Unusable unlisted branches are only reported when they hold
        posted journal items, so empty branches do not clutter the warnings.

        :return: ``(scopes, excluded)``: ``scopes`` is a list of
            ``(company, member_company_ids)`` with the column company first;
            ``excluded`` maps ``"no_access"`` and ``"archived"`` to the (sudo)
            ``res.company`` records left out of the report for that reason.
        """
        self.ensure_one()
        Company = self.env["res.company"].sudo().with_context(active_test=False)
        # sudo + active_test=False: a plain read of the Many2many silently drops
        # the archived companies and the ones not active in the company switcher
        # (x2many convert_to_record), so they would vanish from the report
        # instead of being reported as excluded.
        profile_companies = self.sudo().with_context(active_test=False).company_ids
        profile_ids = set(profile_companies.ids)
        accessible_ids = self._get_accessible_company_ids()

        def usable(company):
            return company.active and company.id in accessible_ids

        members = {company.id: Company.browse() for company in profile_companies}
        branches = Company.browse()
        if profile_companies:
            branches = (
                Company.search([("id", "child_of", profile_companies.ids)])
                - profile_companies
            )
        for branch in branches:
            owner_id = next(
                (
                    cid
                    for cid in reversed(self._company_chain(branch))
                    if cid in profile_ids
                ),
                None,
            )
            if owner_id:
                members[owner_id] |= branch

        unusable_branches = branches.filtered(lambda company: not usable(company))
        branch_ids_with_items = set()
        if unusable_branches:
            # sudo: only whether such a branch has posted items is used here.
            groups = (
                self.env["account.move.line"]
                .sudo()
                ._read_group(
                    domain=[
                        ("company_id", "in", unusable_branches.ids),
                        ("parent_state", "=", "posted"),
                    ],
                    groupby=["company_id"],
                )
            )
            branch_ids_with_items = {company.id for (company,) in groups}

        scopes = []
        excluded = {"no_access": Company.browse(), "archived": Company.browse()}

        def exclude(company):
            excluded["no_access" if company.active else "archived"] |= company

        for company in profile_companies:
            for branch in members[company.id]:
                if not usable(branch) and branch.id in branch_ids_with_items:
                    exclude(branch)
            usable_branches = members[company.id].filtered(usable)
            if usable(company):
                scopes.append(
                    (company.with_env(self.env), [company.id, *usable_branches.ids])
                )
                continue
            exclude(company)
            # Balances the user may read are not dropped because their listed
            # parent is inaccessible or archived: every top-most usable branch
            # becomes a column holding its usable branches.
            usable_ids = set(usable_branches.ids)
            columns = {}
            for branch in usable_branches:
                top_id = next(
                    cid for cid in self._company_chain(branch) if cid in usable_ids
                )
                columns.setdefault(top_id, [top_id])
                if branch.id != top_id:
                    columns[top_id].append(branch.id)
            for top_id, member_ids in columns.items():
                scopes.append((Company.browse(top_id).with_env(self.env), member_ids))
        return scopes, excluded

    def _read_company_balances(self, company, member_ids):
        """Posted balances of one company column, grouped by company and account.

        The domain filters explicitly on ``company_id in member_ids``. The native
        ``account.account.current_balance`` is not used: it sums journal items
        with ``company_id child_of env.company``, which adds a branch's amounts
        to its parent a second time when the branch is consolidated as well.

        :return: list of ``(line_company, account, balance)`` tuples
        """
        MoveLine = self.env["account.move.line"].with_context(
            allowed_company_ids=member_ids
        )
        return MoveLine._read_group(
            domain=[
                ("company_id", "in", member_ids),
                ("parent_state", "=", "posted"),
            ],
            groupby=["company_id", "account_id"],
            aggregates=["balance:sum"],
        )

    # -- consolidation --------------------------------------------------------

    def _compute_consolidation_data(self):
        """Compute consolidated financial data across all companies."""
        self.ensure_one()
        if not self.env["account.move.line"].has_access("read"):
            raise UserError(
                self.env._(
                    "You cannot read journal items, so no balances can be "
                    "consolidated. Ask an administrator to give you accounting "
                    "access (at least the 'Invoicing' role under Accounting in "
                    "your user settings), then generate the report again."
                )
            )
        result = {
            "companies": [],
            "accounts": {},
            "consolidated": {},
            "eliminations": {},
            "warnings": [],
        }
        scopes, excluded = self._get_consolidation_scopes()
        unreadable = self.env["res.company"].sudo()
        column_roots = self.env["res.company"].sudo()
        # sudo + active_test=False for the same reason as the companies: the
        # accounts of companies that are not active in the switcher, and
        # archived accounts that still carry balances, must still be eliminated.
        elimination_accounts = (
            self.sudo().with_context(active_test=False).elimination_account_ids
        )
        elimination_ids = set(elimination_accounts.ids)
        used_elimination_ids = set()
        eliminated_keys = set()
        today = fields.Date.context_today(self)

        for company, member_ids in scopes:
            try:
                groups = self._read_company_balances(company, member_ids)
            except AccessError as error:
                _logger.warning(
                    "Consolidation profile %s: journal items of company %s are "
                    "not readable, company skipped: %s",
                    self.id,
                    company.id,
                    error,
                )
                unreadable |= company.sudo()
                continue
            column_roots |= company.sudo().root_id
            company_data = {
                "id": company.id,
                "name": company.sudo().name,
                "accounts": {},
            }
            for line_company, account, balance in groups:
                if not account:
                    # section / note lines carry no account and no amount
                    continue
                if line_company.currency_id != self.currency_id:
                    # sudo: rates live on the root company, which a user who
                    # only works in a branch may not access; the rate itself is
                    # not sensitive.
                    balance = line_company.currency_id.sudo()._convert(
                        balance, self.currency_id, line_company.sudo(), today
                    )
                # Account codes are company dependent (code_store, keyed on the
                # root company): resolve them for this column's company, never
                # for env.company, or accounts of other groups have no code.
                account_in_company = account.sudo().with_company(company)
                key = (
                    account_in_company.code
                    or account_in_company.placeholder_code
                    or f"#{account.id}"
                )
                name = account_in_company.name
                entry = {"name": name, "code": key, "balance": 0.0}
                company_data["accounts"].setdefault(key, dict(entry))
                company_data["accounts"][key]["balance"] += balance
                result["consolidated"].setdefault(key, dict(entry))
                result["consolidated"][key]["balance"] += balance
                if account.id in elimination_ids:
                    used_elimination_ids.add(account.id)
                    eliminated_keys.add(key)
            result["companies"].append(company_data)

        warnings = result["warnings"]
        excluded_companies = excluded["no_access"] | excluded["archived"] | unreadable
        warnings.extend(
            self._get_exclusion_warnings(
                excluded["no_access"], excluded["archived"], unreadable
            )
        )
        if not result["companies"]:
            raise UserError(
                self.env._(
                    "Consolidation profile '%(profile)s' has no company whose "
                    "balances you can read, so there is nothing to consolidate. "
                    "%(reasons)s",
                    profile=self.name,
                    reasons=" ".join(warnings)
                    or self.env._(
                        "Select the companies to consolidate on the profile, then "
                        "generate the report again."
                    ),
                )
            )
        unused = self._apply_eliminations(
            result,
            elimination_accounts,
            column_roots,
            excluded_companies.root_id,
            used_elimination_ids,
            eliminated_keys,
        )
        if unused:
            warnings.append(
                self.env._(
                    "Nothing was eliminated for %(accounts)s: these elimination "
                    "accounts do not belong to any consolidated company. Select "
                    "the inter-company accounts of the companies in this "
                    "profile instead.",
                    accounts=self._format_visible_accounts(unused),
                )
            )
        return result

    def _get_exclusion_warnings(self, no_access, archived, unreadable):
        """One warning per reason a company was left out of the report."""
        warnings = []
        if no_access:
            warnings.append(
                self.env._(
                    "Not included: %(companies)s. Your user has no access to these "
                    "companies, so their balances are missing from this "
                    "consolidation. Ask an administrator to add them to your "
                    "allowed companies, then generate the report again.",
                    companies=self._format_visible_companies(no_access),
                )
            )
        if archived:
            warnings.append(
                self.env._(
                    "Not included: %(companies)s. These companies are archived, so "
                    "their journal items cannot be read and their balances are "
                    "missing from this consolidation. Restore the companies, or "
                    "remove them from the profile, then generate the report again.",
                    companies=self._format_visible_companies(archived),
                )
            )
        if unreadable:
            warnings.append(
                self.env._(
                    "Not included: %(companies)s. Your access rights do not allow "
                    "reading the journal items of these companies, so their "
                    "balances are missing from this consolidation. Ask an "
                    "administrator for read access to journal items in these "
                    "companies (at least the 'Invoicing' role under Accounting in "
                    "your user settings), then generate the report again.",
                    companies=self._format_visible_companies(unreadable),
                )
            )
        return warnings

    def _apply_eliminations(
        self,
        result,
        elimination_accounts,
        column_roots,
        excluded_roots,
        used_elimination_ids,
        eliminated_keys,
    ):
        """Fill ``result["eliminations"]`` and return the unused accounts.

        Eliminations cancel whole code rows, for all consolidated companies
        together, as the report rows are keyed by code. The code of a selected
        account is company dependent, so it is resolved in the root company of
        every consolidated column: an account selected in one company also
        eliminates the same code of the other consolidated companies. Rows
        keyed on a selected account without a code (``eliminated_keys``) are
        eliminated as well.

        :return: the elimination accounts that belong to no consolidated and no
            excluded company (an excluded company is reported on its own).
        """
        elimination_codes = set()
        unused = elimination_accounts.browse()
        for account in elimination_accounts:
            codes = {
                code
                for root in column_roots
                if (code := account.with_company(root).code)
            }
            elimination_codes |= codes
            if codes or account.id in used_elimination_ids:
                continue
            if not any(account.with_company(root).code for root in excluded_roots):
                unused |= account
        for key, row in result["consolidated"].items():
            if key in elimination_codes or key in eliminated_keys:
                result["eliminations"][key] = {
                    "name": row["name"],
                    "code": key,
                    "balance": -row["balance"],
                }
        return unused

    # -- labels ---------------------------------------------------------------

    def _filter_readable(self, records):
        """Return the part of ``records`` the current user may read.

        Warnings read companies and accounts with sudo, so they must not name
        records the user could not open: the access rules are evaluated with
        all the user's companies enabled, not only those active in the switcher.
        """
        if self.env.su or not records:
            return records
        readable = (
            records.with_env(self.env)
            .with_context(
                allowed_company_ids=sorted(self._get_accessible_company_ids()),
                active_test=False,
            )
            ._filtered_access("read")
        )
        return records.browse(readable.ids)

    def _format_visible_companies(self, companies):
        """Names of the companies the user may read; the others are only counted."""
        visible = self._filter_readable(companies)
        labels = visible.mapped("name")
        if hidden := len(companies) - len(visible):
            labels.append(
                self.env._("%(count)s company(ies) you cannot see", count=hidden)
            )
        return ", ".join(labels)

    def _format_visible_accounts(self, accounts):
        """Labels of the accounts the user may read; the others are only counted."""
        visible = self._filter_readable(accounts)
        labels = [self._format_foreign_account(account) for account in visible]
        if hidden := len(accounts) - len(visible):
            labels.append(
                self.env._("%(count)s account(s) you cannot see", count=hidden)
            )
        return ", ".join(labels)

    def _format_foreign_account(self, account):
        """Label an account with the code and name of its own company.

        ``display_name`` resolves the company-dependent code in env.company, so
        an account of another company would show up without its code. The
        company name is only shown when the user may read that company.
        """
        account = account.sudo()
        companies = account.company_ids
        readable = self._filter_readable(companies)
        company = readable[:1] or companies[:1]
        code = account.with_company(company).code if company else False
        label = f"{code} {account.name}" if code else account.name
        return f"{label} ({company.name})" if readable else label

    def _col_letter(self, n):
        """Convert a 0-based column index to an A1 column reference.

        Handles indices beyond 25 (A..Z, AA, AB, ...) so consolidations with
        more than 26 companies still produce valid cell references.
        """
        s = ""
        n += 1
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    def _build_spreadsheet_data(self, data):
        """Build o-spreadsheet JSON from consolidation data."""
        cells = {}
        styles = {
            "1": {"bold": True, "fontSize": 14, "textColor": "#01666b"},
            "2": {"bold": True, "fillColor": "#f0f0f0"},
            "3": {"fillColor": "#f2f2f2"},
            "4": {"bold": True, "textColor": "#b3261e"},
        }

        # Warnings (skipped companies, unused elimination accounts) go on top so
        # an incomplete consolidation can never be mistaken for a complete one.
        row = 1
        warnings = data.get("warnings") or []
        for warning in warnings:
            cells[f"A{row}"] = {"style": 4, "content": warning}
            row += 1
        if warnings:
            row += 1  # blank separator row before the table
        header_row = row

        # Header row
        cells[f"A{header_row}"] = {"style": 1, "content": self.env._("Account")}
        cells[f"B{header_row}"] = {"style": 1, "content": self.env._("Code")}
        col = 2
        for comp in data["companies"]:
            col_letter = self._col_letter(col)
            cells[f"{col_letter}{header_row}"] = {"style": 1, "content": comp["name"]}
            col += 1
        elim_col = self._col_letter(col)
        cells[f"{elim_col}{header_row}"] = {
            "style": 1,
            "content": self.env._("Eliminations"),
        }
        cons_col = self._col_letter(col + 1)
        cells[f"{cons_col}{header_row}"] = {
            "style": 1,
            "content": self.env._("Consolidated"),
        }

        # Data rows
        row = header_row + 1
        all_codes = sorted(data["consolidated"].keys())
        for code in all_codes:
            account = data["consolidated"][code]
            style_id = "3" if (row - header_row) % 2 == 1 else None

            cells[f"A{row}"] = {"content": account["name"]}
            cells[f"B{row}"] = {"content": code}
            if style_id:
                cells[f"A{row}"]["style"] = 3
                cells[f"B{row}"]["style"] = 3

            col = 2
            for comp in data["companies"]:
                col_letter = self._col_letter(col)
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
                    "name": self.env._("Consolidated"),
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
