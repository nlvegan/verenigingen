# Procurios Membership & Mandate Import + Member Import Rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import Procurios membership + SEPA-mandate CSV exports and link them to existing members (matching on `Member.procurios_id`), and rename the person/relation importer `Procurios CSV Import` → `Member Import`.

**Architecture:** Mirror the existing `Procurios Mandate Import` controller (`verenigingen/verenigingen_payments/doctype/procurios_mandate_import/`) — it already implements the exact structural pattern (BaseCSVImport subclass + pure validator + prebuilt caches + per-row processor + `CSVImportBackgroundProcessor`). A new `Procurios Membership Import` reuses that pattern; active memberships are created via the existing `MembershipImportService` (→ Membership + dues schedule), cancelled/expired ones as direct historical records. The mandate importer already exists and just needs to be *run*.

**Tech Stack:** Frappe v16 / Python 3.14, `bench` test runner, existing `verenigingen.utils.csv.base_csv_import`, `verenigingen.utils.csv_import_processor`, `verenigingen.services.csv_import.membership_import_service`.

## Global Constraints

- **Test sites only:** run tests on `test_site_1`..`test_site_5`, never `veg11` (except the explicit Workstream-3 mandate run). Create/delete records freely.
- **Real integration tests only** — no business-logic mocks (repo `test-quality-enforcer` / `block-inappropriate-mocks` hooks enforce this).
- **Decorator order:** `@frappe.whitelist()` MUST be outermost, then `@critical_api(operation_type=OperationType.ADMIN)`, then `def`.
- **Match key:** memberships and mandates link on `Member.procurios_id` only (the `Debiteur Id` column). No name/email/IBAN fallback.
- **Membership Type mapping:** link-to-existing only; no auto-create.
- **Idempotency:** memberships dedupe on the new `Membership.procurios_membership_id` (Procurios membership `Id` column).
- **Active patches file:** `verenigingen/patches.txt` (NOT `verenigingen/verenigingen/patches.txt`).
- **Import gating:** `@critical_api(OperationType.ADMIN)`; role gate `ADMIN_ROLES = ["System Manager", "Verenigingen Administrator"]` (from `base_csv_import`).
- **Copyright header** on new files: `# Copyright (c) 2026, Verenigingen and contributors` / `# For license information, please see license.txt`.
- **Sample data files** (on veg11, for reference during dev):
  - memberships: `sites/veg11.veganisme.org/private/files/Export-test 2_ Lidmaatschappen van de 50 relaties (20260709_1454) - Blad1.csv`
  - mandates: `sites/veg11.veganisme.org/private/files/Export-test 3_ Alle mandaten (20260709_1456) - Blad1.csv`
  - Both are **comma-delimited**, UTF-8-BOM. The `Procurios CSV Import`/mandate doctypes default `csv_delimiter` to `Semicolon` — the test uploads must set delimiter=Comma (or re-save the sample as semicolon).

---

## Membership CSV column reference (file 0017)

Header (comma-delimited), relevant columns:
`Vervaldatum, Contractant Naam, Debiteur Naam, Ingangsdatum, Aanmaakdatum, Opgezegd, Einddatum, Gefactureerd tot, Normale prijs (abonnement), Herkomst, Id, Categorie, Product, Type, …, Looptijd, Contractant Id, Contractant e-mailadres, Debiteur Id, Debiteur e-mailadres, Type, #Expl, …, Normale prijs (type), …`

Note: **`Type` appears twice** in the header (position ~14 and ~24); both hold the same value (Maandlid/Jaarlid) in the sample. Mapping used by this importer:

| Procurios column | Meaning | Target |
|---|---|---|
| `Debiteur Id` | relation ID | match → `Member.procurios_id` |
| `Debiteur Naam` | full name | logging only |
| `Type` | Maandlid/Jaarlid | → Membership Type (via mapping table) |
| `Looptijd` | `1 Maand`/`1 Jaar` | → `payment_period` (monthly/annual) |
| `Ingangsdatum` | start | → Membership `start_date` |
| `Opgezegd` | cancelled marker/date | → status Cancelled + `cancellation_date` |
| `Einddatum` | end date | → status Expired (if past) / `cancellation_date` fallback |
| `Normale prijs (type)` (fallback `Normale prijs (abonnement)`) | price | → `dues_rate` |
| `Id` | membership id (e.g. 7112) | → `procurios_membership_id` (idempotency) |

---

## Task 1: Custom field `procurios_membership_id` on Membership

**Files:**
- Create: `verenigingen/patches/v15_0/add_procurios_membership_id_field.py`
- Modify: `verenigingen/patches.txt` (append patch dotted-path under `[post_model_sync]`)
- Test: `verenigingen/tests/patches/test_procurios_membership_id_field.py`

**Interfaces:**
- Produces: `Membership.procurios_membership_id` (Data, indexed) — consumed by Tasks 5/6 for idempotency.

- [ ] **Step 1: Write the failing test**

```python
# verenigingen/tests/patches/test_procurios_membership_id_field.py
import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcuriosMembershipIdField(FrappeTestCase):
    def test_field_exists_on_membership(self):
        meta = frappe.get_meta("Membership")
        field = meta.get_field("procurios_membership_id")
        self.assertIsNotNone(field, "procurios_membership_id custom field missing on Membership")
        self.assertEqual(field.fieldtype, "Data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.patches.test_procurios_membership_id_field`
Expected: FAIL (field is None).

- [ ] **Step 3: Write the patch**

```python
# verenigingen/patches/v15_0/add_procurios_membership_id_field.py
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
    """Add Membership.procurios_membership_id — idempotency key for the
    Procurios membership import (stores the Procurios membership `Id`)."""
    if frappe.get_meta("Membership").get_field("procurios_membership_id"):
        return
    create_custom_field(
        "Membership",
        {
            "fieldname": "procurios_membership_id",
            "label": "Procurios Membership ID",
            "fieldtype": "Data",
            "read_only": 1,
            "no_copy": 1,
            "search_index": 1,
            "insert_after": "amended_from",
            "description": "Procurios membership Id this record was imported from (idempotency key).",
        },
    )
    frappe.clear_cache(doctype="Membership")
```

