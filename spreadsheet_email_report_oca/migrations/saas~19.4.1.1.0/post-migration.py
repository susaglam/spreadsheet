# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


def migrate(cr, version):
    # The 'xlsx' format option was removed (the server has no o-spreadsheet
    # engine and can only emit JSON; the old option attached JSON with a .xlsx
    # name that Excel could not open). Normalise any legacy row so the now
    # single-option required Selection doesn't render blank in list/form views.
    cr.execute(
        "UPDATE spreadsheet_email_report SET format = 'json' WHERE format != 'json'"
    )
