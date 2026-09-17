# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging
import time

from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..tools.webhook import (
    WebhookTargetError,
    post_webhook,
    requests,
    sign_payload,
)

_logger = logging.getLogger(__name__)

# Seconds one run of the delivery cron may spend sending webhooks. Events
# left over are sent by the next run, so one slow endpoint cannot keep the
# cron busy for long.
CRON_TIME_BUDGET = 60


class SpreadsheetSpreadsheet(models.Model):
    _inherit = "spreadsheet.spreadsheet"

    def write(self, vals):
        result = super().write(vals)
        # Trigger webhooks only when raw data changes
        if "spreadsheet_raw" in vals or "spreadsheet_binary_data" in vals:
            for rec in self:
                rec._trigger_webhooks("update")
        return result

    def send_spreadsheet_message(self, message, access_token=None):
        result = super().send_spreadsheet_message(message, access_token=access_token)
        # Collaborative edits never write spreadsheet_raw/binary_data, so the
        # write() hook above misses them; fire the update webhook here after a
        # persisted revision/snapshot instead.
        if result and message.get("type") in (
            "REMOTE_REVISION",
            "REVISION_UNDONE",
            "REVISION_REDONE",
            "SNAPSHOT",
        ):
            self._trigger_webhooks("update")
        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._trigger_webhooks("create")
        return records

    def unlink(self):
        # Prepare the events BEFORE deleting (afterwards neither the name nor
        # the token user's read access can be evaluated) but create them only
        # once the deletion succeeded: a refused unlink whose error is caught
        # by the caller must not announce a deletion that did not happen.
        self.check_access("unlink")
        vals_list = []
        for rec in self:
            vals_list.extend(rec._prepare_webhook_event_vals("delete"))
        result = super().unlink()
        for vals in vals_list:
            vals["spreadsheet_id"] = False  # the record is gone
        if vals_list:
            self.env["spreadsheet.api.webhook.event"].sudo().create(vals_list)
        return result

    def _is_readable_by_api_user(self, user):
        """Whether ``user`` (a token's user) may read this spreadsheet.

        Evaluated in a clean, non-sudo environment of that user with all of
        its companies allowed, which is how the REST API itself runs, so a
        webhook never announces a spreadsheet the API would hide.
        """
        self.ensure_one()
        context = dict(self.env.context)
        context.pop("allowed_company_ids", None)
        record = self.with_env(self.env(user=user.id, su=False, context=context))
        try:
            return record.has_access("read")
        except (AccessError, ValueError) as error:
            _logger.warning(
                "Skipping webhook for spreadsheet %s: read access of user %s "
                "could not be evaluated (%s).",
                self.id,
                user.id,
                error,
            )
            return False

    def _trigger_webhooks(self, event_type):
        """Enqueue delivery events for the tokens watching this spreadsheet."""
        self.ensure_one()
        vals_list = self._prepare_webhook_event_vals(event_type)
        if vals_list:
            self.env["spreadsheet.api.webhook.event"].sudo().create(vals_list)

    def _prepare_webhook_event_vals(self, event_type):
        """Return the values of the delivery events to create.

        Only tokens whose user can read the spreadsheet are notified: the
        payload carries the spreadsheet name, which must not leak to an
        integration that cannot see it through the API.
        """
        self.ensure_one()
        vals_list = []
        Token = self.env["spreadsheet.api.token"].sudo()
        WebhookEvent = self.env["spreadsheet.api.webhook.event"].sudo()
        # Same retry ceiling the delivery cron uses; needed so coalescing only
        # skips a still-deliverable pending event, never a terminally-failed one.
        retry_max = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_int("spreadsheet_api.webhook_retry_max")
            or 3
        )

        tokens = Token.search(
            [
                ("active", "=", True),
                ("webhook_url", "!=", False),
            ]
        )
        for token in tokens:
            # Check token applies to this spreadsheet
            if token.spreadsheet_ids and self not in token.spreadsheet_ids:
                continue
            if not Token._is_allowed_api_user(token.user_id):
                continue
            if not self._is_readable_by_api_user(token.user_id):
                continue

            # Coalesce bursts: collaborative editing fires many REMOTE_REVISION
            # messages per second; skip if a STILL-DELIVERABLE 'update' for this
            # token+spreadsheet is already queued. Exhausted (retry_count ==
            # retry_max) events are excluded, so a dead endpoint doesn't
            # permanently suppress all future updates.
            if event_type == "update" and WebhookEvent.search_count(
                [
                    ("token_id", "=", token.id),
                    ("spreadsheet_id", "=", self.id),
                    ("event_type", "=", "update"),
                    ("delivered", "=", False),
                    ("retry_count", "<", retry_max),
                ]
            ):
                continue

            payload = {
                "event": event_type,
                "spreadsheet_id": self.id,
                "spreadsheet_name": self.name,
                "timestamp": fields.Datetime.now().isoformat(),
            }
            vals_list.append(
                {
                    "token_id": token.id,
                    "spreadsheet_id": self.id,
                    "event_type": event_type,
                    "payload": json.dumps(payload),
                }
            )
        return vals_list