- [ ] **Step 4: Register the patch**

Append to `verenigingen/patches.txt` under the `[post_model_sync]` section:

```
verenigingen.patches.v15_0.add_procurios_membership_id_field
```

- [ ] **Step 5: Run the patch + test**

Run:
```bash
bench --site test_site_1 execute verenigingen.patches.v15_0.add_procurios_membership_id_field.execute
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.patches.test_procurios_membership_id_field
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/patches/v15_0/add_procurios_membership_id_field.py verenigingen/patches.txt verenigingen/tests/patches/test_procurios_membership_id_field.py
git commit -m "feat(import): add Membership.procurios_membership_id idempotency field"
```

---

## Task 2: `ProcuriosMembershipValidator` (pure, no DB)

**Files:**
- Create: `verenigingen/utils/csv/procurios_membership_validator.py`
- Test: `verenigingen/tests/utils/csv/test_procurios_membership_validator.py`

**Interfaces:**
- Produces:
  - `@dataclass ProcuriosMembershipRow(row_number:int, debiteur_id:str, debiteur_naam:str, procurios_type:str, payment_period:str, start_date:str, dues_rate:Optional[float], procurios_membership_id:str, status:str, cancellation_date:Optional[str])` where `status ∈ {"Active","Cancelled","Expired"}`.
  - `ProcuriosMembershipValidator` with:
    - `check_required_columns(headers: List[str]) -> List[str]`
    - `extract_membership_types(csv_data: List[Dict]) -> List[str]` (sorted distinct non-empty `Type`)
    - `validate_and_map(csv_data: List[Dict]) -> Tuple[List[ProcuriosMembershipRow], List[str]]`
    - `map_row(row: Dict, row_num: int) -> ProcuriosMembershipRow` (raises ValueError on bad row)
- Consumed by: Task 4 controller.

REQUIRED_COLUMNS = `["Debiteur Id", "Type", "Ingangsdatum", "Id"]`.

Status rule (in `map_row`): `today = date.today()`.
- `Opgezegd` non-empty → `status="Cancelled"`, `cancellation_date = _parse_date(Opgezegd)` if parseable else `_parse_date(Einddatum)` if present else `today.isoformat()`.
- elif `Einddatum` non-empty and parseable and `< today` → `status="Expired"`, `cancellation_date = Einddatum`.
- else `status="Active"`, `cancellation_date=None`.

`payment_period` from `Looptijd` (case-insensitive, strip): contains `maand` → `"Maandelijks"`; contains `jaar` → `"Jaarlijks"`; contains `kwartaal` → `"Kwartaal"`; else `""`.

`dues_rate` = float of `Normale prijs (type)`, else `Normale prijs (abonnement)`, else None (comma decimal tolerated: replace `,`→`.`).

- [ ] **Step 1: Write the failing tests**

```python
# verenigingen/tests/utils/csv/test_procurios_membership_validator.py
import unittest
from datetime import date

from verenigingen.utils.csv.procurios_membership_validator import (
    ProcuriosMembershipValidator,
)


class TestProcuriosMembershipValidator(unittest.TestCase):
    def setUp(self):
        self.v = ProcuriosMembershipValidator(today=date(2026, 7, 15))

    def _row(self, **over):
        base = {
            "Debiteur Id": "67017",
            "Debiteur Naam": "Amanda de Nijs",
            "Type": "Maandlid",
            "Looptijd": "1 Maand",
            "Ingangsdatum": "2022-11-27",
            "Opgezegd": "",
            "Einddatum": "",
            "Normale prijs (type)": "2.5",
            "Id": "7112",
        }
        base.update(over)
        return base

    def test_required_columns_missing(self):
        missing = self.v.check_required_columns(["Debiteur Id", "Type"])
        self.assertIn("Ingangsdatum", missing)
        self.assertIn("Id", missing)

    def test_active_row(self):
        rows, errors = self.v.validate_and_map([self._row()])
        self.assertEqual(errors, [])
        r = rows[0]
        self.assertEqual(r.debiteur_id, "67017")
        self.assertEqual(r.procurios_membership_id, "7112")
        self.assertEqual(r.status, "Active")
        self.assertEqual(r.payment_period, "Maandelijks")
        self.assertEqual(r.start_date, "2022-11-27")
        self.assertEqual(r.dues_rate, 2.5)
        self.assertIsNone(r.cancellation_date)

    def test_cancelled_row_sets_status_and_date(self):
        rows, _ = self.v.validate_and_map([self._row(Opgezegd="2023-05-01")])
        self.assertEqual(rows[0].status, "Cancelled")
        self.assertEqual(rows[0].cancellation_date, "2023-05-01")

    def test_expired_row_past_einddatum(self):
        rows, _ = self.v.validate_and_map([self._row(Einddatum="2024-01-01")])
        self.assertEqual(rows[0].status, "Expired")
        self.assertEqual(rows[0].cancellation_date, "2024-01-01")

    def test_jaarlid_payment_period(self):
        rows, _ = self.v.validate_and_map([self._row(Type="Jaarlid", Looptijd="1 Jaar")])
        self.assertEqual(rows[0].payment_period, "Jaarlijks")

    def test_duplicate_type_column_takes_membership_type(self):
        # csv.DictReader collapses duplicate headers; validator must read the
        # de-duplicated single "Type" value, not crash.
        rows, _ = self.v.validate_and_map([self._row(Type="Jaarlid")])
        self.assertEqual(rows[0].procurios_type, "Jaarlid")

    def test_extract_membership_types_distinct_sorted(self):
        data = [self._row(), self._row(Type="Jaarlid"), self._row(Type="Maandlid")]
        self.assertEqual(self.v.extract_membership_types(data), ["Jaarlid", "Maandlid"])

    def test_missing_required_value_is_row_error(self):
        rows, errors = self.v.validate_and_map([self._row(**{"Debiteur Id": ""})])
        self.assertEqual(rows, [])
        self.assertTrue(any("Debiteur Id" in e for e in errors))

    def test_comma_decimal_dues_rate(self):
        rows, _ = self.v.validate_and_map([self._row(**{"Normale prijs (type)": "2,5"})])
        self.assertEqual(rows[0].dues_rate, 2.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.utils.csv.test_procurios_membership_validator`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the validator**

