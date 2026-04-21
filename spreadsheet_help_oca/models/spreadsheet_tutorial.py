# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, fields, models


class SpreadsheetTutorial(models.Model):
    _name = "spreadsheet.tutorial"
    _description = "Spreadsheet Tutorial / Video Guide"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    module_name = fields.Char(
        string="Related Module",
        help="Which module does this tutorial cover? (e.g., spreadsheet_template_oca)",
    )
    duration_minutes = fields.Integer(default=5)
    video_url = fields.Char(
        string="Video URL",
        help="YouTube, Vimeo or any embeddable video URL. Leave empty for text-only tutorials.",
    )
    tour_name = fields.Char(
        string="Interactive Tour Name",
        help="If set, the 'Start Tour' button launches this web_tour.",
    )
    guide_spreadsheet_id = fields.Many2one(
        "spreadsheet.spreadsheet",
        string="Example Spreadsheet",
        help="A pre-built spreadsheet with live examples for this feature.",
    )
    difficulty = fields.Selection(
        [
            ("beginner", "Beginner"),
            ("intermediate", "Intermediate"),
            ("advanced", "Advanced"),
        ],
        default="beginner",
    )
    tags = fields.Char(
        help="Comma-separated tags for search (e.g., 'formula,forecast,template').",
    )

    def action_open_example(self):
        """Open the associated guide spreadsheet if set."""
        self.ensure_one()
        if self.guide_spreadsheet_id:
            return self.guide_spreadsheet_id.open_spreadsheet()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("No example available"),
                "message": _(
                    "This tutorial does not have an associated example spreadsheet yet."
                ),
                "type": "warning",
            },
        }

    def action_start_tour(self):
        """Launch the associated web_tour interactive tour."""
        self.ensure_one()
        if not self.tour_name:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No tour available"),
                    "message": _("This tutorial does not have an interactive tour."),
                    "type": "info",
                },
            }
        return {
            "type": "ir.actions.client",
            "tag": "spreadsheet_help_start_tour",
            "params": {"tour_name": self.tour_name},
        }
