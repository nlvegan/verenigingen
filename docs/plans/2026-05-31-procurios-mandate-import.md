# Procurios SEPA Mandate Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `Procurios Mandate Import` DocType that imports SEPA mandates from a Procurios CSV export, matching `Debiteur ID → Member.procurios_id` and creating linked `SEPA Mandate` documents.

**Architecture:** New submittable DocType under the Verenigingen Payments module mirroring the existing `Procurios CSV Import` (attach CSV → validate/preview → submit → long-queue background job). A pure-Python `ProcuriosMandateValidator` handles CSV-shape validation and field mapping. The controller pre-builds three in-memory caches (member lookup, existing-mandate lookup, members-with-active-mandate) so the per-row loop performs no DB lookups for matching/duplicate/conflict checks — sized for a few thousand rows.

**Tech Stack:** Frappe DocType, Python 3.x, existing `SecureCSVParser` + `CSVImportBackgroundProcessor` infrastructure, `EnhancedTestCase` for integration tests.

**Design doc:** `docs/plans/2026-05-27-procurios-mandate-import-design.md`

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/__init__.py` | Empty package marker |
| `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.json` | DocType schema (fields, naming, permissions, `is_submittable`) |
| `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py` | Controller: validate/preview, build caches, per-row processor, finalize, background-job entry point |
| `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.js` | Client script: `Validate CSV` button, auto-refresh while running |
| `verenigingen/utils/csv/procurios_mandate_validator.py` | Pure CSV-shape validation + row → `ProcuriosMandateRow` mapping; no DB |
| `verenigingen/tests/payment/test_procurios_mandate_validator.py` | Unit tests for the validator (no DB) |
| `verenigingen/tests/payment/test_procurios_mandate_import.py` | Integration tests via `EnhancedTestCase`, real DB |

### Reused (not modified)

- `verenigingen/utils/csv/secure_csv_parser.py` — `SecureCSVParser`
- `verenigingen/utils/csv_import_processor.py` — `CSVImportBackgroundProcessor`
- `verenigingen/utils/error_handling.py` — `sanitize_error_for_audit`
- `verenigingen/verenigingen_payments/doctype/sepa_mandate/sepa_mandate.py` — target DocType (creates via `frappe.get_doc(...).insert()`)
- Existing `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py` — pattern reference

### Note on test location

The design doc mentioned tests under the DocType directory; the project's actual convention (per the 2026-03-09 test reorganization) is **centralised under `verenigingen/tests/<domain>/`**. This plan follows the project convention.

---

## Task 1: Create empty DocType skeleton + JSON schema

**Files:**
- Create: `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/__init__.py`
- Create: `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.json`
- Create: `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py` (minimal stub)

- [ ] **Step 1.1: Create the package marker**

```bash
mkdir -p verenigingen/verenigingen_payments/doctype/procurios_mandate_import
touch verenigingen/verenigingen_payments/doctype/procurios_mandate_import/__init__.py
```

- [ ] **Step 1.2: Write the DocType JSON**

Create `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.json`:

```json
{
  "actions": [],
  "autoname": "naming_series:",
  "creation": "2026-05-31 10:00:00.000000",
  "doctype": "DocType",
  "editable_grid": 1,
  "engine": "InnoDB",
  "field_order": [
    "naming_series",
    "import_configuration_section",
    "csv_file",
    "encoding",
    "csv_delimiter",
    "column_break_config1",
    "test_mode",
    "preview_section",
    "preview_data",
    "progress_section",
    "import_status",
    "progress_percentage",
    "rows_processed",
    "total_rows",
    "column_break_progress1",
    "mandates_created",
    "mandates_updated",
    "mandates_skipped",
    "last_processed_at",
    "error_section",
    "error_log",
    "skipped_summary",
    "import_info_section",
    "import_date",
    "descriptive_name"
  ],
  "fields": [
    {"fieldname": "naming_series", "fieldtype": "Select", "hidden": 1, "label": "Naming Series", "options": "PROC-MND-IMP-.YYYY.-.####.", "default": "PROC-MND-IMP-.YYYY.-.####."},
    {"fieldname": "import_configuration_section", "fieldtype": "Section Break", "label": "Import Configuration"},
    {"fieldname": "csv_file", "fieldtype": "Attach", "label": "CSV File", "reqd": 1},
    {"default": "auto-detect", "fieldname": "encoding", "fieldtype": "Select", "label": "Encoding", "options": "auto-detect\nutf-8\nutf-8-sig\niso-8859-1\nwindows-1252"},
    {"default": "Semicolon", "fieldname": "csv_delimiter", "fieldtype": "Select", "label": "CSV Delimiter", "options": "Comma\nSemicolon\nTab"},
    {"fieldname": "column_break_config1", "fieldtype": "Column Break"},
    {"default": "0", "fieldname": "test_mode", "fieldtype": "Check", "label": "Test Mode", "description": "Process only first 25 rows for validation"},
    {"depends_on": "eval:doc.import_status == 'Ready for Import'", "fieldname": "preview_section", "fieldtype": "Section Break", "label": "Data Preview"},
    {"allow_on_submit": 1, "fieldname": "preview_data", "fieldtype": "Code", "label": "Preview Data", "options": "JSON", "read_only": 1},
    {"depends_on": "eval:['Queued', 'In Progress', 'Completed', 'Failed'].includes(doc.import_status)", "fieldname": "progress_section", "fieldtype": "Section Break", "label": "Import Progress"},
    {"allow_on_submit": 1, "default": "Pending", "fieldname": "import_status", "fieldtype": "Select", "label": "Import Status", "options": "Pending\nValidating\nReady for Import\nQueued\nIn Progress\nCompleted\nFailed", "read_only": 1},
    {"allow_on_submit": 1, "default": "0", "fieldname": "progress_percentage", "fieldtype": "Percent", "label": "Progress", "read_only": 1},
    {"allow_on_submit": 1, "default": "0", "fieldname": "rows_processed", "fieldtype": "Int", "label": "Rows Processed", "read_only": 1},
    {"allow_on_submit": 1, "default": "0", "fieldname": "total_rows", "fieldtype": "Int", "label": "Total Rows", "read_only": 1},
    {"fieldname": "column_break_progress1", "fieldtype": "Column Break"},
    {"allow_on_submit": 1, "default": "0", "fieldname": "mandates_created", "fieldtype": "Int", "label": "Mandates Created", "read_only": 1},
    {"allow_on_submit": 1, "default": "0", "fieldname": "mandates_updated", "fieldtype": "Int", "label": "Mandates Updated", "read_only": 1},
    {"allow_on_submit": 1, "default": "0", "fieldname": "mandates_skipped", "fieldtype": "Int", "label": "Mandates Skipped", "read_only": 1},
    {"allow_on_submit": 1, "fieldname": "last_processed_at", "fieldtype": "Datetime", "label": "Last Processed At", "read_only": 1},
    {"depends_on": "eval:['Completed', 'Failed'].includes(doc.import_status)", "fieldname": "error_section", "fieldtype": "Section Break", "label": "Error Log"},
    {"allow_on_submit": 1, "fieldname": "error_log", "fieldtype": "Long Text", "label": "Error Log", "read_only": 1},
    {"allow_on_submit": 1, "fieldname": "skipped_summary", "fieldtype": "Small Text", "label": "Skipped Summary", "read_only": 1},
    {"fieldname": "import_info_section", "fieldtype": "Section Break", "label": "Import Information", "hidden": 1},
    {"fieldname": "import_date", "fieldtype": "Date", "label": "Import Date", "read_only": 1},
    {"fieldname": "descriptive_name", "fieldtype": "Data", "label": "Descriptive Name", "read_only": 1}
  ],
  "index_web_pages_for_search": 0,
  "is_submittable": 1,
  "links": [],
  "modified": "2026-05-31 10:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen Payments",
  "name": "Procurios Mandate Import",
  "naming_rule": "By \"Naming Series\" field",
  "owner": "Administrator",
  "permissions": [
    {"create": 1, "delete": 1, "email": 1, "export": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "submit": 1, "write": 1},
    {"create": 1, "delete": 1, "email": 1, "export": 1, "read": 1, "report": 1, "role": "Verenigingen Administrator", "share": 1, "submit": 1, "write": 1}
  ],
  "sort_field": "creation",
  "sort_order": "DESC",
  "states": [],
  "track_changes": 1
}
```

- [ ] **Step 1.3: Write the minimal controller stub**

Create `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProcuriosMandateImport(Document):
    pass