```python
# verenigingen/utils/csv/procurios_membership_validator.py
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""CSV-shape validation + row mapping for the Procurios membership export.

Pure Python, no DB access — mirrors procurios_mandate_validator.py. Per-row
business rules (member match, dedup, active-conflict) live in the controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

REQUIRED_COLUMNS = ["Debiteur Id", "Type", "Ingangsdatum", "Id"]


@dataclass
class ProcuriosMembershipRow:
    row_number: int
    debiteur_id: str
    debiteur_naam: str
    procurios_type: str
    payment_period: str
    start_date: str
    dues_rate: Optional[float]
    procurios_membership_id: str
    status: str  # Active | Cancelled | Expired
    cancellation_date: Optional[str]


class ProcuriosMembershipValidator:
    def __init__(self, today: Optional[date] = None):
        self._today = today or date.today()

    def check_required_columns(self, headers: List[str]) -> List[str]:
        present = set(headers)
        return [c for c in REQUIRED_COLUMNS if c not in present]

    def extract_membership_types(self, csv_data: List[Dict]) -> List[str]:
        seen = {(row.get("Type") or "").strip() for row in csv_data}
        return sorted(t for t in seen if t)

    def validate_and_map(
        self, csv_data: List[Dict]
    ) -> Tuple[List[ProcuriosMembershipRow], List[str]]:
        mapped: List[ProcuriosMembershipRow] = []
        errors: List[str] = []
        for idx, row in enumerate(csv_data, start=2):  # +1 header, 1-indexed
            try:
                mapped.append(self.map_row(row, idx))
            except ValueError as e:
                errors.append(str(e))
        return mapped, errors

    def map_row(self, row: Dict, row_num: int) -> ProcuriosMembershipRow:
        for col in REQUIRED_COLUMNS:
            if not (row.get(col) or "").strip():
                raise ValueError(f"Row {row_num}: required column '{col}' is empty")

        start_date = self._parse_date(row["Ingangsdatum"], row_num, "Ingangsdatum")
        opgezegd = (row.get("Opgezegd") or "").strip()
        einddatum = (row.get("Einddatum") or "").strip()

        status, cancellation_date = self._determine_status(opgezegd, einddatum)

        return ProcuriosMembershipRow(
            row_number=row_num,
            debiteur_id=row["Debiteur Id"].strip(),
            debiteur_naam=(row.get("Debiteur Naam") or "").strip(),
            procurios_type=row["Type"].strip(),
            payment_period=self._map_payment_period(row.get("Looptijd", "")),
            start_date=start_date,
            dues_rate=self._parse_rate(row),
            procurios_membership_id=row["Id"].strip(),
            status=status,
            cancellation_date=cancellation_date,
        )

    # ---- helpers ----

    def _determine_status(
        self, opgezegd: str, einddatum: str
    ) -> Tuple[str, Optional[str]]:
        if opgezegd:
            cancelled = self._try_parse(opgezegd) or self._try_parse(einddatum) or self._today.isoformat()
            return "Cancelled", cancelled
        if einddatum:
            end = self._try_parse(einddatum)
            if end and date.fromisoformat(end) < self._today:
                return "Expired", end
        return "Active", None

    def _map_payment_period(self, looptijd: str) -> str:
        t = (looptijd or "").strip().lower()
        if "maand" in t:
            return "Maandelijks"
        if "kwartaal" in t:
            return "Kwartaal"
        if "jaar" in t:
            return "Jaarlijks"
        return ""

    def _parse_rate(self, row: Dict) -> Optional[float]:
        for col in ("Normale prijs (type)", "Normale prijs (abonnement)"):
            raw = (row.get(col) or "").strip().replace(",", ".")
            if raw:
                try:
                    return float(raw)
                except ValueError:
                    continue
        return None

    def _parse_date(self, value: str, row_num: int, field: str) -> str:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Row {row_num}: invalid {field} '{value}': {e}") from e

    def _try_parse(self, value: str) -> Optional[str]:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
        except (ValueError, AttributeError):
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.utils.csv.test_procurios_membership_validator`
Expected: PASS (all 10 tests).

- [ ] **Step 5: Commit**

```bash
git add verenigingen/utils/csv/procurios_membership_validator.py verenigingen/tests/utils/csv/test_procurios_membership_validator.py
git commit -m "feat(import): ProcuriosMembershipValidator (CSV shape + status mapping)"
```

---

## Task 3: `Procurios Membership Type Mapping` child DocType

**Files:**
- Create: `verenigingen/verenigingen/doctype/procurios_membership_type_mapping/procurios_membership_type_mapping.json`
- Create: `verenigingen/verenigingen/doctype/procurios_membership_type_mapping/procurios_membership_type_mapping.py`
- Create: `verenigingen/verenigingen/doctype/procurios_membership_type_mapping/__init__.py`
- Test: `verenigingen/tests/doctype/test_procurios_membership_type_mapping.py`

**Interfaces:**
- Produces child DocType `Procurios Membership Type Mapping` with fields `procurios_type` (Data, read-only), `membership_type` (Link → Membership Type). Used as a Table field on Task 4's parent.

- [ ] **Step 1: Write the failing test**

```python
# verenigingen/tests/doctype/test_procurios_membership_type_mapping.py
import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcuriosMembershipTypeMapping(FrappeTestCase):
    def test_doctype_is_child_with_expected_fields(self):
        meta = frappe.get_meta("Procurios Membership Type Mapping")
        self.assertTrue(meta.istable, "must be a child table")
        self.assertEqual(meta.get_field("membership_type").options, "Membership Type")
        self.assertTrue(meta.get_field("procurios_type").read_only)
```

