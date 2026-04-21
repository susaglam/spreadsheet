# Copyright 2026 Badkamertien
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from random import randint

from odoo import fields, models


class SpreadsheetTemplateCategory(models.Model):
    _name = "spreadsheet.template.category"
    _description = "Spreadsheet Template Category"
    _order = "sequence, name"

    def _get_default_color(self):
        return randint(1, 11)

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer(default=lambda self: self._get_default_color())
    template_ids = fields.One2many(
        "spreadsheet.template", "category_id", string="Templates"
    )
    template_count = fields.Integer(compute="_compute_template_count")

    _sql_constraints = [
        ("name_uniq", "unique (name)", "A category with the same name already exists."),
    ]

    def _compute_template_count(self):
        for rec in self:
            rec.template_count = len(rec.template_ids)
