# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from random import randint

from odoo import fields, models


class SpreadsheetTemplateCategory(models.Model):
    _name = "spreadsheet.template.category"
    _description = "Spreadsheet Template Category"
    _order = "sequence, name"

    def _get_default_color(self):
        return randint(1, 11)

    # NOT translate=True: a translatable Char is stored as a JSONB blob in
    # Odoo, so the SQL UNIQUE(name) constraint would compare whole blobs and
    # treat two categories with the same en_US name but different translation
    # sets as distinct, defeating uniqueness. Category labels are short
    # grouping tags and are kept untranslated so the constraint works.
    name = fields.Char(
        required=True,
        help="Short grouping label for templates, e.g. 'Sales', 'Finance', "
        "'HR'. Must be unique.",
    )
    sequence = fields.Integer(
        default=10,
        help="Lower numbers sort first in lists and the kanban.",
    )
    color = fields.Integer(
        default=lambda self: self._get_default_color(),
        help="Color tag for this category chip, shown wherever the category "
        "is displayed.",
    )
    template_ids = fields.One2many(
        "spreadsheet.template", "category_id", string="Templates"
    )
    template_count = fields.Integer(compute="_compute_template_count")

    _name_uniq = models.Constraint(
        "unique (name)",
        "A category with the same name already exists.",
    )

    def _compute_template_count(self):
        for rec in self:
            rec.template_count = len(rec.template_ids)