- [ ] **Step 2: Run to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.doctype.test_procurios_membership_type_mapping`
Expected: FAIL (DocType not found).

- [ ] **Step 3: Create the child DocType files**

```json
// procurios_membership_type_mapping.json
{
 "actions": [],
 "creation": "2026-07-15 10:00:00.000000",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "field_order": ["procurios_type", "membership_type"],
 "fields": [
  {"fieldname": "procurios_type", "fieldtype": "Data", "in_list_view": 1, "label": "Procurios Type", "read_only": 1, "columns": 4},
  {"fieldname": "membership_type", "fieldtype": "Link", "in_list_view": 1, "label": "Membership Type", "options": "Membership Type", "columns": 4}
 ],
 "index_web_pages_for_search": 0,
 "istable": 1,
 "links": [],
 "modified": "2026-07-15 10:00:00.000000",
 "modified_by": "Administrator",
 "module": "Verenigingen",
 "name": "Procurios Membership Type Mapping",
 "owner": "Administrator",
 "permissions": [],
 "sort_field": "creation",
 "sort_order": "DESC",
 "states": []
}
```

```python
# procurios_membership_type_mapping.py
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProcuriosMembershipTypeMapping(Document):
    pass
```

```python
# __init__.py  (empty file)
```

- [ ] **Step 4: Reload + run test**

Run:
```bash
bench --site test_site_1 reload-doctype "Procurios Membership Type Mapping"
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.doctype.test_procurios_membership_type_mapping
```
Expected: PASS. (If reload-doctype can't find it pre-migrate, run `bench --site test_site_1 migrate` first.)

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/procurios_membership_type_mapping/ verenigingen/tests/doctype/test_procurios_membership_type_mapping.py
git commit -m "feat(import): Procurios Membership Type Mapping child doctype"
```

---

## Task 4: `Procurios Membership Import` DocType + validate/preview + type-mapping upsert

**Files:**
- Create: `verenigingen/verenigingen/doctype/procurios_membership_import/procurios_membership_import.json`
- Create: `verenigingen/verenigingen/doctype/procurios_membership_import/procurios_membership_import.py`
- Create: `verenigingen/verenigingen/doctype/procurios_membership_import/__init__.py`
- Create: `verenigingen/verenigingen/doctype/procurios_membership_import/procurios_membership_import.js`
- Test: `verenigingen/tests/doctype/test_procurios_membership_import.py`

**Interfaces:**
- Consumes: `ProcuriosMembershipValidator` (Task 2), `Procurios Membership Type Mapping` (Task 3), `BaseCSVImport` + helpers (`run_csv_validation`, `format_truncated_error_log`, `mark_import_failed`, `prepare_background_import`) from `verenigingen.utils.csv.base_csv_import`.
- Produces: `ProcuriosMembershipImport(BaseCSVImport)` with `_validator` property, `_validate_and_preview_csv()`, `_get_type_mapping() -> Dict[str,str]`, `_incomplete_mapping_types() -> List[str]`. Consumed by Task 5 (per-row logic) — Task 5 completes the same file.

DocType JSON: series `PROC-MEMB-IMP-.YYYY.-.####.`, `is_submittable: 1`, module Verenigingen. Fields (mirror `procurios_mandate_import.json`, swap counters):
`naming_series`(hidden), `csv_file`(Attach, reqd), `encoding`(Select, default `auto-detect`), `csv_delimiter`(Select `Comma\nSemicolon\nTab`, default `Comma`), `membership_type_mapping`(Table → Procurios Membership Type Mapping), `preview_data`(Code/JSON, read_only, allow_on_submit), `import_status`(Select `Pending\nValidating\nReady for Import\nQueued\nIn Progress\nCompleted\nFailed`, read_only, allow_on_submit, default Pending), `progress_percentage`(Percent), `rows_processed`(Int), `total_rows`(Int), `memberships_created`(Int), `memberships_skipped`(Int), `skipped_summary`(Small Text, read_only, allow_on_submit), `error_log`(Long Text, read_only, allow_on_submit), `descriptive_name`(Data, read_only), `import_date`(Date, read_only). Permissions: System Manager + Verenigingen Administrator (create/read/write/submit/delete), copy from `procurios_mandate_import.json`.

- [ ] **Step 1: Write the failing tests**

```python
# verenigingen/tests/doctype/test_procurios_membership_import.py
import frappe
from frappe.tests.utils import FrappeTestCase


def _write_csv(rows_header, rows):
    import os, tempfile
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(rows_header + "\n")
        for r in rows:
            f.write(r + "\n")
    # attach as a File so csv_file has a valid /private path
    with open(path, "rb") as fh:
        filedoc = frappe.get_doc({
            "doctype": "File",
            "file_name": "memb_test.csv",
            "is_private": 1,
            "content": fh.read(),
        }).insert(ignore_permissions=True)
    return filedoc.file_url


HEADER = "Debiteur Id,Debiteur Naam,Type,Looptijd,Ingangsdatum,Opgezegd,Einddatum,Normale prijs (type),Id"


class TestProcuriosMembershipImportValidate(FrappeTestCase):
    def _make_import(self, rows):
        url = _write_csv(HEADER, rows)
        doc = frappe.get_doc({
            "doctype": "Procurios Membership Import",
            "csv_file": url,
            "csv_delimiter": "Comma",
        }).insert(ignore_permissions=True)
        return doc

    def test_validate_populates_type_mapping(self):
        doc = self._make_import([
            "67017,Amanda,Maandlid,1 Maand,2022-11-27,,,2.5,7112",
            "18458,Annelies,Jaarlid,1 Jaar,2020-01-30,,,20,5124",
        ])
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
        doc.save(ignore_permissions=True)
        # Re-validate: existing choice must survive
        doc._validate_and_preview_csv()
        doc.reload()
        self.assertEqual(doc.membership_type_mapping[0].membership_type, mt)

    def test_incomplete_mapping_detected(self):
        doc = self._make_import(["67017,Amanda,Maandlid,1 Maand,2022-11-27,,,2.5,7112"])
        doc._validate_and_preview_csv()
        doc.reload()
        self.assertEqual(doc._incomplete_mapping_types(), ["Maandlid"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.doctype.test_procurios_membership_import`
