# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Integration tests for the Procurios Mandate Import flow.

Real DB. No business-logic mocks (per project test-quality enforcer).
"""

import csv
import json
import os
import tempfile

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


CSV_HEADERS = [
    "Incasso-afspraak ID",
    "Type machtiging",
    "Type machtiging ID",
    "Mandaatnummer",
    "IBAN",
    "Incassant",
    "Incassant ID",
    "Rekeninghouder",
    "Debiteur naam",
    "Debiteur ID",
    "Datum van ondertekening",
    "Opzegdatum",
    "Pre-notificatie datum",
    "Administratie ID",
    "Administratie",
]


def _base_row(**overrides):
    row = {
        "Incasso-afspraak ID": "973",
        "Type machtiging": "Doorlopend",
        "Type machtiging ID": "2",
        "Mandaatnummer": "M-001",
        "IBAN": "NL91ABNA0417164300",
        "Incassant": "NVV",
        "Incassant ID": "2",
        "Rekeninghouder": "J. Jansen",
        "Debiteur naam": "Jan Jansen",
        "Debiteur ID": "PROC-1",
        "Datum van ondertekening": "2020-01-15",
        "Opzegdatum": "",
        "Pre-notificatie datum": "",
        "Administratie ID": "1",
        "Administratie": "NVV",
    }
    row.update(overrides)
    return row


def _create_csv_attach(rows):
    """Test fixture: write `rows` to a temp CSV and register as a Frappe File."""
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="procurios_mandate_")
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    with open(path, "rb") as f:
        content = f.read()

    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": os.path.basename(path),
        "is_private": 1,
        "content": content,
    })
    file_doc.flags.ignore_permissions = True
    file_doc.insert()
    return file_doc.file_url


def _create_raw_csv_attach(raw_text: str, name_hint: str = "raw.csv"):
    """Test fixture: register an arbitrary CSV blob as a Frappe File."""
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": name_hint,
        "is_private": 1,
        "content": raw_text.encode("utf-8"),
    })
    file_doc.flags.ignore_permissions = True
    file_doc.insert()
    return file_doc.file_url


def _create_import_doc(file_url: str, **fields):
    """Test fixture: insert a Procurios Mandate Import pointing at `file_url`."""
    payload = {
        "doctype": "Procurios Mandate Import",
        "csv_file": file_url,
        "csv_delimiter": "Semicolon",
    }
    payload.update(fields)
    doc = frappe.get_doc(payload)
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


class TestProcuriosMandateImportValidate(EnhancedTestCase):
    """Validate / preview phase — no submission."""

    def test_validate_marks_ready_with_preview(self):
        rows = [_base_row(Mandaatnummer="M-001"), _base_row(Mandaatnummer="M-002")]
        file_url = _create_csv_attach(rows)
        doc = _create_import_doc(file_url)

        doc._validate_and_preview_csv()
        doc.reload()

        self.assertEqual(doc.import_status, "Ready for Import")
        self.assertEqual(doc.total_rows, 2)
        preview = json.loads(doc.preview_data)
        self.assertEqual(len(preview), 2)
        self.assertEqual(preview[0]["mandate_id"], "M-001")

    def test_validate_fails_on_missing_required_column(self):
        # CSV missing 'Mandaatnummer'
        file_url = _create_raw_csv_attach(
            "IBAN;Rekeninghouder\nNL91ABNA0417164300;J. Jansen\n",
            name_hint="missing_mandaatnummer.csv",
        )
        doc = _create_import_doc(file_url)

        doc._validate_and_preview_csv()
        doc.reload()

        self.assertEqual(doc.import_status, "Failed")
        self.assertIn("Mandaatnummer", doc.error_log or "")
