# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging

from odoo import api, fields, models

try:
    import requests
except ImportError:
    requests = None

_logger = logging.getLogger(__name__)


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

    def _trigger_webhooks(self, event_type):
        """Find tokens with webhook URLs that match this spreadsheet
        and enqueue delivery events.
        """
        self.ensure_one()
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
            WebhookEvent.create(
                {
                    "token_id": token.id,
                    "spreadsheet_id": self.id,
                    "event_type": event_type,
                    "payload": json.dumps(payload),
                }
            )


class SpreadsheetApiWebhookEvent(models.Model):
    _inherit = "spreadsheet.api.webhook.event"

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
        # Keep the batch small and the per-request timeout short so one stuck
        # endpoint cannot starve the whole batch past the cron interval.
        pending = self.search(
            [
                ("delivered", "=", False),
                ("retry_count", "<", retry_max),
            ],
            limit=20,
        )

        for event in pending:
            try:
                resp = requests.post(
                    event.token_id.webhook_url,
                    data=event.payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Spreadsheet-Token": event.token_id.token,
                    },
                    timeout=5,
                )
                event.write(
                    {
                        "response_status": resp.status_code,
                        "response_body": (resp.text or "")[:500],
                        "delivered": 200 <= resp.status_code < 300,
                        "retry_count": event.retry_count + 1,
                    }
                )
            except Exception as e:
                _logger.warning("Webhook %s delivery failed: %s", event.id, e)
                event.write(
                    {
                        "response_status": 0,
                        "response_body": str(e)[:500],
                        "retry_count": event.retry_count + 1,
                    }
                )