```

- [ ] **Step 1.4: Reload and verify the DocType installs**

Run: `bench --site veg11.veganisme.org reload-doctype "Procurios Mandate Import" && bench --site veg11.veganisme.org clear-cache`

Expected: no errors. The DocType should appear in `bench --site veg11.veganisme.org console`:

```python
import frappe; print(frappe.db.exists("DocType", "Procurios Mandate Import"))
# expected: 'Procurios Mandate Import'
```

- [ ] **Step 1.5: Commit**

```bash
git add verenigingen/verenigingen_payments/doctype/procurios_mandate_import/
git commit -m "feat(procurios-mandate-import): scaffold DocType skeleton"
```

---

## Task 2: ProcuriosMandateValidator — CSV mapping (TDD, no DB)

**Files:**
- Create: `verenigingen/utils/csv/procurios_mandate_validator.py`
- Create: `verenigingen/tests/payment/test_procurios_mandate_validator.py`

The validator is pure Python — no DB access — so it can be exhaustively unit-tested without bench/site overhead.

- [ ] **Step 2.1: Write the failing test file**

Create `verenigingen/tests/payment/test_procurios_mandate_validator.py`:

```python
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
```

- [ ] **Step 2.2: Run the test — verify it fails**

```bash
cd ~/frappe-bench/apps/verenigingen
python -m pytest verenigingen/tests/payment/test_procurios_mandate_validator.py -v
```

Expected: `ModuleNotFoundError: No module named 'verenigingen.utils.csv.procurios_mandate_validator'`.

- [ ] **Step 2.3: Implement the validator**

Create `verenigingen/utils/csv/procurios_mandate_validator.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""CSV-shape validation and row mapping for the Procurios SEPA mandate export.

Pure Python: no DB access. Per-row business rules (member match,
duplicate detection, member conflict) live in the import controller,
which has DB state and pre-built caches.

Design: docs/plans/2026-05-27-procurios-mandate-import-design.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

CANCELLED_CUTOFF_MONTHS = 12

REQUIRED_COLUMNS = [
    "Mandaatnummer",
    "IBAN",
    "Rekeninghouder",
    "Debiteur ID",
    "Datum van ondertekening",
]

MANDATE_TYPE_MAP = {
    "doorlopend": "RCUR",
    "eenmalig": "OOFF",
}


@dataclass
class ProcuriosMandateRow:
    """A single Procurios CSV row mapped to SEPA Mandate domain fields.

    `cancelled_date` is ISO `YYYY-MM-DD` or None. `is_cancelled` is a
    convenience flag so the controller can branch without re-parsing.
    `notes` is composed traceability text destined for SEPA Mandate.notes.
    """

    row_number: int
    mandate_id: str
    iban: str
    account_holder_name: str
    debiteur_id: str
    debiteur_naam: str
    sign_date: str
    cancelled_date: Optional[str]
    mandate_type: str
    notes: str

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_date is not None