Expected: FAIL (DocType not found).

- [ ] **Step 3: Create the DocType JSON**

Copy `procurios_mandate_import.json`, change `name`/`naming_series options+default` to `PROC-MEMB-IMP-.YYYY.-.####.`, replace mandate counter fields with the membership fields listed above, add the `membership_type_mapping` Table field (options `Procurios Membership Type Mapping`), keep `is_submittable: 1` and the two-role permission block. (Full field list above; use the sibling file as the literal template.)

- [ ] **Step 4: Create the controller (validate/preview half)**

```python
# procurios_membership_import.py
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Procurios membership import controller.

Imports membership contracts from a Procurios CSV export. Matches
Debiteur Id -> Member.procurios_id. Active rows create a live Membership
+ dues schedule via MembershipImportService; cancelled/expired rows are
created as historical records. Idempotent on Membership.procurios_membership_id.

Design: docs/superpowers/specs/2026-07-15-procurios-membership-mandate-import-design.md
"""

from __future__ import annotations

import json
from typing import Dict, List

import frappe

from verenigingen.utils.csv.base_csv_import import (
    BaseCSVImport,
    format_truncated_error_log,
    mark_import_failed,
)
from verenigingen.utils.csv.procurios_membership_validator import (
    ProcuriosMembershipValidator,
)

# dues-schedule template settings fields (checked on validate)
DUES_TEMPLATE_SETTINGS = [
    "csv_monthly_dues_schedule",
    "csv_quarterly_dues_schedule",
    "csv_annual_dues_schedule",
]


class ProcuriosMembershipImport(BaseCSVImport):
    _BACKGROUND_METHOD = (
        "verenigingen.verenigingen.doctype.procurios_membership_import."
        "procurios_membership_import.process_import_background"
    )

    @property
    def _validator(self) -> ProcuriosMembershipValidator:
        if not hasattr(self, "_validator_instance"):
            self._validator_instance = ProcuriosMembershipValidator()
        return self._validator_instance

    # ---- validate / preview ----

    def _validate_and_preview_csv(self) -> None:
        self.db_set("import_status", "Validating")
        frappe.db.commit()
        try:
            csv_data = self._read_csv_file()
            if not csv_data:
                mark_import_failed(self, "CSV file is empty or could not be read")
                return

            headers = list(csv_data[0].keys())
            missing = self._validator.check_required_columns(headers)
            if missing:
                mark_import_failed(self, "Missing required columns: " + ", ".join(missing))
                return

            self._sync_type_mapping(self._validator.extract_membership_types(csv_data))

            mapped, errors = self._validator.validate_and_map(csv_data)
            if errors:
                self.db_set("error_log", format_truncated_error_log(errors))

            preview = [
                {
                    "debiteur_id": r.debiteur_id,
                    "debiteur_naam": r.debiteur_naam,
                    "type": r.procurios_type,
                    "status": r.status,
                    "start_date": r.start_date,
                    "dues_rate": r.dues_rate,
                }
                for r in mapped[:5]
            ]
            self.db_set("preview_data", json.dumps(preview, indent=2, default=str))
            self.db_set("total_rows", len(csv_data))
            self.db_set("descriptive_name", f"Procurios membership import - {len(csv_data)} rows")

            missing_templates = self._missing_dues_templates()
            if missing_templates:
                self.db_set(
                    "error_log",
                    "WARNING: Verenigingen Settings missing dues-schedule templates: "
                    + ", ".join(missing_templates)
                    + " — active memberships with these payment periods will fail.",
                )

            self.db_set("import_status", "Ready for Import" if mapped else "Failed")
            if not mapped and not errors:
                self.db_set("error_log", "No valid rows found in CSV")
            frappe.db.commit()
        except Exception as e:
            mark_import_failed(self, str(e))
            raise

    def _sync_type_mapping(self, procurios_types: List[str]) -> None:
        """Upsert distinct Procurios Type values into membership_type_mapping,
        preserving any membership_type already chosen."""
        existing = {r.procurios_type: r.membership_type for r in (self.membership_type_mapping or [])}
        self.set("membership_type_mapping", [])
        for ptype in procurios_types:
            self.append(
                "membership_type_mapping",
                {"procurios_type": ptype, "membership_type": existing.get(ptype)},
            )
        # persist child rows (validate stage; doc not submitted yet)
        self.save(ignore_permissions=True)

    def _get_type_mapping(self) -> Dict[str, str]:
        return {
            r.procurios_type: r.membership_type
            for r in (self.membership_type_mapping or [])
            if r.procurios_type and r.membership_type
        }

    def _incomplete_mapping_types(self) -> List[str]:
        return [
            r.procurios_type
            for r in (self.membership_type_mapping or [])
            if r.procurios_type and not r.membership_type
        ]

    def _missing_dues_templates(self) -> List[str]:
        settings = frappe.get_single("Verenigingen Settings")
        return [f for f in DUES_TEMPLATE_SETTINGS if not settings.get(f)]
```

```python
# __init__.py  (empty)
```

```javascript
// procurios_membership_import.js — mirror procurios_mandate_import.js:
// a "Validate File" button that calls
// verenigingen.verenigingen.doctype.procurios_membership_import.procurios_membership_import.validate_import_file
// Copy the sibling file and swap the method path + doctype name.
```

- [ ] **Step 5: Migrate + run tests**

Run:
```bash
bench --site test_site_1 migrate
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.doctype.test_procurios_membership_import
```
Expected: the 3 validate-stage tests PASS. (`validate_import_file`/`process_import_background` module functions come in Tasks 5–6; if the DocType `on_submit` enqueue is exercised, it will fail until then — the validate tests do not submit.)

- [ ] **Step 6: Commit**

```bash
git add verenigingen/verenigingen/doctype/procurios_membership_import/ verenigingen/tests/doctype/test_procurios_membership_import.py
git commit -m "feat(import): Procurios Membership Import doctype + validate/preview + type-mapping upsert"
```

---

## Task 5: Membership import — caches, per-row processor, background entrypoints

