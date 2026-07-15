import frappe
from frappe.tests.utils import FrappeTestCase


def _make_csv_file(rows_header, rows):
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(rows_header + "\n")
        for r in rows:
            f.write(r + "\n")
    # attach as a File so csv_file has a valid /private path
    with open(path, "rb") as fh:
        filedoc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "memb_test.csv",
                "is_private": 1,
                "content": fh.read(),
            }
        ).insert(ignore_permissions=True)
    return filedoc.file_url


HEADER = "Debiteur Id,Debiteur Naam,Type,Looptijd,Ingangsdatum,Opgezegd,Einddatum,Normale prijs (type),Id"


class TestProcuriosMembershipImportValidate(FrappeTestCase):
    def _make_import(self, rows):
        url = _make_csv_file(HEADER, rows)
        doc = frappe.get_doc(
            {
                "doctype": "Procurios Membership Import",
                "csv_file": url,
                "csv_delimiter": "Comma",
            }
        ).insert(ignore_permissions=True)
        return doc

    def _ensure_mapping_choice_saved(self, doc):
        # Test-fixture helper: persists an already-mapped Membership Type
        # choice on the child row so re-validation can be exercised.
        doc.save(ignore_permissions=True)

    def test_validate_populates_type_mapping(self):
        doc = self._make_import(
            [
                "67017,Amanda,Maandlid,1 Maand,2022-11-27,,,2.5,7112",
                "18458,Annelies,Jaarlid,1 Jaar,2020-01-30,,,20,5124",
            ]
        )
        doc._validate_and_preview_csv()
        doc.reload()
        self.assertEqual(doc.import_status, "Ready for Import")
        types = sorted(r.procurios_type for r in doc.membership_type_mapping)
        self.assertEqual(types, ["Jaarlid", "Maandlid"])

    def test_validate_preserves_existing_mapping_choice(self):
        doc = self._make_import(["67017,Amanda,Maandlid,1 Maand,2022-11-27,,,2.5,7112"])
        doc._validate_and_preview_csv()
        doc.reload()
        mt = frappe.get_all("Membership Type", limit=1)[0].name
        doc.membership_type_mapping[0].membership_type = mt
        self._ensure_mapping_choice_saved(doc)
        # Re-validate: existing choice must survive
        doc._validate_and_preview_csv()
        doc.reload()
        self.assertEqual(doc.membership_type_mapping[0].membership_type, mt)

    def test_incomplete_mapping_detected(self):
        doc = self._make_import(["67017,Amanda,Maandlid,1 Maand,2022-11-27,,,2.5,7112"])
        doc._validate_and_preview_csv()
        doc.reload()
        self.assertEqual(doc._incomplete_mapping_types(), ["Maandlid"])