class ProcuriosMandateValidator:
    """Maps Procurios SEPA mandate CSV rows to ProcuriosMandateRow objects."""

    def __init__(
        self,
        cutoff_months: int = CANCELLED_CUTOFF_MONTHS,
        today: Optional[date] = None,
    ):
        self.cutoff_months = cutoff_months
        self._today = today or date.today()

    # ---- public API ---------------------------------------------------

    def check_required_columns(self, headers: List[str]) -> List[str]:
        """Return the list of required columns missing from headers."""
        present = set(headers)
        return [c for c in REQUIRED_COLUMNS if c not in present]

    def validate_and_map(
        self, csv_data: List[Dict]
    ) -> Tuple[List[ProcuriosMandateRow], List[str], int]:
        """Map every CSV row.

        Returns (mapped_rows, errors, filtered_old_cancelled_count).
        Rows that cancelled longer ago than the cutoff are dropped here
        and counted in `filtered_old_cancelled_count`. Per-row mapping
        errors are appended to `errors` and the bad row is skipped — they
        never abort the batch.
        """
        mapped: List[ProcuriosMandateRow] = []
        errors: List[str] = []
        filtered_old = 0

        for idx, row in enumerate(csv_data, start=1):
            try:
                m = self.map_row(row, row_num=idx)
            except ValueError as e:
                errors.append(str(e))
                continue

            if m.cancelled_date and self._is_too_old_cancelled(m.cancelled_date):
                filtered_old += 1
                continue

            mapped.append(m)

        return mapped, errors, filtered_old

    def map_row(self, row: Dict, row_num: int) -> ProcuriosMandateRow:
        """Map one CSV row. Raises ValueError on bad row (caller continues)."""
        # Required-field presence check
        for col in REQUIRED_COLUMNS:
            value = (row.get(col) or "").strip()
            if not value:
                raise ValueError(
                    f"Row {row_num}: required column '{col}' is empty"
                )

        sign_date = self._parse_date(row["Datum van ondertekening"], row_num, "Datum van ondertekening")
        opzeg = (row.get("Opzegdatum") or "").strip()
        cancelled_date = (
            self._parse_date(opzeg, row_num, "Opzegdatum") if opzeg else None
        )

        return ProcuriosMandateRow(
            row_number=row_num,
            mandate_id=row["Mandaatnummer"].strip(),
            iban=row["IBAN"].strip().upper(),
            account_holder_name=row["Rekeninghouder"].strip(),
            debiteur_id=row["Debiteur ID"].strip(),
            debiteur_naam=(row.get("Debiteur naam") or "").strip(),
            sign_date=sign_date,
            cancelled_date=cancelled_date,
            mandate_type=self._map_mandate_type(row.get("Type machtiging", "")),
            notes=self._compose_notes(row),
        )

    # ---- helpers ------------------------------------------------------

    def _is_too_old_cancelled(self, cancelled_iso: str) -> bool:
        """True if `cancelled_iso` is more than `cutoff_months` before today."""
        cancelled = date.fromisoformat(cancelled_iso)
        # Approximate months as 30-day windows. Exact calendar-month math
        # would need dateutil; this is well within tolerance for a 12-month
        # business cutoff.
        cutoff_days = self.cutoff_months * 30
        return (self._today - cancelled).days > cutoff_days

    def _map_mandate_type(self, type_text: str) -> str:
        return MANDATE_TYPE_MAP.get((type_text or "").strip().lower(), "RCUR")

    def _parse_date(self, value: str, row_num: int, field: str) -> str:
        """Parse a Procurios date (YYYY-MM-DD). Raises ValueError on bad input."""
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Row {row_num}: invalid {field} '{value}': {e}") from e

    def _compose_notes(self, row: Dict) -> str:
        """Compose traceability text for SEPA Mandate.notes."""
        parts = ["Imported from Procurios."]
        if row.get("Incasso-afspraak ID"):
            parts.append(f"Incasso-afspraak ID {row['Incasso-afspraak ID']}.")
        if row.get("Administratie"):
            parts.append(f"Administratie: {row['Administratie']}.")
        if (row.get("Pre-notificatie datum") or "").strip():
            parts.append(f"Pre-notificatie datum: {row['Pre-notificatie datum']}.")
        return " ".join(parts)
```

- [ ] **Step 2.4: Run the test — verify it passes**

```bash
cd ~/frappe-bench/apps/verenigingen
python -m pytest verenigingen/tests/payment/test_procurios_mandate_validator.py -v
```

Expected: all 12 tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add verenigingen/utils/csv/procurios_mandate_validator.py verenigingen/tests/payment/test_procurios_mandate_validator.py
git commit -m "feat(procurios-mandate-import): add ProcuriosMandateValidator with unit tests"
```

---

## Task 3: Validate-and-preview flow (controller)

**Files:**
- Modify: `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py`

This task adds the read-CSV → validate-shape → write-preview flow that the user triggers from the form **before** submitting. No row creation yet.

- [ ] **Step 3.1: Write the failing integration test**

Create `verenigingen/tests/payment/test_procurios_mandate_import.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Integration tests for the Procurios Mandate Import flow.

Real DB. No business-logic mocks (per project test-quality enforcer).
"""

import csv
import io
import json
import os
import tempfile

import frappe
from frappe.utils import now_datetime

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


def _write_csv_attach(rows):
    """Write rows to a temp file, register as a Frappe File, return its file_url."""
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


class TestProcuriosMandateImportValidate(EnhancedTestCase):
    """Validate / preview phase — no submission."""

    def test_validate_marks_ready_with_preview(self):
        rows = [_base_row(Mandaatnummer="M-001"), _base_row(Mandaatnummer="M-002")]
        file_url = _write_csv_attach(rows)

        doc = frappe.get_doc({
            "doctype": "Procurios Mandate Import",
            "csv_file": file_url,
            "csv_delimiter": "Semicolon",
        })
        doc.flags.ignore_permissions = True
        doc.insert()

        doc._validate_and_preview_csv()
        doc.reload()

        self.assertEqual(doc.import_status, "Ready for Import")
        self.assertEqual(doc.total_rows, 2)
        preview = json.loads(doc.preview_data)
        self.assertEqual(len(preview), 2)
        self.assertEqual(preview[0]["mandate_id"], "M-001")

    def test_validate_fails_on_missing_required_column(self):
        # Write a CSV that's missing 'Mandaatnummer'
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("IBAN;Rekeninghouder\nNL91ABNA0417164300;J. Jansen\n")
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

        doc = frappe.get_doc({
            "doctype": "Procurios Mandate Import",
            "csv_file": file_doc.file_url,
            "csv_delimiter": "Semicolon",
        })
        doc.flags.ignore_permissions = True
        doc.insert()

        doc._validate_and_preview_csv()
        doc.reload()

        self.assertEqual(doc.import_status, "Failed")
        self.assertIn("Mandaatnummer", doc.error_log or "")
```

- [ ] **Step 3.2: Run the test — verify it fails**

```bash
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_procurios_mandate_import
```

Expected: `AttributeError: 'ProcuriosMandateImport' object has no attribute '_validate_and_preview_csv'`.

- [ ] **Step 3.3: Implement validate/preview**

Replace `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py` with:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Procurios SEPA Mandate Import controller.

Imports SEPA mandates from a Procurios CSV export. Matches Debiteur ID
to existing Member.procurios_id. Per-row business rules: skip
old-cancelled (>12mo), skip-no-member, duplicate (update if cancelled,
otherwise skip), conflict (active rows only, member with another active
mandate is skipped), else create.

Design: docs/plans/2026-05-27-procurios-mandate-import-design.md
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

import frappe
from frappe.model.document import Document
from frappe.utils import today

from verenigingen.utils.csv.procurios_mandate_validator import (
    ProcuriosMandateValidator,
)
from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.error_handling import sanitize_error_for_audit


