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


def _create_member_with_procurios_id(test_case, procurios_id: str, **kwargs):
    """Test fixture: create a Member with a specific procurios_id."""
    member = test_case.create_test_member(procurios_id=procurios_id, **kwargs)
    return member


def _create_active_sepa_mandate(member_name: str, mandate_id: str, iban: str):
    """Test fixture: insert an Active SEPA Mandate for `member_name`."""
    mandate = frappe.get_doc({
        "doctype": "SEPA Mandate",
        "mandate_id": mandate_id,
        "member": member_name,
        "account_holder_name": "Test Holder",
        "iban": iban,
        "sign_date": "2023-01-01",
        "mandate_type": "RCUR",
        "scheme": "SEPA",
    })
    mandate.flags.ignore_permissions = True
    mandate.insert()
    return mandate


def _create_stub_import_doc():
    """Test fixture: an import doc with a placeholder file (file content unused)."""
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": "stub.csv",
        "is_private": 1,
        "content": b"stub",
    })
    file_doc.flags.ignore_permissions = True
    file_doc.insert()

    doc = frappe.get_doc({
        "doctype": "Procurios Mandate Import",
        "csv_file": file_doc.file_url,
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


def _make_mandate_row(**kw):
    """Build a ProcuriosMandateRow for tests (pure-Python; no DB)."""
    from verenigingen.utils.csv.procurios_mandate_validator import ProcuriosMandateRow

    defaults = dict(
        row_number=1,
        mandate_id="M-100",
        iban="NL91ABNA0417164300",
        account_holder_name="J. Jansen",
        debiteur_id="PROC-1",
        debiteur_naam="Jan Jansen",
        sign_date="2020-01-15",
        cancelled_date=None,
        mandate_type="RCUR",
        notes="Imported from Procurios.",
    )
    defaults.update(kw)
    return ProcuriosMandateRow(**defaults)


def _empty_skip_counters():
    return {"no_member": 0, "duplicate": 0, "conflict": 0, "error": 0}


class TestProcuriosMandateImportProcessRow(EnhancedTestCase):
    """Per-row processor — exercises every branch of the decision tree."""

    def test_creates_mandate_when_member_exists(self):
        member = _create_member_with_procurios_id(self, "PROC-1")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="M-100", debiteur_id="PROC-1")

        status, name = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "created")
        mandate = frappe.get_doc("SEPA Mandate", name)
        self.assertEqual(mandate.member, member.name)
        self.assertEqual(mandate.status, "Active")
        # The validation service normalises IBAN spacing (e.g. "NL91 ABNA 0417 1643 00"),
        # so compare without spaces.
        self.assertEqual(mandate.iban.replace(" ", ""), "NL91ABNA0417164300")
        # Cache must be updated so a subsequent active row for same member triggers conflict.
        self.assertIn(member.name, caches.members_with_active_mandate)

    def test_skips_when_no_member_match(self):
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(debiteur_id="NO-SUCH-ID")

        status, name = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(name, "")
        self.assertEqual(counters["no_member"], 1)

    def test_skips_duplicate_active(self):
        member = _create_member_with_procurios_id(self, "PROC-2")
        _create_active_sepa_mandate(member.name, "M-DUP", "NL91ABNA0417164300")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="M-DUP", debiteur_id="PROC-2")

        status, _ = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(counters["duplicate"], 1)

    def test_updates_existing_when_csv_cancelled(self):
        member = _create_member_with_procurios_id(self, "PROC-3")
        existing = _create_active_sepa_mandate(member.name, "M-UPD", "NL91ABNA0417164300")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(
            mandate_id="M-UPD", debiteur_id="PROC-3", cancelled_date="2025-12-01"
        )

        status, _name = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "updated")
        updated = frappe.get_doc("SEPA Mandate", existing.name)
        self.assertEqual(str(updated.cancelled_date), "2025-12-01")
        self.assertEqual(updated.status, "Cancelled")

    def test_skips_conflict_when_member_has_other_active(self):
        member = _create_member_with_procurios_id(self, "PROC-4")
        _create_active_sepa_mandate(member.name, "M-EXISTING", "NL91ABNA0417164300")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="M-NEW", debiteur_id="PROC-4")

        status, _ = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(counters["conflict"], 1)
        self.assertFalse(frappe.db.exists("SEPA Mandate", {"mandate_id": "M-NEW"}))

    def test_cancelled_row_for_member_with_active_mandate_still_imports(self):
        # A historical cancelled mandate doesn't conflict with an active one.
        member = _create_member_with_procurios_id(self, "PROC-5")
        _create_active_sepa_mandate(member.name, "M-ACTIVE", "NL91ABNA0417164300")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(
            mandate_id="M-OLD", debiteur_id="PROC-5", cancelled_date="2025-12-01"
        )

        status, name = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "created")
        mandate = frappe.get_doc("SEPA Mandate", name)
        self.assertEqual(mandate.status, "Cancelled")
        self.assertEqual(counters["conflict"], 0)

    def test_two_active_rows_same_member_second_conflicts(self):
        _create_member_with_procurios_id(self, "PROC-6")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()  # member has no active mandate yet
        counters = _empty_skip_counters()
        errors = []

        s1, _ = doc._process_single_row(
            _make_mandate_row(mandate_id="M-A", debiteur_id="PROC-6"),
            errors, caches, counters,
        )
        s2, _ = doc._process_single_row(
            _make_mandate_row(mandate_id="M-B", debiteur_id="PROC-6"),
            errors, caches, counters,
        )
        self.assertEqual(s1, "created")
        self.assertEqual(s2, "skipped")
        self.assertEqual(counters["conflict"], 1)

    def test_invalid_iban_logs_error_and_skips(self):
        _create_member_with_procurios_id(self, "PROC-7")
        doc = _create_stub_import_doc()
        caches = doc._build_caches()
        counters = _empty_skip_counters()
        errors = []
        row = _make_mandate_row(mandate_id="M-BAD", debiteur_id="PROC-7", iban="NOT-AN-IBAN")

        status, _ = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(counters["error"], 1)
        self.assertTrue(any("Row 1" in e for e in errors))
