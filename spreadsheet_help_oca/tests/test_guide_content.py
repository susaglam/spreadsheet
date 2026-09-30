# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import re
from unittest.mock import patch

from odoo.modules.module import load_script
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import file_open
from odoo.tools.binary import BinaryBytes

POST_MIGRATE = "spreadsheet_help_oca/migrations/saas~19.4.1.0.2/post-migrate.py"

# xmlid (in spreadsheet_help_oca) -> English sheet name of the shipped workbook
GUIDE_SHEETS = {
    "guide_forecast": "Forecast Examples",
    "guide_period": "Comparison Examples",
    "guide_core": "Formula Reference",
    "guide_features": "Features",
}

# Words of the ASCII-Turkish workbooks shipped before saas~19.4.1.0.2.
TURKISH = re.compile(
    r"\b(Ornek\w*|Formul|Formuller\w*|Aciklama|Sonuc|Satis|Siparis|Musteri|Ciro|Tahmin|"
    r"Rehber|bizim|sayisi|menusu|uzerinden|Referansi|Canli|Donem|Gecen|"
    r"Kategori|Notlar|KULLANIM|Ozellikler|YENI|Beklenen|degeri|ortalamasi|"
    r"hesaplarin|partnerin|Listesi|Turkce)\b"
)


def _read_file(xmlid):
    with file_open(f"spreadsheet_help_oca/data/files/{xmlid}.json", "rb") as file:
        return file.read()