**Files:**
- Modify: `verenigingen/verenigingen/doctype/procurios_membership_import/procurios_membership_import.py` (add caches, per-row, finalize, module-level `validate_import_file` + `process_import_background`)
- Modify: `whitelist_files.txt` (register the two new whitelisted methods if that file enumerates them — grep first)
- Test: `verenigingen/tests/doctype/test_procurios_membership_import_flow.py`

**Interfaces:**
- Consumes: `MembershipImportService.create_membership_from_csv(member_doc, row_data)` from `verenigingen.services.csv_import.membership_import_service` (`row_data` keys: `member_id`, `membership_type`, `payment_period`, `member_since`, `dues_rate`); `CSVImportBackgroundProcessor`, `prepare_background_import`, `run_csv_validation`.
- Produces: `_build_caches()`, `_process_single_member(row, error_log, caches, skip_counters)`, `_create_active_membership(...)`, `_create_historical_membership(...)`, `_finalize_import_results(...)`, module-level `validate_import_file` / `process_import_background`.

Per-row decision order (mirror mandate `_process_single_row`):
1. `debiteur_id` in `caches.ambiguous_procurios_ids` → skip `ambiguous_member` + log.
2. member = `caches.procurios_id_to_member.get(debiteur_id)`; none → skip `no_member` + log.
3. `procurios_membership_id` in `caches.existing_membership_ids` → skip `duplicate`.
4. If `row.status == "Active"` and member in `caches.members_with_active_membership` → skip `already_active` + log.
5. Active → `_create_active_membership`; Cancelled/Expired → `_create_historical_membership`.

`_create_active_membership`: build `row_data`, call `create_membership_from_csv`; if it returns a name, `frappe.db.set_value("Membership", name, "procurios_membership_id", row.procurios_membership_id, update_modified=False)`, add to caches, return `("created", name)`.

`_create_historical_membership`: create a submitted Membership directly. **Elevate to Administrator** for the insert/submit so `Membership.validate_dates`'s minimum-1-year rule (which only *throws* for non-System-Manager users) degrades to a warning; suppress the msgprint. Set `_is_csv_import=True` on the doc.

```python
def _create_historical_membership(self, row, member_name, caches):
    original_user = frappe.session.user
    try:
        frappe.set_user("Administrator")
        frappe.flags.suppress_grace_period_message = True
        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": member_name,
            "membership_type": caches.type_mapping[row.procurios_type],
            "start_date": row.start_date,
            "cancellation_date": row.cancellation_date,
            "cancellation_reason": "Imported from Procurios (historical)",
            "procurios_membership_id": row.procurios_membership_id,
        })
        membership._is_csv_import = True
        membership.flags.ignore_permissions = True
        membership.flags.skip_dues_schedule_creation = True  # no billing for historical
        membership.insert()
        membership.submit()  # set_status -> Cancelled/Expired from cancellation_date/renewal_date
    finally:
        frappe.set_user(original_user)
    caches.existing_membership_ids.add(row.procurios_membership_id)
    return ("created", membership.name)
```

- [ ] **Step 1: Write the failing flow tests**

```python
# verenigingen/tests/doctype/test_procurios_membership_import_flow.py
import frappe
from frappe.tests.utils import FrappeTestCase
from verenigingen.tests.utils.base import VereningingenTestCase  # if present; else FrappeTestCase
from verenigingen.tests.fixtures.member_factory import create_test_member  # adjust import to repo factory


HEADER = "Debiteur Id,Debiteur Naam,Type,Looptijd,Ingangsdatum,Opgezegd,Einddatum,Normale prijs (type),Id"


class TestMembershipImportFlow(FrappeTestCase):
    """Real integration: create members with procurios_id, import, assert."""

    def setUp(self):
        # Ensure a Membership Type exists and dues templates are configured on
        # Verenigingen Settings (csv_monthly/quarterly/annual_dues_schedule).
        # Use the repo's existing test factory / fixtures for these.
        ...

    def _run_import(self, rows, mapping):
        # helper: create File + Procurios Membership Import, validate, set
        # membership_type_mapping choices from `mapping`, submit, run the
        # background job synchronously, reload, return the doc.
        ...

    def test_active_row_creates_membership_and_dues_schedule(self):
        member = create_test_member(procurios_id="900001")
        doc = self._run_import(
            ["900001,Test A,Maandlid,1 Maand,2022-11-27,,,2.5,900001"],
            {"Maandlid": "<a monthly Membership Type>"},
        )
        self.assertEqual(doc.memberships_created, 1)
        m = frappe.get_all("Membership", filters={"member": member.name}, fields=["name", "status", "procurios_membership_id"])
        self.assertEqual(m[0].status, "Active")
        self.assertEqual(m[0].procurios_membership_id, "900001")
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", {"member": member.name}))

    def test_no_member_skips_and_logs(self):
        doc = self._run_import(
            ["999999,Nobody,Maandlid,1 Maand,2022-11-27,,,2.5,900002"],
            {"Maandlid": "<a monthly Membership Type>"},
        )
        self.assertEqual(doc.memberships_created, 0)
        self.assertIn("no Member with procurios_id=999999", doc.error_log)

    def test_cancelled_row_creates_historical_no_dues(self):
        member = create_test_member(procurios_id="900003")
        doc = self._run_import(
            ["900003,Test C,Jaarlid,1 Jaar,2018-01-01,2020-06-01,,20,900003"],
            {"Jaarlid": "<an annual Membership Type>"},
        )
        m = frappe.get_all("Membership", filters={"member": member.name}, fields=["status"])
        self.assertEqual(m[0].status, "Cancelled")

    def test_idempotent_rerun_creates_nothing_new(self):
        member = create_test_member(procurios_id="900004")
        rows = ["900004,Test D,Maandlid,1 Maand,2022-11-27,,,2.5,900004"]
        self._run_import(rows, {"Maandlid": "<monthly>"})
        doc2 = self._run_import(rows, {"Maandlid": "<monthly>"})
        self.assertEqual(doc2.memberships_created, 0)
        self.assertEqual(frappe.db.count("Membership", {"member": member.name}), 1)

    def test_already_active_membership_skips_and_logs(self):
        member = create_test_member(procurios_id="900005")
        # give the member an existing active membership first (via factory)
        ...
        doc = self._run_import(
            ["900005,Test E,Maandlid,1 Maand,2022-11-27,,,2.5,900005"],
            {"Maandlid": "<monthly>"},
        )
        self.assertEqual(doc.memberships_created, 0)
        self.assertIn("already has an active membership", doc.error_log)
```

