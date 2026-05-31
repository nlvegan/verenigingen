# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import unittest
from datetime import date


class TestProcuriosMandateValidator(unittest.TestCase):
    """Unit tests for ProcuriosMandateValidator field mapping and classification.

    Pure logic; no DB access. Per-row business rules (member match,
    duplicate, conflict) are exercised in test_procurios_mandate_import.py.
    """

    def setUp(self):
        from verenigingen.utils.csv.procurios_mandate_validator import ProcuriosMandateValidator

        # Pin "today" to make cutoff math deterministic across test runs.
        self.validator = ProcuriosMandateValidator(today=date(2026, 5, 31))

    def _base_row(self, **overrides):
        row = {
            "Incasso-afspraak ID": "973",
            "Type machtiging": "Doorlopend",
            "Type machtiging ID": "2",
            "Mandaatnummer": "40123603-V005064-00002",
            "IBAN": "NL12TRIO0197963145",
            "Incassant": "Nederlandse Vereniging voor Veganisme",
            "Incassant ID": "2",
            "Rekeninghouder": "F.J. de Haan",
            "Debiteur naam": "Foppe de Haan",
            "Debiteur ID": "1484",
            "Datum van ondertekening": "2015-06-18",
            "Opzegdatum": "",
            "Pre-notificatie datum": "",
            "Administratie ID": "1",
            "Administratie": "Nederlandse Vereniging voor Veganisme",
        }
        row.update(overrides)
        return row

    def test_check_required_columns_all_present(self):
        headers = list(self._base_row().keys())
        self.assertEqual(self.validator.check_required_columns(headers), [])

    def test_check_required_columns_missing(self):
        headers = ["Mandaatnummer", "IBAN"]
        missing = self.validator.check_required_columns(headers)
        self.assertIn("Rekeninghouder", missing)
        self.assertIn("Debiteur ID", missing)
        self.assertIn("Datum van ondertekening", missing)

    def test_map_row_active_mandate(self):
        mapped = self.validator.map_row(self._base_row(), row_num=1)
        self.assertEqual(mapped.mandate_id, "40123603-V005064-00002")
        self.assertEqual(mapped.iban, "NL12TRIO0197963145")
        self.assertEqual(mapped.account_holder_name, "F.J. de Haan")
        self.assertEqual(mapped.debiteur_id, "1484")
        self.assertEqual(mapped.debiteur_naam, "Foppe de Haan")
        self.assertEqual(mapped.sign_date, "2015-06-18")
        self.assertIsNone(mapped.cancelled_date)
        self.assertEqual(mapped.mandate_type, "RCUR")
        self.assertFalse(mapped.is_cancelled)
        self.assertIn("973", mapped.notes)

    def test_map_row_iban_is_trimmed_and_uppercased(self):
        mapped = self.validator.map_row(self._base_row(IBAN="  nl12trio0197963145  "), row_num=1)
        self.assertEqual(mapped.iban, "NL12TRIO0197963145")

    def test_map_row_recently_cancelled(self):
        # 6 months before pinned today (2026-05-31) → recently cancelled
        mapped = self.validator.map_row(self._base_row(Opzegdatum="2025-12-01"), row_num=1)
        self.assertEqual(mapped.cancelled_date, "2025-12-01")
        self.assertTrue(mapped.is_cancelled)

    def test_map_row_mandate_type_eenmalig(self):
        mapped = self.validator.map_row(
            self._base_row(**{"Type machtiging": "Eenmalig"}), row_num=1
        )
        self.assertEqual(mapped.mandate_type, "OOFF")

    def test_map_row_mandate_type_unknown_defaults_rcur(self):
        mapped = self.validator.map_row(
            self._base_row(**{"Type machtiging": "Iets-anders"}), row_num=1
        )
        self.assertEqual(mapped.mandate_type, "RCUR")

    def test_map_row_missing_required_field_raises(self):
        bad = self._base_row(Mandaatnummer="")
        with self.assertRaises(ValueError) as ctx:
            self.validator.map_row(bad, row_num=7)
        self.assertIn("row 7", str(ctx.exception).lower())
        self.assertIn("mandaatnummer", str(ctx.exception).lower())

    def test_map_row_invalid_date_raises(self):
        bad = self._base_row(**{"Datum van ondertekening": "not-a-date"})
        with self.assertRaises(ValueError):
            self.validator.map_row(bad, row_num=3)

    def test_validate_and_map_filters_old_cancelled(self):
        rows = [
            self._base_row(Mandaatnummer="A", Opzegdatum=""),                 # active
            self._base_row(Mandaatnummer="B", Opzegdatum="2025-12-01"),        # recent
            self._base_row(Mandaatnummer="C", Opzegdatum="2020-01-01"),        # too old
        ]
        mapped, errors, filtered = self.validator.validate_and_map(rows)
        ids = sorted(m.mandate_id for m in mapped)
        self.assertEqual(ids, ["A", "B"])
        self.assertEqual(filtered, 1)
        self.assertEqual(errors, [])

    def test_validate_and_map_collects_errors_without_aborting(self):
        rows = [
            self._base_row(Mandaatnummer="A"),
            self._base_row(Mandaatnummer=""),  # bad row
            self._base_row(Mandaatnummer="C"),
        ]
        mapped, errors, _ = self.validator.validate_and_map(rows)
        self.assertEqual(len(mapped), 2)
        self.assertEqual(len(errors), 1)

    def test_notes_compose_includes_administratie_and_pre_notification(self):
        row = self._base_row(**{
            "Pre-notificatie datum": "2026-01-15",
            "Administratie": "NVV",
            "Incasso-afspraak ID": "999",
        })
        mapped = self.validator.map_row(row, row_num=1)
        self.assertIn("Incasso-afspraak ID 999", mapped.notes)
        self.assertIn("NVV", mapped.notes)
        self.assertIn("2026-01-15", mapped.notes)


if __name__ == "__main__":
    unittest.main()
