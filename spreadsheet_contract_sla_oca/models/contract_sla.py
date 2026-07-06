# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SpreadsheetContract(models.Model):
    _name = "spreadsheet.contract"
    _description = "Contract Tracker"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_end"

    name = fields.Char(
        required=True,
        tracking=True,
        help="Human-readable label for this contract. "
        "Example: 'Acme Cloud Hosting 2026'.",
    )
    active = fields.Boolean(default=True)
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        required=True,
        tracking=True,
        help="Customer or vendor this contract is signed with. "
        "Used for grouping and reporting.",
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
        help="Category of agreement; also drives the colour on the calendar "
        "view. Example: pick 'Service Agreement' for an SLA-backed support "
        "contract.",
    )
    date_start = fields.Date(
        required=True,
        tracking=True,
        help="Date the contract becomes effective. The status turns 'Active' "
        "once this date is reached.",
    )
    date_end = fields.Date(
        required=True,
        tracking=True,
        help="Contract expiry date. The Expiring/Expired status and renewal "
        "reminders are calculated from this.",
    )
    renewal_reminder_days = fields.Integer(
        string="Reminder Before (days)",
        default=lambda self: (
            self.env["ir.config_parameter"]
            .sudo()
            .get_int("spreadsheet_contract.default_reminder_days", 30)
        ),
        help="Days before expiry to send renewal reminder. Defaults to the "
        "value configured in Settings.",
    )
    amount = fields.Float(
        string="Contract Value",
        tracking=True,
        help="Total monetary value of the contract, in the selected currency.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    responsible_id = fields.Many2one(
        "res.users",
        string="Responsible",
        default=lambda self: self.env.user,
        tracking=True,
        help="User who owns this contract and receives the renewal reminder "
        "activity and email.",
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
    last_reminder_date = fields.Date(
        string="Last Reminder Sent",
        readonly=True,
        copy=False,
        help="Date the most recent renewal reminder was sent. Prevents the "
        "cron from re-sending the same reminder every day.",
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
        self.message_post(
            body=self.env._("Contract renewed until %(date)s.", date=new_end)
        )

    @api.model
    def _cron_check_contract_expiry(self):
        """Send reminders for contracts expiring soon."""
        today = fields.Date.context_today(self)
        # Recompute the stored date-based fields on ALL active contracts (not
        # only future-dated ones): they are keyed solely on date_end and would
        # otherwise stay frozen as calendar days pass — expired contracts must
        # still flip state. Then narrow to the not-yet-expired reminder subset.
        all_contracts = self.search([("active", "=", True)])
        all_contracts.modified(["date_end"])
        contracts = all_contracts.filtered(lambda c: c.date_end and c.date_end >= today)

        template = self.env.ref(
            "spreadsheet_contract_sla_oca.contract_expiry_email_template",
            raise_if_not_found=False,
        )

        for contract in contracts:
            if not contract.date_end:
                continue
            days_left = (contract.date_end - today).days
            # Fire anywhere inside the reminder window (not only on the exact
            # boundary day).
            if not 0 <= days_left <= contract.renewal_reminder_days:
                continue
            # Send once per renewal window: skip if we already reminded on or
            # after the window opened. This de-dups across days (a daily cron
            # must not re-send every day) while a missed run still catches up.
            window_start = contract.date_end - relativedelta(
                days=contract.renewal_reminder_days
            )
            if (
                contract.last_reminder_date
                and contract.last_reminder_date >= window_start
            ):
                continue
            try:
                # Schedule activity for responsible user
                contract.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=contract.responsible_id.id,
                    summary=self.env._(
                        "Contract '%(name)s' expires in %(days)s days",
                        name=contract.name,
                        days=days_left,
                    ),
                    date_deadline=contract.date_end,
                )
                # Stamp before sending so a mail-queue error cannot cause the
                # activity to be re-scheduled (duplicated) on the next run.
                contract.last_reminder_date = today

                # Send email through the outgoing queue (non-blocking)
                if template:
                    template.send_mail(contract.id, force_send=False)

                _logger.info(
                    "Contract expiry reminder sent: %s (expires %s)",
                    contract.name,
                    contract.date_end,
                )
            except Exception:
                _logger.exception("Contract reminder failed for %s", contract.name)
                continue


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
        help="Measured SLA result, compared to Target to compute compliance "
        "(e.g. 99.95). A value of 0 counts as a real measurement.",
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
    last_updated = fields.Datetime(
        string="Last Measured",
        readonly=True,
        copy=False,
        help="Automatically stamped whenever the Target or Actual value is "
        "changed. Also marks the metric as measured (so an Actual of 0 is "
        "compared instead of staying Pending).",
    )

    @api.depends("target_value", "actual_value", "last_updated")
    def _compute_compliance(self):
        for rec in self:
            # Gate on the measurement timestamp rather than value truthiness so
            # a genuine measured 0.0 is not mistaken for 'not yet measured'.
            if not rec.last_updated:
                rec.compliance = "pending"
            elif rec.actual_value >= rec.target_value:
                rec.compliance = "met"
            else:
                rec.compliance = "breached"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Stamp only on a real measurement (actual_value); a metric created
            # with just a target must stay Pending until it is measured.
            if "actual_value" in vals and not vals.get("last_updated"):
                vals["last_updated"] = fields.Datetime.now()
        return super().create(vals_list)

    def write(self, vals):
        if "actual_value" in vals and "last_updated" not in vals:
            vals["last_updated"] = fields.Datetime.now()
        return super().write(vals)