class SpreadsheetApiWebhookEvent(models.Model):
    _inherit = "spreadsheet.api.webhook.event"

    def _get_delivery_headers(self):
        self.ensure_one()
        token = self.token_id.sudo()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Odoo-Spreadsheet-Webhook/1.0",
            "X-Spreadsheet-Event": self.event_type,
            "X-Spreadsheet-Token-Id": str(token.id),
        }
        # The plaintext token is no longer stored, so it can't be sent (and
        # sending a credential to a third party was a leak anyway). Receivers
        # verify HMAC-SHA256(key=sha256_hex(token), body) instead. _deliver()
        # never sends an event of a token without a secret.
        signature = sign_payload(token.token_hash or "", self.payload or "")
        headers["X-Spreadsheet-Signature"] = f"sha256={signature}"
        return headers

    def _deliver(self):
        """Attempt one delivery of this event and record the outcome."""
        self.ensure_one()
        token = self.token_id.sudo()
        values = {"retry_count": self.retry_count + 1, "delivered": False}
        if not token.active or not token.webhook_url:
            values.update(
                response_status=0,
                response_body=self.env._(
                    "Not sent: the API token is archived or has no webhook URL "
                    "anymore. Reactivate the token or set its webhook URL; new "
                    "changes will queue new events."
                ),
            )
        elif not token.token_hash:
            values.update(
                response_status=0,
                response_body=self.env._(
                    "Not sent: this API token has no secret yet, so the call "
                    "could not be signed and the receiver could not check "
                    "where it comes from. Click Generate Token on the token; "
                    "later attempts are then sent normally."
                ),
            )
        elif not token._is_allowed_api_user(token.user_id):
            values.update(
                response_status=0,
                response_body=self.env._(
                    "Not sent: the API token runs as the superuser, a "
                    "portal/public user or an archived user, which is not "
                    "allowed. Set an active internal user on the token."
                ),
            )
        else:
            try:
                status, body = post_webhook(
                    token.webhook_url,
                    self.payload or "",
                    headers=self._get_delivery_headers(),
                )
                values.update(
                    response_status=status,
                    response_body=body,
                    delivered=200 <= status < 300,
                )
            except WebhookTargetError as error:
                _logger.warning(
                    "Webhook %s blocked: target %s is not a public address (%s).",
                    self.id,
                    token.webhook_url,
                    error,
                )
                values.update(
                    response_status=0,
                    response_body=token._webhook_target_error_message(
                        error, token.webhook_url
                    )[:500],
                )
            except Exception as error:  # network errors come in many types
                _logger.warning("Webhook %s delivery failed: %s", self.id, error)
                values.update(response_status=0, response_body=str(error)[:500])
        self.sudo().write(values)

    @api.model
    def _cron_deliver_webhooks(self):
        """Deliver pending webhook events, with retry logic."""
        if not requests:
            _logger.warning("requests library not available; webhooks disabled.")
            return

        retry_max = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_int("spreadsheet_api.webhook_retry_max")
            or 3
        )
        # Keep the batch small, every call bounded by a total deadline (see
        # tools/webhook.py) and the whole run bounded by CRON_TIME_BUDGET, so
        # one slow endpoint cannot starve the other tokens' webhooks.
        pending = self.search(
            [
                ("delivered", "=", False),
                ("retry_count", "<", retry_max),
            ],
            limit=20,
        )
        started = time.monotonic()
        for index, event in enumerate(pending):
            if time.monotonic() - started > CRON_TIME_BUDGET:
                _logger.info(
                    "Webhook delivery stopped after %s seconds; %s event(s) "
                    "left for the next run.",
                    CRON_TIME_BUDGET,
                    len(pending) - index,
                )
                break
            event._deliver()