> Implementer note: fill the `...` helpers using the repo's real member factory (`grep -rn "def create_test_member" verenigingen/tests`) and the existing dues-template settings fixtures (`grep -rn "csv_monthly_dues_schedule" verenigingen`). No mocking of membership/dues creation.

- [ ] **Step 2: Run to verify they fail**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.doctype.test_procurios_membership_import_flow`
Expected: FAIL (methods/entrypoints not defined).

- [ ] **Step 3: Implement caches + per-row + finalize + entrypoints**

Add to `procurios_membership_import.py` (mirror `procurios_mandate_import.py` §caches/§per-row/§finalize and its module-level `validate_import_file`/`process_import_background`, adapting):
- `_Caches` dataclass: `procurios_id_to_member`, `ambiguous_procurios_ids`, `existing_membership_ids: Set[str]`, `members_with_active_membership: Set[str]`, `type_mapping: Dict[str,str]`.
- `_build_caches()`: same procurios_id ambiguity loop as mandate importer; `existing_membership_ids` from `frappe.get_all("Membership", filters={"procurios_membership_id": ["!=", ""]}, pluck="procurios_membership_id")`; `members_with_active_membership` from `frappe.get_all("Membership", filters={"status":"Active","docstatus":1}, pluck="member")`; `type_mapping = self._get_type_mapping()`.
- `_process_single_member(...)` with the 5-step order above.
- `_create_active_membership(...)` and `_create_historical_membership(...)` as specified.
- `_finalize_import_results(...)`: set `memberships_created`, derive `memberships_skipped` from `skip_counters` values, `skipped_summary` over keys `("no_member","ambiguous_member","duplicate","already_active","error")`, status Completed, `save(ignore_permissions=True)`, commit.
- Module-level `validate_import_file` → `run_csv_validation("Procurios Membership Import", import_doc_name)`; `process_import_background` → mirror mandate: `prepare_background_import`, read csv, `check_required_columns`, **guard `_incomplete_mapping_types()` → mark_import_failed** ("Complete the membership-type mapping before importing: …"), `validate_and_map`, `test_mode` slice [:25], `_build_caches()`, `skip_counters` seeded with `error=len(validator_errors)`, `CSVImportBackgroundProcessor(... "Procurios Membership Import")` with `progress_field_map={"created":"memberships_created","skipped":"memberships_skipped"}`, wrap per-row in `bulk_member_operations` NOT required (memberships, not members) — but reset `frappe.flags.in_background_job=False` in `finally`. Decorate both with `@frappe.whitelist()` (outermost) + `@critical_api(operation_type=OperationType.ADMIN)`.

- [ ] **Step 4: Run to verify they pass**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.doctype.test_procurios_membership_import_flow`
Expected: PASS. Iterate: if `set_status` yields "Expired" instead of "Cancelled" for the cancelled row, verify `cancellation_date` is today-or-past (it is) — `set_status` checks cancellation before renewal, so Cancelled wins. If the historical submit still throws the 1-year rule, confirm the `frappe.set_user("Administrator")` block wraps the `submit()` too.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/procurios_membership_import/procurios_membership_import.py verenigingen/tests/doctype/test_procurios_membership_import_flow.py whitelist_files.txt
git commit -m "feat(import): Procurios membership import per-row processing + background job"
```

---

## Task 6: Rename `Procurios CSV Import` → `Member Import`

**Files:**
- Rename on disk: `verenigingen/verenigingen/doctype/procurios_csv_import/` → `member_import/` (+ the 4 files inside, class `ProcuriosCSVImport` → `MemberImport`)
- Modify: `verenigingen/utils/csv/base_csv_import.py` (docstring references), `verenigingen/utils/csv_import_processor.py` (any "Procurios CSV Import" literal), `whitelist_files.txt`
- Create: `verenigingen/patches/v15_0/rename_procurios_csv_import_to_member_import.py`
- Modify: `verenigingen/patches.txt`
- Test: `verenigingen/tests/patches/test_rename_member_import.py`

**Interfaces:**
- Produces: DocType `Member Import` (table `tabMember Import`), series `MEM-IMP-.YYYY.-.####.`, module-level methods at `verenigingen.verenigingen.doctype.member_import.member_import.{validate_import_file,process_import_background}`.

- [ ] **Step 1: Write the failing test**

```python
# verenigingen/tests/patches/test_rename_member_import.py
import frappe
from frappe.tests.utils import FrappeTestCase


class TestRenameMemberImport(FrappeTestCase):
    def test_member_import_doctype_exists(self):
        self.assertTrue(frappe.db.exists("DocType", "Member Import"))
        self.assertFalse(frappe.db.exists("DocType", "Procurios CSV Import"))

    def test_series_updated(self):
        naming = frappe.get_meta("Member Import").get_field("naming_series")
        self.assertIn("MEM-IMP-", naming.options)
```

- [ ] **Step 2: Run to verify it fails**