@tagged("post_install", "-at_install")
class TestGuideContent(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = load_script(
            POST_MIGRATE, "spreadsheet_help_oca_test_guide_content_migrate"
        )

    def _guide(self, xmlid):
        return self.env.ref(f"spreadsheet_help_oca.{xmlid}")

    # ------------------------------------------------------------------
    # [8] the shipped workbooks are English, in the current o-spreadsheet format
    # ------------------------------------------------------------------
    def test_guide_files_are_english_and_current_format(self):
        for xmlid, sheet_name in GUIDE_SHEETS.items():
            raw = _read_file(xmlid).decode("utf-8")
            data = json.loads(raw)
            # Current format: no migration chain runs when the guide opens.
            self.assertIsInstance(data["version"], str, xmlid)
            self.assertNotIn("odooVersion", data, xmlid)
            # A shipped workbook starts the collaborative revision history.
            self.assertEqual(data["revisionId"], "START_REVISION", xmlid)
            self.assertEqual([s["name"] for s in data["sheets"]], [sheet_name])
            for sheet in data["sheets"]:
                for ref, content in sheet["cells"].items():
                    self.assertNotIn(":", ref, f"{xmlid} {ref}: squished cell")
                    self.assertIsInstance(content, str, f"{xmlid} {ref}")
            match = TURKISH.search(raw)
            self.assertFalse(match, f"{xmlid} still holds Turkish text: {match}")

    def test_installed_guides_hold_the_shipped_workbook(self):
        """type="bytes" stores the file as is and spreadsheet_oca decodes it."""
        fingerprint = self.migration._guide_fingerprint
        for xmlid, sheet_name in GUIDE_SHEETS.items():
            guide = self._guide(xmlid)
            if self.env["spreadsheet.oca.revision"].search_count(
                [("model", "=", guide._name), ("res_id", "=", guide.id)], limit=1
            ):
                continue  # edited in this database: not the shipped state
            self.assertEqual(
                fingerprint(guide.spreadsheet_binary_data),
                fingerprint(_read_file(xmlid)),
                xmlid,
            )
            self.assertEqual(guide.spreadsheet_raw["sheets"][0]["name"], sheet_name)

    # ------------------------------------------------------------------
    # Upgrade: Turkish workbooks are reloaded, edited ones are kept
    # ------------------------------------------------------------------
    def test_fingerprint_ignores_formatting_and_rejects_non_json(self):
        fingerprint = self.migration._guide_fingerprint
        content = _read_file("guide_features")
        self.assertEqual(
            fingerprint(content), fingerprint(content.replace(b"\n", b"\r\n"))
        )
        self.assertEqual(
            fingerprint(BinaryBytes(content)),
            fingerprint(json.dumps(json.loads(content), indent=4).encode()),
        )
        self.assertIsNone(fingerprint(b"not json"))
        self.assertIsNone(fingerprint(b"\xff\xfe"))
        self.assertIsNone(fingerprint(BinaryBytes(b"")))
        self.assertIsNone(fingerprint(False))

    def test_current_files_are_not_listed_as_turkish(self):
        """Otherwise every upgrade would reload (and reset) the guides."""
        shipped = self.migration.SHIPPED_GUIDE_FINGERPRINTS
        self.assertEqual(set(shipped), set(GUIDE_SHEETS))
        for xmlid in GUIDE_SHEETS:
            current = self.migration._guide_fingerprint(_read_file(xmlid))
            self.assertNotIn(current, shipped[xmlid], xmlid)

    def test_post_migrate_reloads_only_untouched_turkish_guides(self):
        migration = self.migration
        Revision = self.env["spreadsheet.oca.revision"].sudo()

        def turkish(sheet_name):
            return json.dumps(
                {"version": 12, "odooVersion": 4, "sheets": [{"name": sheet_name}]}
            ).encode()

        untouched = self._guide("guide_period")
        untouched.spreadsheet_binary_data = BinaryBytes(turkish("Comparison Ornekleri"))
        with_revisions = self._guide("guide_forecast")
        with_revisions.spreadsheet_binary_data = BinaryBytes(
            turkish("Forecast Ornekleri")
        )
        Revision.create(
            {
                "model": with_revisions._name,
                "res_id": with_revisions.id,
                "type": "REMOTE_REVISION",
                "next_revision_id": "help-test-next",
                "server_revision_id": "START_REVISION",
                "commands": json.dumps({"type": "REMOTE_REVISION", "commands": []}),
            }
        )
        replaced = self._guide("guide_core")
        own_workbook = json.dumps({"sheets": [{"name": "Our own reference"}]}).encode()
        replaced.spreadsheet_binary_data = BinaryBytes(own_workbook)
        self.env.flush_all()

        # Pretend the fake workbooks above are the files this module shipped.
        fingerprint = migration._guide_fingerprint
        original = migration.SHIPPED_GUIDE_FINGERPRINTS
        migration.SHIPPED_GUIDE_FINGERPRINTS = {
            "guide_period": {fingerprint(turkish("Comparison Ornekleri"))},
            "guide_forecast": {fingerprint(turkish("Forecast Ornekleri"))},
            "guide_core": original["guide_core"],
            "guide_features": original["guide_features"],
        }
        try:
            for _run in range(2):  # the second run must change nothing
                migration.migrate(self.env.cr, "saas~19.4.1.0.1")
                self.env.flush_all()
                self.env.invalidate_all()

                self.assertEqual(
                    bytes(untouched.spreadsheet_binary_data),
                    _read_file("guide_period"),
                )
                self.assertEqual(
                    untouched.spreadsheet_raw["sheets"][0]["name"],
                    "Comparison Examples",
                )
                self.assertEqual(
                    bytes(with_revisions.spreadsheet_binary_data),
                    turkish("Forecast Ornekleri"),
                )
                self.assertEqual(
                    Revision.search_count(
                        [
                            ("model", "=", with_revisions._name),
                            ("res_id", "=", with_revisions.id),
                        ]
                    ),
                    1,
                )
                self.assertEqual(bytes(replaced.spreadsheet_binary_data), own_workbook)
        finally:
            migration.SHIPPED_GUIDE_FINGERPRINTS = original

    def test_post_migrate_guide_reload_failure_does_not_abort_upgrade(self):
        """A guide that cannot be reloaded is logged and kept; the other steps
        of the migration still run."""
        migration = self.migration
        guide = self._guide("guide_features")
        old = json.dumps({"version": 12, "sheets": [{"name": "Ozellikler"}]}).encode()
        guide.write(
            {
                "spreadsheet_binary_data": BinaryBytes(old),
                "name": "✨ Rehber: Ozellikler ve Menuler",
            }
        )
        self.env.flush_all()

        def missing_file(*args, **kwargs):
            raise FileNotFoundError("data/files/guide_features.json")

        original = migration.SHIPPED_GUIDE_FINGERPRINTS
        migration.SHIPPED_GUIDE_FINGERPRINTS = {
            "guide_features": {migration._guide_fingerprint(old)}
        }
        try:
            with (
                patch.object(migration, "file_open", missing_file),
                self.assertLogs(migration.__name__, level="WARNING"),
            ):
                migration.migrate(self.env.cr, "saas~19.4.1.0.1")
        finally:
            migration.SHIPPED_GUIDE_FINGERPRINTS = original
        self.env.invalidate_all()
        self.assertEqual(bytes(guide.spreadsheet_binary_data), old)
        self.assertEqual(guide.name, "✨ Guide: Features and Menus")
