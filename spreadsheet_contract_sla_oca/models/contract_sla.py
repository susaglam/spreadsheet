# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class SpreadsheetContract(models.Model):
    _name = "spreadsheet.contract"
    _description = "Contract Tracker"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_end"

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        required=True,
        tracking=True,
    )
    contract_type = fields.Selection(
        [
            ("sale", "Sales Contract"),
            ("purchase", "Purchase Contract"),
            ("service", "Service Agreement"),
            ("other", "Other"),
        ],
        required=True,
        default="sale",
        tracking=True,
    )
    date_start = fields.Date(required=True, tracking=True)
    date_end = fields.Date(required=True, tracking=True)
    renewal_reminder_days = fields.Integer(
        string="Reminder Before (days)",
        default=30,
        help="Days before expiry to send renewal reminder.",
    )
    amount = fields.Float(string="Contract Value", tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    responsible_id = fields.Many2one(
        "res.users",
        string="Responsible",
        default=lambda self: self.env.user,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("expiring", "Expiring Soon"),
            ("expired", "Expired"),
            ("renewed", "Renewed"),
        ],
        default="draft",
        tracking=True,
        compute="_compute_state",
        store=True,
    )
    days_to_expiry = fields.Integer(
        compute="_compute_days_to_expiry",
        store=True,
    )
    notes = fields.Html()

    # SLA fields
    sla_ids = fields.One2many(
        "spreadsheet.contract.sla",
        "contract_id",
        string="SLA Metrics",
    )

    @api.depends("date_end")
    def _compute_days_to_expiry(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_end:
                rec.days_to_expiry = (rec.date_end - today).days
            else:
                rec.days_to_expiry = 0

    @api.depends("date_start", "date_end", "days_to_expiry", "renewal_reminder_days")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.date_start or not rec.date_end:
                rec.state = "draft"
            elif rec.date_end < today:
                rec.state = "expired"
            elif rec.days_to_expiry <= rec.renewal_reminder_days:
                rec.state = "expiring"
            elif rec.date_start <= today:
                rec.state = "active"
            else:
                rec.state = "draft"

    def action_renew(self):
        """Renew the contract for another period."""
        self.ensure_one()
        duration = relativedelta(self.date_end, self.date_start)
        new_start = self.date_end + relativedelta(days=1)
        new_end = new_start + duration
        self.write(
            {
                "date_start": new_start,
                "date_end": new_end,
            }
        )
        self.message_post(body=_("Contract renewed until %s.") % new_end)

    @api.model
    def _cron_check_contract_expiry(self):
        """Send reminders for contracts expiring soon."""
        today = fields.Date.context_today(self)
        contracts = self.search(
            [
                ("active", "=", True),
                ("date_end", ">=", today),
            ]
        )

        template = self.env.ref(
            "spreadsheet_contract_sla_oca.contract_expiry_email_template",
            raise_if_not_found=False,
        )

        for contract in contracts:
            if contract.days_to_expiry == contract.renewal_reminder_days:
                # Schedule activity for responsible user
                contract.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=contract.responsible_id.id,
                    summary=_("Contract '%s' expires in %s days")
                    % (contract.name, contract.days_to_expiry),
                    date_deadline=contract.date_end,
                )
                # Send email
                if template:
                    template.send_mail(contract.id, force_send=True)

                _logger.info(
                    "Contract expiry reminder sent: %s (expires %s)",
                    contract.name,
                    contract.date_end,
                )


class SpreadsheetContractSla(models.Model):
    _name = "spreadsheet.contract.sla"
    _description = "Contract SLA Metric"
    _order = "contract_id, name"

    name = fields.Char(required=True, string="SLA Metric")
    contract_id = fields.Many2one(
        "spreadsheet.contract",
        required=True,
        ondelete="cascade",
    )
    target_value = fields.Float(
        string="Target",
        help="Target SLA value (e.g., 99.9 for 99.9% uptime).",
    )
    actual_value = fields.Float(
        string="Actual",
    )
    unit = fields.Char(
        default="%",
        help="Unit of measurement (%, hours, days, etc.).",
    )
    compliance = fields.Selection(
        [
            ("met", "Met"),
            ("breached", "Breached"),
            ("pending", "Pending"),
        ],
        compute="_compute_compliance",
        store=True,
    )
    last_updated = fields.Datetime()

    @api.depends("target_value", "actual_value")
    def _compute_compliance(self):
        for rec in self:
            if not rec.actual_value:
                rec.compliance = "pending"
            elif rec.actual_value >= rec.target_value:
                rec.compliance = "met"
            else:
                rec.compliance = "breached"