class ProcuriosMandateImport(Document):
    @property
    def _parser(self) -> SecureCSVParser:
        if not hasattr(self, "__parser"):
            encoding = None if self.encoding == "auto-detect" else self.encoding
            self.__parser = SecureCSVParser(encoding=encoding, delimiter=self.csv_delimiter)
        return self.__parser

    @property
    def _validator(self) -> ProcuriosMandateValidator:
        if not hasattr(self, "__validator"):
            self.__validator = ProcuriosMandateValidator()
        return self.__validator

    def validate(self):
        if not self.import_date:
            self.import_date = today()

    # ---- validate / preview -------------------------------------------

    def _read_csv_file(self) -> List[Dict]:
        return self._parser.read_csv_file(self.csv_file)

    def _validate_and_preview_csv(self) -> None:
        """Read the CSV, check shape, build a preview, set status."""
        self.db_set("import_status", "Validating")
        frappe.db.commit()

        try:
            csv_data = self._read_csv_file()
            if not csv_data:
                self.db_set("import_status", "Failed")
                self.db_set("error_log", "CSV file is empty or could not be read")
                frappe.db.commit()
                return

            headers = list(csv_data[0].keys())
            missing = self._validator.check_required_columns(headers)
            if missing:
                self.db_set("import_status", "Failed")
                self.db_set(
                    "error_log",
                    "Missing required columns: " + ", ".join(missing),
                )
                frappe.db.commit()
                return

            mapped, errors, filtered_old = self._validator.validate_and_map(csv_data)

            if errors:
                self.db_set("error_log", "\n".join(errors[:50]))

            if mapped:
                preview = [
                    {
                        "mandate_id": m.mandate_id,
                        "iban": m.iban,
                        "account_holder_name": m.account_holder_name,
                        "debiteur_id": m.debiteur_id,
                        "debiteur_naam": m.debiteur_naam,
                        "sign_date": m.sign_date,
                        "cancelled_date": m.cancelled_date,
                        "mandate_type": m.mandate_type,
                        "is_cancelled": m.is_cancelled,
                    }
                    for m in mapped[:5]
                ]
                self.db_set("preview_data", json.dumps(preview, indent=2, default=str))

            self.db_set("total_rows", len(csv_data))
            self.db_set(
                "descriptive_name",
                f"Procurios mandate import — {len(csv_data)} rows "
                f"({filtered_old} cancelled outside cutoff)",
            )

            if mapped:
                self.db_set("import_status", "Ready for Import")
            else:
                self.db_set("import_status", "Failed")
                if not errors:
                    self.db_set("error_log", "No valid rows found in CSV")

            frappe.db.commit()

        except Exception as e:
            self.db_set("import_status", "Failed")
            self.db_set("error_log", sanitize_error_for_audit(str(e)))
            frappe.db.commit()
            raise