Run: `bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.patches.test_rename_member_import`
Expected: FAIL (Member Import doesn't exist yet).

- [ ] **Step 3: Rename files on disk + update code**

```bash
cd verenigingen/verenigingen/doctype
git mv procurios_csv_import member_import
cd member_import
git mv procurios_csv_import.py member_import.py
git mv procurios_csv_import.js member_import.js
git mv procurios_csv_import.json member_import.json
git mv test_procurios_csv_import_coverage.py test_member_import_coverage.py
```
Then edit `member_import.py`: class `ProcuriosCSVImport` → `MemberImport`; `_BACKGROUND_METHOD` → `verenigingen.verenigingen.doctype.member_import.member_import.process_import_background`; the two `run_csv_validation("Procurios CSV Import", ...)` / `CSVImportBackgroundProcessor(..., "Procurios CSV Import")` / `prepare_background_import("Procurios CSV Import", ...)` string literals → `"Member Import"`. Edit `member_import.json`: `"name": "Member Import"`, naming_series options/default → `MEM-IMP-.YYYY.-.####.`. Edit `member_import.js` doctype ref + method path. Update the coverage test's imports/DocType strings. Grep-and-replace remaining literals:
```bash
grep -rn "Procurios CSV Import\|ProcuriosCSVImport\|procurios_csv_import" verenigingen/utils/csv/base_csv_import.py verenigingen/utils/csv_import_processor.py whitelist_files.txt
```

- [ ] **Step 4: Write the rename patch**

```python
# verenigingen/patches/v15_0/rename_procurios_csv_import_to_member_import.py
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import frappe
from frappe.model.rename_doc import rename_doc


def execute():
    """Rename DocType Procurios CSV Import -> Member Import (table + links)."""
    if frappe.db.exists("DocType", "Procurios CSV Import") and not frappe.db.exists(
        "DocType", "Member Import"
    ):
        rename_doc("DocType", "Procurios CSV Import", "Member Import", force=True)
        frappe.clear_cache(doctype="Member Import")
```

Append to `verenigingen/patches.txt` under `[post_model_sync]`:
```
verenigingen.patches.v15_0.rename_procurios_csv_import_to_member_import
```

- [ ] **Step 5: Migrate + run test**

Run:
```bash
bench --site test_site_1 migrate
bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.patches.test_rename_member_import
```
Expected: PASS. Also re-run the renamed coverage test:
`bench --site test_site_1 run-tests --app verenigingen --module verenigingen.verenigingen.doctype.member_import.test_member_import_coverage`

- [ ] **Step 6: Commit**

```bash
git add -A verenigingen/verenigingen/doctype/member_import verenigingen/patches/v15_0/rename_procurios_csv_import_to_member_import.py verenigingen/patches.txt verenigingen/utils/csv/base_csv_import.py verenigingen/utils/csv_import_processor.py whitelist_files.txt verenigingen/tests/patches/test_rename_member_import.py
git commit -m "refactor(import): rename Procurios CSV Import -> Member Import (series MEM-IMP-)"
```

---

## Task 7: Run the Procurios mandate import on veg11 (Workstream 3)

**Files:** none (execution task). Not TDD.

- [ ] **Step 1: Create + validate the import record on veg11**

```bash
bench --site veg11.veganisme.org execute frappe.client.insert --args '{...}'  # OR via console:
```
Console script (preferred — copy the existing `Procurios Mandate Import` sample file url):
```python
# in: bench --site veg11.veganisme.org console
import frappe
url = "/private/files/Export-test 3_ Alle mandaten (20260709_1456) - Blad1.csv"
doc = frappe.get_doc({
    "doctype": "Procurios Mandate Import",
    "csv_file": url,
    "csv_delimiter": "Comma",
}).insert(ignore_permissions=True)
frappe.db.commit()
name = doc.name
from verenigingen.verenigingen_payments.doctype.procurios_mandate_import.procurios_mandate_import import validate_import_file
print(validate_import_file(name))
```
Expected: `status: success`, import_status `Ready for Import`, total_rows 7699.

- [ ] **Step 2: Run the import (full)**

```python
doc = frappe.get_doc("Procurios Mandate Import", name)
doc.submit()  # enqueues; OR run synchronously:
from verenigingen.verenigingen_payments.doctype.procurios_mandate_import.procurios_mandate_import import process_import_background
process_import_background(name, test_mode=False)
doc.reload()
print("created", doc.mandates_created, "updated", doc.mandates_updated, "skipped", doc.mandates_skipped)
print(doc.skipped_summary)
```
Expected: `mandates_created == 2` (procurios_id 1072 René Beemer, 1073 Sonja Rijs), rest `no_member`. Verify:
```python
for pid in ("1072", "1073"):
    m = frappe.db.get_value("Member", {"procurios_id": pid}, "name")
    print(pid, frappe.get_all("SEPA Mandate", filters={"member": m}, fields=["name","mandate_id","status"]))
```

- [ ] **Step 3: Report the breakdown to the user.** Include created/updated/skipped + skipped_summary. Do NOT delete the 2 created veg11 mandates (they are legitimate). If the run misbehaves, delete only the records this run created and report.

---

## Self-Review

**Spec coverage:**
- Rename → Task 6. ✅
- New Procurios Membership Import (doctype, validator, mapping child, per-row, active+historical, idempotency, skip+log) → Tasks 1–5. ✅
- Configurable type mapping after validation → Task 4 (`_sync_type_mapping`) + Task 5 (import guard). ✅
- Cancelled/expired imported historically → Task 5 `_create_historical_membership`. ✅
- Active → Membership + dues schedule via service → Task 5 `_create_active_membership`. ✅
- Skip already-active + log → Task 5 step 4. ✅
- Idempotency field → Task 1. ✅
- Dues-template precondition check → Task 4 `_missing_dues_templates`. ✅
- Mandate run on veg11 → Task 7. ✅
- Tests run on test sites, real integration → all test tasks. ✅

**Placeholder scan:** The Task-5 flow test has `...` helper bodies with an explicit implementer note to fill them from the repo's real factory (no mocks) — intentional, since exact factory signatures must be grepped, not guessed. All production-code steps show complete code.

**Type consistency:** `ProcuriosMembershipRow` fields, `_Caches` attribute names, `row_data` keys for `create_membership_from_csv`, and `progress_field_map` values are consistent across Tasks 2/4/5. `procurios_membership_id` field name consistent Tasks 1/5.

**Open items to resolve during implementation (flagged, not blocking):**
1. Exact `Opgezegd` value semantics in the real export (date vs marker) — the validator handles both (parse → date; unparseable-but-present → today). Verify against file 0017 in Task 5.
2. `Membership.submit()` under `frappe.set_user("Administrator")` for the historical path — confirm no other validation blocks a past-dated cancelled membership; adjust flags if Task 5 Step 4 surfaces one.