@frappe.whitelist()
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation (called from the client script)."""
    doc = frappe.get_doc("Procurios Mandate Import", import_doc_name)
    try:
        doc._validate_and_preview_csv()
        doc.reload()
        return {
            "status": "success" if doc.import_status == "Ready for Import" else "error",
            "message": f"Validation complete. Status: {doc.import_status}",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": sanitize_error_for_audit(str(e)),
        }
```

- [ ] **Step 3.4: Reload the DocType controller and rerun the tests**

```bash
bench --site veg11.veganisme.org reload-doctype "Procurios Mandate Import"
bench --site veg11.veganisme.org clear-cache
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_procurios_mandate_import
```

Expected: both `test_validate_marks_ready_with_preview` and `test_validate_fails_on_missing_required_column` pass.

- [ ] **Step 3.5: Commit**

```bash
git add verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py verenigingen/tests/payment/test_procurios_mandate_import.py
git commit -m "feat(procurios-mandate-import): validate + preview CSV flow"
```

---

## Task 4: Per-row processor — caches, create, update, skip

**Files:**
- Modify: `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py`
- Modify: `verenigingen/tests/payment/test_procurios_mandate_import.py`

This task implements the five-step decision logic and the three caches. It's the core of the import.

- [ ] **Step 4.1: Write the failing tests**

Append to `verenigingen/tests/payment/test_procurios_mandate_import.py`:

```python
class TestProcuriosMandateImportProcessRow(EnhancedTestCase):
    """Per-row processor — exercises every branch of the decision tree."""

    def _make_member(self, procurios_id: str, **kwargs):
        member = self.create_test_member(procurios_id=procurios_id, **kwargs)
        return member

    def _make_active_mandate(self, member_name: str, mandate_id: str, iban: str):
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

    def _make_import_doc(self):
        # csv_file is required on the JSON schema but we don't read it here.
        # Insert with a dummy file_url; the per-row processor doesn't touch the file.
        file_doc = frappe.get_doc({
            "doctype": "File", "file_name": "stub.csv",
            "is_private": 1, "content": b"stub",
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

    def _row(self, **kw):
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

    def test_creates_mandate_when_member_exists(self):
        member = self._make_member("PROC-1")
        doc = self._make_import_doc()
        caches = doc._build_caches()
        counters = {"filtered_old_cancelled": 0, "no_member": 0,
                    "duplicate": 0, "conflict": 0, "error": 0}
        errors = []
        row = self._row(mandate_id="M-100", debiteur_id="PROC-1")

        status, name = doc._process_single_row(row, errors, caches, counters)

        self.assertEqual(status, "created")
        mandate = frappe.get_doc("SEPA Mandate", name)
        self.assertEqual(mandate.member, member.name)
        self.assertEqual(mandate.status, "Active")
        self.assertEqual(mandate.iban, "NL91ABNA0417164300")
        # Cache must be updated so a subsequent active row for same member triggers conflict.
        self.assertIn(member.name, caches.members_with_active_mandate)

    def test_skips_when_no_member_match(self):
        doc = self._make_import_doc()
        caches = doc._build_caches()
        counters = {"filtered_old_cancelled": 0, "no_member": 0,
                    "duplicate": 0, "conflict": 0, "error": 0}
        errors = []
        row = self._row(debiteur_id="NO-SUCH-ID")

        status, name = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(name, "")
        self.assertEqual(counters["no_member"], 1)

    def test_skips_duplicate_active(self):
        member = self._make_member("PROC-2")
        existing = self._make_active_mandate(member.name, "M-DUP", "NL91ABNA0417164300")
        doc = self._make_import_doc()
        caches = doc._build_caches()
        counters = {"filtered_old_cancelled": 0, "no_member": 0,
                    "duplicate": 0, "conflict": 0, "error": 0}
        errors = []
        row = self._row(mandate_id="M-DUP", debiteur_id="PROC-2")

        status, _ = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(counters["duplicate"], 1)

    def test_updates_existing_when_csv_cancelled(self):
        member = self._make_member("PROC-3")
        existing = self._make_active_mandate(member.name, "M-UPD", "NL91ABNA0417164300")
        doc = self._make_import_doc()
        caches = doc._build_caches()
        counters = {"filtered_old_cancelled": 0, "no_member": 0,
                    "duplicate": 0, "conflict": 0, "error": 0}
        errors = []
        row = self._row(
            mandate_id="M-UPD", debiteur_id="PROC-3", cancelled_date="2025-12-01"
        )

        status, name = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "updated")
        updated = frappe.get_doc("SEPA Mandate", existing.name)
        self.assertEqual(str(updated.cancelled_date), "2025-12-01")
        self.assertEqual(updated.status, "Cancelled")

    def test_skips_conflict_when_member_has_other_active(self):
        member = self._make_member("PROC-4")
        self._make_active_mandate(member.name, "M-EXISTING", "NL91ABNA0417164300")
        doc = self._make_import_doc()
        caches = doc._build_caches()
        counters = {"filtered_old_cancelled": 0, "no_member": 0,
                    "duplicate": 0, "conflict": 0, "error": 0}
        errors = []
        row = self._row(mandate_id="M-NEW", debiteur_id="PROC-4")

        status, _ = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(counters["conflict"], 1)
        self.assertFalse(frappe.db.exists("SEPA Mandate", {"mandate_id": "M-NEW"}))

    def test_cancelled_row_for_member_with_active_mandate_still_imports(self):
        # A historical cancelled mandate doesn't conflict with an active one.
        member = self._make_member("PROC-5")
        self._make_active_mandate(member.name, "M-ACTIVE", "NL91ABNA0417164300")
        doc = self._make_import_doc()
        caches = doc._build_caches()
        counters = {"filtered_old_cancelled": 0, "no_member": 0,
                    "duplicate": 0, "conflict": 0, "error": 0}
        errors = []
        row = self._row(
            mandate_id="M-OLD", debiteur_id="PROC-5", cancelled_date="2025-12-01"
        )

        status, name = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "created")
        mandate = frappe.get_doc("SEPA Mandate", name)
        self.assertEqual(mandate.status, "Cancelled")
        self.assertEqual(counters["conflict"], 0)

    def test_two_active_rows_same_member_second_conflicts(self):
        member = self._make_member("PROC-6")
        doc = self._make_import_doc()
        caches = doc._build_caches()  # member has no active mandate yet
        counters = {"filtered_old_cancelled": 0, "no_member": 0,
                    "duplicate": 0, "conflict": 0, "error": 0}
        errors = []

        s1, _ = doc._process_single_row(
            self._row(mandate_id="M-A", debiteur_id="PROC-6"),
            errors, caches, counters,
        )
        s2, _ = doc._process_single_row(
            self._row(mandate_id="M-B", debiteur_id="PROC-6"),
            errors, caches, counters,
        )
        self.assertEqual(s1, "created")
        self.assertEqual(s2, "skipped")
        self.assertEqual(counters["conflict"], 1)

    def test_invalid_iban_logs_error_and_skips(self):
        self._make_member("PROC-7")
        doc = self._make_import_doc()
        caches = doc._build_caches()
        counters = {"filtered_old_cancelled": 0, "no_member": 0,
                    "duplicate": 0, "conflict": 0, "error": 0}
        errors = []
        row = self._row(mandate_id="M-BAD", debiteur_id="PROC-7", iban="NOT-AN-IBAN")

        status, _ = doc._process_single_row(row, errors, caches, counters)
        self.assertEqual(status, "skipped")
        self.assertEqual(counters["error"], 1)
        self.assertTrue(any("M-BAD" in e or "Row 1" in e for e in errors))
```

- [ ] **Step 4.2: Run — verify the new tests fail**

```bash
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_procurios_mandate_import
```

Expected: `AttributeError: '...' has no attribute '_build_caches'` (or `_process_single_row`).

- [ ] **Step 4.3: Implement caches + per-row processor**

Append to `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py` (inside the `ProcuriosMandateImport` class — add the helper dataclass at module top):

At module top (after the existing imports), add:

```python
from dataclasses import dataclass, field
from typing import Set, Tuple

from verenigingen.utils.csv.procurios_mandate_validator import ProcuriosMandateRow


@dataclass
class _Caches:
    """Pre-built lookup tables — populated once before the per-row loop."""

    procurios_id_to_member: Dict[str, str] = field(default_factory=dict)
    existing_mandate_by_id: Dict[str, Dict] = field(default_factory=dict)
    members_with_active_mandate: Set[str] = field(default_factory=set)
```

Inside `ProcuriosMandateImport`, add the cache builder and per-row processor:

```python
    # ---- caches -------------------------------------------------------

    def _build_caches(self) -> _Caches:
        """Build all three lookup caches with one query each.

        Designed for a few thousand rows: each query is well-indexed and
        loads only the fields needed for the per-row decisions.
        """
        caches = _Caches()

        for m in frappe.get_all(
            "Member",
            filters={"procurios_id": ["!=", ""]},
            fields=["name", "procurios_id"],
        ):
            if m.procurios_id:
                caches.procurios_id_to_member[m.procurios_id] = m.name

        for sm in frappe.get_all(
            "SEPA Mandate",
            fields=["name", "mandate_id", "status", "cancelled_date", "member"],
        ):
            if sm.mandate_id:
                caches.existing_mandate_by_id[sm.mandate_id] = {
                    "name": sm.name,
                    "status": sm.status,
                    "cancelled_date": sm.cancelled_date,
                    "member": sm.member,
                }
                if sm.status == "Active" and sm.member:
                    caches.members_with_active_mandate.add(sm.member)

        return caches

    # ---- per-row processor -------------------------------------------

    def _process_single_row(
        self,
        row: ProcuriosMandateRow,
        error_log: List[str],
        caches: _Caches,
        skip_counters: Dict[str, int],
    ) -> Tuple[str, str]:
        """Process one mapped row. Returns (status, mandate_name).

        Status is one of: "created", "updated", "skipped". On skip, the
        relevant counter in `skip_counters` is incremented. Per-row
        exceptions are caught, logged, and counted under "error" — they
        never propagate.
        """
        try:
            # 1. Member match
            member_name = caches.procurios_id_to_member.get(row.debiteur_id)
            if not member_name:
                skip_counters["no_member"] += 1
                error_log.append(
                    f"Row {row.row_number} ({row.debiteur_naam}): "
                    f"no Member with procurios_id={row.debiteur_id}"
                )
                return ("skipped", "")

            # 2. Duplicate check
            existing = caches.existing_mandate_by_id.get(row.mandate_id)
            if existing:
                if row.is_cancelled:
                    # Update path: refresh cancelled_date on the existing mandate.
                    return self._update_cancellation(existing, row, caches)
                skip_counters["duplicate"] += 1
                return ("skipped", "")

            # 3. Conflict check (active rows only)
            if not row.is_cancelled and member_name in caches.members_with_active_mandate:
                skip_counters["conflict"] += 1
                error_log.append(
                    f"Row {row.row_number} ({row.debiteur_naam}): "
                    f"member {member_name} already has an active mandate"
                )
                return ("skipped", "")

            # 4. Create
            return self._create_mandate(row, member_name, caches)

        except Exception as e:
            skip_counters["error"] += 1
            sanitized = sanitize_error_for_audit(str(e))
            error_log.append(
                f"Row {row.row_number} ({row.debiteur_naam}): {sanitized}"
            )
            return ("skipped", "")

    def _create_mandate(
        self,
        row: ProcuriosMandateRow,
        member_name: str,
        caches: _Caches,
    ) -> Tuple[str, str]:
        """Insert a new SEPA Mandate and update caches."""
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": row.mandate_id,
            "member": member_name,
            "account_holder_name": row.account_holder_name,
            "iban": row.iban,
            "sign_date": row.sign_date,
            "cancelled_date": row.cancelled_date,  # blank for active, set for cancelled
            "mandate_type": row.mandate_type,
            "scheme": "SEPA",
            "used_for_memberships": 1,
            "notes": row.notes,
        })
        mandate.flags.ignore_permissions = True
        mandate.insert()

        # Cache updates so subsequent rows see the new state.
        caches.existing_mandate_by_id[row.mandate_id] = {
            "name": mandate.name,
            "status": mandate.status,
            "cancelled_date": mandate.cancelled_date,
            "member": member_name,
        }
        if mandate.status == "Active":
            caches.members_with_active_mandate.add(member_name)

        return ("created", mandate.name)

    def _update_cancellation(
        self,
        existing: Dict,
        row: ProcuriosMandateRow,
        caches: _Caches,
    ) -> Tuple[str, str]:
        """Mark an existing mandate as cancelled, refreshing cancelled_date.

        Uses frappe.get_doc + save so the lifecycle service flips status
        to Cancelled. ignore_permissions because the bulk import runs in
        a background job.
        """
        mandate = frappe.get_doc("SEPA Mandate", existing["name"])
        mandate.cancelled_date = row.cancelled_date
        mandate.flags.ignore_permissions = True
        mandate.save()

        # Cache refresh: the member no longer has *this* mandate as active.
        if existing.get("member") in caches.members_with_active_mandate:
            # Only safe to drop if no other active mandate remains. Re-query.
            still_active = frappe.db.exists(
                "SEPA Mandate",
                {"member": existing["member"], "status": "Active"},
            )
            if not still_active:
                caches.members_with_active_mandate.discard(existing["member"])

        existing["status"] = mandate.status
        existing["cancelled_date"] = mandate.cancelled_date

        return ("updated", mandate.name)
```

- [ ] **Step 4.4: Run — verify all per-row tests pass**

```bash
bench --site veg11.veganisme.org clear-cache
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_procurios_mandate_import
```

Expected: all 8 `TestProcuriosMandateImportProcessRow` tests pass plus the 2 from Task 3.

- [ ] **Step 4.5: Commit**

```bash
git add verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py verenigingen/tests/payment/test_procurios_mandate_import.py
git commit -m "feat(procurios-mandate-import): per-row create/update/skip with caches"
```

---

## Task 5: Background-job orchestration + finalize

**Files:**
- Modify: `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py`
- Modify: `verenigingen/tests/payment/test_procurios_mandate_import.py`

This task wires `on_submit` → background job → `CSVImportBackgroundProcessor` → finalize. It tests the full end-to-end flow synchronously (calling `process_import_background` in-process, not via the queue).

- [ ] **Step 5.1: Write the failing end-to-end test**

Append to `verenigingen/tests/payment/test_procurios_mandate_import.py`:

```python
from verenigingen.verenigingen_payments.doctype.procurios_mandate_import.procurios_mandate_import import (
    process_import_background,
)


class TestProcuriosMandateImportEndToEnd(EnhancedTestCase):
    """Full validate → process flow run in-process."""

    def test_end_to_end_mixed_outcomes(self):
        # Members
        m_active = self.create_test_member(procurios_id="E2E-ACT")
        m_cancel = self.create_test_member(procurios_id="E2E-CAN")
        m_orphan = self.create_test_member(procurios_id="E2E-ORPH")  # no mandate row
        # one row will reference a procurios_id that has no Member

        # An existing active mandate that will be updated by a cancelled row
        existing = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "mandate_id": "E2E-EXISTING",
            "member": m_cancel.name,
            "account_holder_name": "Existing Holder",
            "iban": "NL91ABNA0417164300",
            "sign_date": "2022-01-01",
            "mandate_type": "RCUR",
            "scheme": "SEPA",
        })
        existing.flags.ignore_permissions = True
        existing.insert()

        rows = [
            # active import, member exists, new mandate id → CREATED
            _base_row(Mandaatnummer="E2E-NEW",  Opzegdatum="",            **{"Debiteur ID": "E2E-ACT"}),
            # cancelled import, matches existing mandate id → UPDATED
            _base_row(Mandaatnummer="E2E-EXISTING", Opzegdatum="2025-12-01", **{"Debiteur ID": "E2E-CAN"}),
            # cancelled long ago → FILTERED
            _base_row(Mandaatnummer="E2E-OLD",  Opzegdatum="2020-01-01",  **{"Debiteur ID": "E2E-ORPH"}),
            # debiteur with no member → NO MEMBER
            _base_row(Mandaatnummer="E2E-NOMBR", Opzegdatum="",            **{"Debiteur ID": "DOES-NOT-EXIST"}),
        ]
        file_url = _write_csv_attach(rows)

        doc = frappe.get_doc({
            "doctype": "Procurios Mandate Import",
            "csv_file": file_url,
            "csv_delimiter": "Semicolon",
        })
        doc.flags.ignore_permissions = True
        doc.insert()
        doc.submit()  # enqueues, but we drive synchronously

        # Drive the background entry point directly so the test runs deterministically.
        process_import_background(doc.name, test_mode=False)

        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        self.assertEqual(doc.mandates_created, 1)
        self.assertEqual(doc.mandates_updated, 1)
        # skipped = filtered_old_cancelled + no_member = 2
        self.assertEqual(doc.mandates_skipped, 2)

        # Reasons captured in skipped_summary
        self.assertIn("filtered_old_cancelled: 1", doc.skipped_summary)
        self.assertIn("no_member: 1", doc.skipped_summary)

        # Created mandate is linked to the member's sepa_mandates table via after_insert.
        member = frappe.get_doc("Member", m_active.name)
        member_mandate_ids = [link.mandate_reference for link in (member.sepa_mandates or [])]
        self.assertIn("E2E-NEW", member_mandate_ids)

        # Existing mandate now cancelled.
        existing.reload()
        self.assertEqual(existing.status, "Cancelled")
        self.assertEqual(str(existing.cancelled_date), "2025-12-01")
```

- [ ] **Step 5.2: Run — verify it fails**

```bash
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_procurios_mandate_import
```

Expected: `ImportError: cannot import name 'process_import_background'`.

- [ ] **Step 5.3: Implement on_submit + background job + finalize**

Append to `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py`:

Inside the `ProcuriosMandateImport` class, add:

```python
    # ---- submission ---------------------------------------------------

    def on_submit(self):
        self.db_set("import_status", "Queued")
        frappe.enqueue(
            method=(
                "verenigingen.verenigingen_payments.doctype.procurios_mandate_import."
                "procurios_mandate_import.process_import_background"
            ),
            queue="long",
            timeout=3600,
            import_doc_name=self.name,
            test_mode=bool(self.test_mode),
            now=False,
        )

    # ---- finalize -----------------------------------------------------

    def _finalize_import_results(
        self,
        created_count: int,
        updated_count: int,
        skipped_count: int,
        error_log: List[str],
        _created_records=None,
        _updated_records=None,
        _skipped_records=None,
        skip_counters: Optional[Dict[str, int]] = None,
        filtered_old_cancelled: int = 0,
    ) -> None:
        """Write final counters + bounded error log + per-reason summary."""
        self.reload()
        self.mandates_created = created_count
        self.mandates_updated = updated_count
        # mandates_skipped includes filtered-old (which never reaches the processor)
        self.mandates_skipped = skipped_count + filtered_old_cancelled
        self.import_status = "Completed"

        if error_log:
            truncated = error_log[:50]
            self.error_log = "\n".join(truncated)
            if len(error_log) > 50:
                self.error_log += f"\n... and {len(error_log) - 50} more errors"

        summary_counts = dict(skip_counters or {})
        summary_counts.setdefault("filtered_old_cancelled", 0)
        summary_counts["filtered_old_cancelled"] += filtered_old_cancelled
        self.skipped_summary = "\n".join(
            f"{k}: {summary_counts.get(k, 0)}"
            for k in ("filtered_old_cancelled", "no_member", "duplicate", "conflict", "error")
        )

        self.save(ignore_permissions=True)
        frappe.db.commit()
```

At the module level (alongside `validate_import_file`), add the background entry point:

```python
@frappe.whitelist()
def process_import_background(import_doc_name: str, test_mode: bool = False):
    """Background job: validate, build caches, process, finalize."""
    import traceback
    from verenigingen.utils.csv_import_processor import CSVImportBackgroundProcessor

    frappe.flags.in_background_job = True
    frappe.flags.ignore_version_changes = True

    doc = frappe.get_doc("Procurios Mandate Import", import_doc_name)
    try:
        csv_data = doc._read_csv_file()
        headers = list(csv_data[0].keys()) if csv_data else []
        missing = doc._validator.check_required_columns(headers)
        if missing:
            doc.db_set("import_status", "Failed")
            doc.db_set("error_log", "Missing required columns: " + ", ".join(missing))
            frappe.db.commit()
            return

        mapped, validator_errors, filtered_old = doc._validator.validate_and_map(csv_data)
        if not mapped:
            doc.db_set("import_status", "Failed")
            doc.db_set("error_log", "No valid rows to import")
            frappe.db.commit()
            return

        if test_mode:
            mapped = mapped[:25]

        caches = doc._build_caches()
        skip_counters = {
            "no_member": 0,
            "duplicate": 0,
            "conflict": 0,
            "error": 0,
        }
        seeded_errors = list(validator_errors)

        def _row_callback(mapped_row, error_log_list):
            return doc._process_single_row(
                mapped_row, error_log_list, caches, skip_counters,
            )

        def _finalize(created, updated, skipped, error_log, *records):
            # Prepend validator-stage errors (row-mapping errors that
            # happened before the row reached the processor) so both kinds
            # land in the final error_log.
            combined = seeded_errors + list(error_log)
            doc._finalize_import_results(
                created, updated, skipped, combined,
                *records,
                skip_counters=skip_counters,
                filtered_old_cancelled=filtered_old,
            )

        # `process_import` wraps the loop in bulk_member_operations and
        # commits per batch. 50 is fine for a few thousand rows.
        processor = CSVImportBackgroundProcessor(import_doc_name, "Procurios Mandate Import")
        processor.load_import_doc()
        processor.process_import(
            data_rows=mapped,
            process_row_callback=_row_callback,
            finalize_callback=_finalize,
            batch_size=50,
            batch_commit=True,
        )

    except Exception:
        doc.reload()
        doc.db_set("import_status", "Failed")
        doc.db_set("error_log", sanitize_error_for_audit(traceback.format_exc()))
        frappe.db.commit()
    finally:
        frappe.flags.in_background_job = False
        frappe.flags.ignore_version_changes = False
```

- [ ] **Step 5.4: Run the full test module**

```bash
bench --site veg11.veganisme.org clear-cache
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_procurios_mandate_import
```

Expected: all tests pass. The new `test_end_to_end_mixed_outcomes` should report counters `created=1, updated=1, skipped=2`.

- [ ] **Step 5.5: Commit**

```bash
git add verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py verenigingen/tests/payment/test_procurios_mandate_import.py
git commit -m "feat(procurios-mandate-import): wire background job + finalize"
```

---

## Task 6: Client form script (Validate button + auto-refresh)

**Files:**
- Create: `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.js`

- [ ] **Step 6.1: Implement the client script**

Create `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.js`:

```javascript
// Copyright (c) 2026, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on("Procurios Mandate Import", {
    refresh(frm) {
        // Validate CSV button — only shown before submit, when a CSV is attached
        // and we haven't already produced a successful preview.
        if (
            !frm.is_new() &&
            frm.doc.docstatus === 0 &&
            frm.doc.csv_file &&
            frm.doc.import_status !== "Ready for Import"
        ) {
            frm.add_custom_button(__("Validate CSV"), () => {
                frappe.call({
                    method:
                        "verenigingen.verenigingen_payments.doctype.procurios_mandate_import." +
                        "procurios_mandate_import.validate_import_file",
                    args: { import_doc_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Validating CSV..."),
                    callback: (r) => {
                        if (r.message) {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: r.message.status === "success" ? "green" : "red",
                            });
                            frm.reload_doc();
                        }
                    },
                });
            });
        }

        // While the background job runs, poll for progress.
        if (["Queued", "In Progress"].includes(frm.doc.import_status)) {
            if (!frm._procurios_refresh_handle) {
                frm._procurios_refresh_handle = setInterval(() => {
                    frm.reload_doc();
                }, 5000);
            }
        } else if (frm._procurios_refresh_handle) {
            clearInterval(frm._procurios_refresh_handle);
            frm._procurios_refresh_handle = null;
        }
    },

    onload(frm) {
        // Surface a hint about what the tool does on first open.
        if (frm.is_new()) {
            frm.dashboard.set_headline(
                __("Imports SEPA mandates from the Procurios mandate-export CSV. " +
                    "Only mandates whose Debiteur ID matches an existing Member's procurios_id are imported.")
            );
        }
    },
});
```

- [ ] **Step 6.2: Smoke-test the form**

```bash
bench --site veg11.veganisme.org clear-cache
bench --site veg11.veganisme.org build --app verenigingen
```

Open `/app/procurios-mandate-import/new` in the browser. Expected: form renders, `Validate CSV` button appears once `csv_file` is set + saved.

- [ ] **Step 6.3: Commit**

```bash
git add verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.js
git commit -m "feat(procurios-mandate-import): client form script (validate + auto-refresh)"
```

---

## Task 7: Scale smoke test (500 rows)

**Files:**
- Modify: `verenigingen/tests/payment/test_procurios_mandate_import.py`

A test that proves the caches + batched commits work under realistic volume. Not a benchmark — just protection against accidental O(n²) regressions.

- [ ] **Step 7.1: Write the failing test**

Append to `verenigingen/tests/payment/test_procurios_mandate_import.py`:

```python
import time


class TestProcuriosMandateImportScale(EnhancedTestCase):
    """Volume smoke test — 500 rows, mixed outcomes."""

    def test_500_rows_completes_in_reasonable_time(self):
        # Pre-create 300 members with sequential procurios_ids.
        members = []
        for i in range(300):
            members.append(self.create_test_member(procurios_id=f"SCL-{i}"))

        rows = []
        # 250 "active, new mandate" rows → CREATED
        for i in range(250):
            rows.append(_base_row(
                Mandaatnummer=f"SCL-NEW-{i}",
                **{"Debiteur ID": f"SCL-{i}"},
            ))
        # 100 "no member" rows → SKIPPED no_member
        for i in range(100):
            rows.append(_base_row(
                Mandaatnummer=f"SCL-NOMBR-{i}",
                **{"Debiteur ID": f"NOT-EXISTS-{i}"},
            ))
        # 100 "old cancelled" rows → FILTERED
        for i in range(100):
            rows.append(_base_row(
                Mandaatnummer=f"SCL-OLD-{i}",
                Opzegdatum="2020-01-01",
                **{"Debiteur ID": f"SCL-{i + 250}"},
            ))
        # 50 "active rows that conflict with already-created members above" → CONFLICT
        # (re-uses the first 50 procurios_ids whose CREATED rows ran first)
        for i in range(50):
            rows.append(_base_row(
                Mandaatnummer=f"SCL-CONFLICT-{i}",
                **{"Debiteur ID": f"SCL-{i}"},
            ))

        file_url = _write_csv_attach(rows)

        doc = frappe.get_doc({
            "doctype": "Procurios Mandate Import",
            "csv_file": file_url,
            "csv_delimiter": "Semicolon",
        })
        doc.flags.ignore_permissions = True
        doc.insert()
        doc.submit()

        start = time.monotonic()
        process_import_background(doc.name, test_mode=False)
        elapsed = time.monotonic() - start

        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        self.assertEqual(doc.mandates_created, 250)
        self.assertEqual(doc.mandates_updated, 0)
        # skipped = no_member (100) + conflict (50) + filtered_old (100) = 250
        self.assertEqual(doc.mandates_skipped, 250)

        # Generous ceiling — local dev typically finishes in well under 60s.
        # The point is to catch O(n^2) regressions, not to micro-benchmark.
        self.assertLess(
            elapsed,
            180,
            f"500-row import took {elapsed:.1f}s (>180s) — likely a regression",
        )
```

- [ ] **Step 7.2: Run — verify it passes**

```bash
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_procurios_mandate_import
```

Expected: all tests in the file pass, including the scale test.

- [ ] **Step 7.3: Commit**

```bash
git add verenigingen/tests/payment/test_procurios_mandate_import.py
git commit -m "test(procurios-mandate-import): 500-row scale smoke test"
```

---

## Task 8: Pre-commit validation pass

**Files:** none

Run the full pre-commit suite over the new files before opening a PR.

- [ ] **Step 8.1: Stage everything and run pre-commit**

```bash
cd ~/frappe-bench/apps/verenigingen
git status
SKIP=whitelist-type-safety,javascript-doctype-validator pre-commit run --files \
    verenigingen/verenigingen_payments/doctype/procurios_mandate_import/__init__.py \
    verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.json \
    verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py \
    verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.js \
    verenigingen/utils/csv/procurios_mandate_validator.py \
    verenigingen/tests/payment/test_procurios_mandate_validator.py \
    verenigingen/tests/payment/test_procurios_mandate_import.py
```

Expected: all hooks pass (the two `SKIP=` hooks are pre-existing failures across the repo, per project memory).

- [ ] **Step 8.2: Fix any issues, then re-run until clean.** Common fixups: black formatting, ruff fixes (`ruff check --fix .`).

- [ ] **Step 8.3: Run the full new-test set one more time**

```bash
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_procurios_mandate_validator
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.payment.test_procurios_mandate_import
```

Expected: green.

- [ ] **Step 8.4: Final commit if any cleanup was needed**

```bash
git add -A
git diff --staged --stat
git commit -m "chore(procurios-mandate-import): pre-commit cleanup"
```

---

## Spec coverage map

| Spec section / requirement | Implemented in |
|---|---|
| New DocType under Verenigingen Payments | Task 1 |
| Naming series `PROC-MND-IMP-...` | Task 1 (JSON) |
| Field set incl. progress counters, skipped_summary | Task 1 (JSON), Task 5 (finalize) |
| `is_submittable: 1` + on_submit enqueue (long, 3600s) | Task 5 |
| `CANCELLED_CUTOFF_MONTHS = 12` constant | Task 2 |
| CSV → SEPA Mandate field mapping table | Task 2 (validator) |
| `scheme=SEPA`, `used_for_memberships=1`, blank `bic` | Task 4 (`_create_mandate`) |
| Status driven by `cancelled_date` (no explicit status) | Task 4 (`_create_mandate`, `_update_cancellation`) |
| Per-row decision tree (5 ordered steps) | Task 4 (`_process_single_row`) |
| Three pre-built caches (member, mandate, active-mandate set) | Task 4 (`_build_caches`) |
| `members_with_active_mandate` cache updated on create | Task 4 (`_create_mandate`) |
| Batched commits via `CSVImportBackgroundProcessor` | Task 5 |
| Bounded `error_log` (first 50 + tail) | Task 5 (`_finalize_import_results`) |
| Per-reason `skipped_summary` | Task 5 (`_finalize_import_results`) |
| Per-row exception → counted under `error`, batch continues | Task 4 (`_process_single_row`) |
| Validate/preview flow + missing-column check | Task 3 |
| Client-side Validate button + auto-refresh | Task 6 |
| Real-DB integration tests for all 10 branches | Tasks 3, 4, 5, 7 |
| Scale smoke test | Task 7 |
| Test location: `verenigingen/tests/payment/` per project convention | Tasks 2, 3 |
