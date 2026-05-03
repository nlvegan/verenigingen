# Organization Document `applies_on` field + MijnRood reclassify — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate "applies-to date" field (Date + Day/Month/Year precision) to `Organization Document`, plus an admin action to reclassify existing MijnRood-imported docs against the current folder mapping (refilling org / document_type / applies_on by parsing filename + folder path). Stop the import-side overload of `upload_date`.

**Architecture:** Schema-first (3 new fields), then a one-shot data-cleanup patch + bench-execute backfill, then an import-side change so future imports are correct, finally a whitelisted reclassify service called from a single-doc form button and a list-view bulk action. Date extraction is done by a new `extract_date_with_precision()` helper that returns precision alongside the date.

**Tech Stack:** Frappe Framework v15, Python 3.12, vanilla JS (Frappe form/listview API), MariaDB, Frappe `db.set_value` for system writes.

**Source spec:** `docs/superpowers/specs/2026-05-03-organization-document-applies-on-and-reclassify-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `verenigingen/verenigingen/doctype/organization_document/organization_document.json` | Modify | Add 3 fields (`applies_on`, `applies_on_precision`, `source_folder_id`) + section + column break |
| `verenigingen/verenigingen/doctype/organization_document/organization_document.py` | Modify | Add `_normalize_applies_on_precision()` to `validate()` |
| `verenigingen/verenigingen/doctype/organization_document/organization_document.js` | Modify | JS snap-to-1 handlers + form button (calls reclassify backend) |
| `verenigingen/verenigingen/doctype/organization_document/organization_document_list.js` | Create | List-view bulk action |
| `verenigingen/utils/date_extraction.py` | Modify | Add `extract_date_with_precision(text) -> (date \| None, str)` |
| `verenigingen/tests/backend/unit/utils/test_date_extraction.py` | Modify | Tests for new helper |
| `verenigingen/patches/v2_2/clean_overloaded_upload_date.py` | Create | One-shot patch: copy stale `upload_date` → `applies_on`, reset `upload_date` to `creation` date |
| `verenigingen/patches.txt` | Modify | Register new patch |
| `verenigingen/mijnrood_sync/services/document_import_service.py` | Modify | `_import_single_document`: write `applies_on` + `source_folder_id`, drop `upload_date` overload; share folder-path resolver |
| `verenigingen/mijnrood_sync/services/document_reclassify_service.py` | Create | Whitelisted `reclassify_documents(names, dry_run)`; per-doc resolve → diff → write |
| `verenigingen/mijnrood_sync/services/source_folder_backfill.py` | Create | Bench-execute `backfill_source_folder_ids(dry_run, batch_size)` |
| `verenigingen/tests/integration/test_organization_document_applies_on.py` | Create | Schema + server-side precision normalization tests |
| `verenigingen/tests/integration/test_document_reclassify_service.py` | Create | Reclassify service tests (incl. permission test as non-Admin) |
| `verenigingen/tests/integration/test_source_folder_backfill.py` | Create | Backfill command tests |

---

## Conventions for this plan

- **Site:** all bench commands target `veg11.veganisme.org`.
- **Decorator order:** `@frappe.whitelist()` MUST be the outermost decorator (per CLAUDE.md MEMORY). Permission checks via `frappe.only_for(...)` go *inside* the function body, not as another decorator.
- **Pre-commit skips:** for any commit touching whitelisted functions or chapter.py-adjacent code, prefix the commit with `SKIP=whitelist-type-safety,javascript-doctype-validator,jest-testing` (per MEMORY.md known-broken pre-commit hooks). Other commits run pre-commit normally.
- **Tests:** use `VereningingenTestCase` (from `verenigingen.tests.utils.base`) and `CoreTestDataFactory` (from `verenigingen.tests.fixtures.test_data_factory`). Permission-sensitive flows must run via `self.as_user(non_admin_email)` — never assume Administrator.
- **Run a single test module:** `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.integration.<module_name>`
- **Reload doctype after JSON edits:** `cd ~/frappe-bench && bench --site veg11.veganisme.org reload-doctype "Organization Document" && bench --site veg11.veganisme.org clear-cache`

---

## Task 1 — Add fields to `Organization Document`

**Goal:** add `applies_on` (Date), `applies_on_precision` (Select Day/Month/Year, default Day), `source_folder_id` (Int, hidden, read-only, search_index), bracketed by a new section break and column break. `applies_on` is in_list_view + in_standard_filter.

**Files:**
- Modify: `verenigingen/verenigingen/doctype/organization_document/organization_document.json`

- [ ] **Step 1: Edit JSON — add the new fields to `field_order` after `file_hash`**

In `field_order` (currently ends with `"file_hash"`), append:

```json
    "file_hash",
    "applies_section",
    "applies_on",
    "applies_on_precision",
    "column_break_applies",
    "source_folder_id"
  ],
```

- [ ] **Step 2: Edit JSON — add the field definitions to `fields` (after the existing `file_hash` field)**

```json
    {
      "description": "SHA256 hash of file content for duplicate detection",
      "fieldname": "file_hash",
      "fieldtype": "Data",
      "hidden": 1,
      "label": "File Hash",
      "read_only": 1,
      "search_index": 1
    },
    {
      "fieldname": "applies_section",
      "fieldtype": "Section Break",
      "label": "Document Date"
    },
    {
      "description": "The date this document applies to (e.g. minutes from May 2024). May be year-only or year+month.",
      "fieldname": "applies_on",
      "fieldtype": "Date",
      "in_list_view": 1,
      "in_standard_filter": 1,
      "label": "Applies On"
    },
    {
      "default": "Day",
      "description": "Granularity of Applies On. Day uses the full date; Month ignores day; Year ignores month and day.",
      "fieldname": "applies_on_precision",
      "fieldtype": "Select",
      "label": "Precision",
      "options": "Day\nMonth\nYear"
    },
    {
      "fieldname": "column_break_applies",
      "fieldtype": "Column Break"
    },
    {
      "description": "MijnRood folder id (set by importer or backfill). Used by Reclassify action.",
      "fieldname": "source_folder_id",
      "fieldtype": "Int",
      "hidden": 1,
      "label": "MijnRood Folder ID",
      "read_only": 1,
      "search_index": 1
    }
  ],
```

- [ ] **Step 3: Reload doctype + migrate**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org reload-doctype "Organization Document" && bench --site veg11.veganisme.org migrate
```

Expected: migration runs without errors; new columns added.

- [ ] **Step 4: Smoke test — verify schema via console**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute frappe.client.get_meta --kwargs '{"doctype":"Organization Document"}' 2>&1 | grep -E '"applies_on"|"applies_on_precision"|"source_folder_id"'
```

Expected: each fieldname appears.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/organization_document/organization_document.json
git commit -m "feat(organization-document): add applies_on, precision, source_folder_id fields"
```

---

## Task 2 — Server-side precision normalization

**Goal:** on `validate()`, when precision is `Month`, snap `applies_on.day` to 1; when `Year`, snap `applies_on` to `(year, 1, 1)`. Mirrors the JS handlers (Task 8) so REST/API callers can't bypass.

**Files:**
- Create: `verenigingen/tests/integration/test_organization_document_applies_on.py`
- Modify: `verenigingen/verenigingen/doctype/organization_document/organization_document.py`

- [ ] **Step 1: Write the failing test file**

```python
# verenigingen/tests/integration/test_organization_document_applies_on.py
"""Tests for Organization Document applies_on / precision normalization."""

from datetime import date

import frappe

from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory
from verenigingen.tests.utils.base import VereningingenTestCase


class TestOrganizationDocumentAppliesOn(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = CoreTestDataFactory(cleanup_on_exit=False)
        cls.chapter = cls.factory.create_test_chapter()

    @classmethod
    def tearDownClass(cls):
        cls.factory.cleanup()
        super().tearDownClass()

    def _make_doc(self, **overrides):
        """Create a minimal Organization Document for a Chapter as Administrator."""
        defaults = dict(
            doctype="Organization Document",
            organization_type="Chapter",
            chapter=self.chapter.name,
            document_name="Test doc",
            document_type="Other",
            document_file="/private/files/dummy.pdf",
        )
        defaults.update(overrides)
        doc = frappe.get_doc(defaults)
        doc.flags.ignore_permissions = True  # System Manager equivalent for setup
        doc.insert()
        self.addCleanup(lambda: frappe.delete_doc(
            "Organization Document", doc.name, ignore_permissions=True, force=True))
        return doc

    def test_precision_month_snaps_day_to_one(self):
        doc = self._make_doc(applies_on=date(2024, 5, 17), applies_on_precision="Month")
        self.assertEqual(doc.applies_on, date(2024, 5, 1))
        self.assertEqual(doc.applies_on_precision, "Month")

    def test_precision_year_snaps_month_and_day_to_one(self):
        doc = self._make_doc(applies_on=date(2024, 5, 17), applies_on_precision="Year")
        self.assertEqual(doc.applies_on, date(2024, 1, 1))
        self.assertEqual(doc.applies_on_precision, "Year")

    def test_precision_day_leaves_date_alone(self):
        doc = self._make_doc(applies_on=date(2024, 5, 17), applies_on_precision="Day")
        self.assertEqual(doc.applies_on, date(2024, 5, 17))
        self.assertEqual(doc.applies_on_precision, "Day")

    def test_no_applies_on_no_op(self):
        doc = self._make_doc(applies_on=None, applies_on_precision="Month")
        self.assertIsNone(doc.applies_on)

    def test_default_precision_is_day(self):
        doc = self._make_doc()
        self.assertEqual(doc.applies_on_precision, "Day")
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.integration.test_organization_document_applies_on
```

Expected: tests `test_precision_month_snaps_day_to_one` and `test_precision_year_snaps_month_and_day_to_one` FAIL (date isn't snapped). Other tests may pass if defaults already work.

- [ ] **Step 3: Add normalization to the controller**

In `verenigingen/verenigingen/doctype/organization_document/organization_document.py`, add a method and wire it into `validate()`:

In `validate()`, add the call near the top (before `_populate_metadata_fields`):

```python
    def validate(self):
        """Validate document before save"""
        self._validate_organization_reference()
        self._validate_file_extension()
        self._normalize_applies_on_precision()
        self._populate_metadata_fields()
        self._validate_upload_permission()
```

Then add the new method (placement: after `_validate_file_extension`, before `_populate_metadata_fields`):

```python
    def _normalize_applies_on_precision(self):
        """Snap applies_on to match applies_on_precision.

        Month → day = 1; Year → month = 1, day = 1. Day → no change.
        Mirrors the JS form handlers so REST/API callers can't bypass.
        Skipped when applies_on is unset.
        """
        if not self.applies_on:
            return

        # frappe.utils.getdate handles str/date input
        from frappe.utils import getdate

        d = getdate(self.applies_on)
        precision = self.applies_on_precision or "Day"

        if precision == "Month" and d.day != 1:
            self.applies_on = d.replace(day=1)
        elif precision == "Year" and (d.month != 1 or d.day != 1):
            self.applies_on = d.replace(month=1, day=1)
```

- [ ] **Step 4: Run test — verify pass**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.integration.test_organization_document_applies_on
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/organization_document/organization_document.py \
        verenigingen/tests/integration/test_organization_document_applies_on.py
git commit -m "feat(organization-document): server-side normalize applies_on per precision"
```

---

## Task 3 — `extract_date_with_precision()` helper

**Goal:** add a new function that returns `(date | None, "Day" | "Month" | "Year")`. Existing `extract_date_from_text()` and `extract_year_from_text()` keep their signatures untouched. Recognises the existing patterns at Day precision, plus `YYYY-MM` / `MM-YYYY` / `<dutch_month> YYYY` at Month precision, and bare `20\d{2}` at Year precision.

**Files:**
- Modify: `verenigingen/utils/date_extraction.py`
- Modify: `verenigingen/tests/backend/unit/utils/test_date_extraction.py`

- [ ] **Step 1: Write failing tests for the new helper**

Append to `verenigingen/tests/backend/unit/utils/test_date_extraction.py`:

```python
from verenigingen.utils.date_extraction import extract_date_with_precision


class TestExtractDateWithPrecision(unittest.TestCase):
    """Tests for extract_date_with_precision(): returns (date|None, precision_label)."""

    # Day precision (full dates)
    def test_full_date_iso_returns_day(self):
        self.assertEqual(
            extract_date_with_precision("Notulen 2024-05-17.pdf"),
            (date(2024, 5, 17), "Day"),
        )

    def test_full_date_european_returns_day(self):
        self.assertEqual(
            extract_date_with_precision("17-05-2024 - notulen.pdf"),
            (date(2024, 5, 17), "Day"),
        )

    def test_full_date_dutch_month_returns_day(self):
        self.assertEqual(
            extract_date_with_precision("31 mei 2024 Notulen congres.pdf"),
            (date(2024, 5, 31), "Day"),
        )

    # Month precision
    def test_year_month_iso_returns_month(self):
        # day stored as 1
        self.assertEqual(
            extract_date_with_precision("notulen-2024-05.pdf"),
            (date(2024, 5, 1), "Month"),
        )

    def test_month_year_european_returns_month(self):
        self.assertEqual(
            extract_date_with_precision("notulen 05-2024.pdf"),
            (date(2024, 5, 1), "Month"),
        )

    def test_dutch_month_year_returns_month(self):
        self.assertEqual(
            extract_date_with_precision("notulen mei 2024.pdf"),
            (date(2024, 5, 1), "Month"),
        )

    def test_dutch_month_year_capitalized_returns_month(self):
        self.assertEqual(
            extract_date_with_precision("Notulen Mei 2024.pdf"),
            (date(2024, 5, 1), "Month"),
        )

    # Year precision
    def test_bare_year_returns_year(self):
        self.assertEqual(
            extract_date_with_precision("Jaarverslag 2024.pdf"),
            (date(2024, 1, 1), "Year"),
        )

    def test_bare_year_in_folder_path_returns_year(self):
        self.assertEqual(
            extract_date_with_precision("Financien / 2024"),
            (date(2024, 1, 1), "Year"),
        )

    # No match
    def test_no_date_returns_none_and_day(self):
        self.assertEqual(extract_date_with_precision("notulen.pdf"), (None, "Day"))

    def test_empty_string_returns_none_and_day(self):
        self.assertEqual(extract_date_with_precision(""), (None, "Day"))

    def test_none_input_returns_none_and_day(self):
        self.assertEqual(extract_date_with_precision(None), (None, "Day"))

    # Priority: full date wins over bare year
    def test_full_date_wins_over_bare_year(self):
        self.assertEqual(
            extract_date_with_precision("2024-05-17 jaarverslag 2023.pdf"),
            (date(2024, 5, 17), "Day"),
        )

    # Priority: month-year wins over bare year
    def test_year_month_wins_over_bare_year(self):
        # If both could match, year-month should win because it is more specific.
        self.assertEqual(
            extract_date_with_precision("2024-05 jaarverslag 2023.pdf"),
            (date(2024, 5, 1), "Month"),
        )
```

- [ ] **Step 2: Run tests — verify failure**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.backend.unit.utils.test_date_extraction
```

Expected: all `TestExtractDateWithPrecision` tests FAIL with `ImportError: cannot import name 'extract_date_with_precision'`.

- [ ] **Step 3: Implement `extract_date_with_precision`**

In `verenigingen/utils/date_extraction.py`, add (after `extract_date_from_text`, before `extract_year_from_text`):

```python
def extract_date_with_precision(text: str | None) -> tuple[date | None, str]:
    """Extract a date and its precision label from text.

    Precision label is one of "Day", "Month", "Year". Day-precision
    returns the actual day; Month uses day=1; Year uses month=1, day=1.

    Returns (None, "Day") when no date pattern matches. The "Day" default
    in the no-match case is irrelevant since callers check the date for
    None first.

    Pattern priority (first match wins):
      1. Full date (delegates to extract_date_from_text) → "Day"
      2. Year-month patterns (YYYY-MM, MM-YYYY, "<dutch_month> YYYY") → "Month"
      3. Bare year (20\\d{2}) → "Year"
    """
    if not text or not isinstance(text, str):
        return (None, "Day")

    # 1. Full date wins
    d = extract_date_from_text(text)
    if d:
        return (d, "Day")

    # 2. Year-month patterns
    text_stripped = text.strip()

    # 2a. YYYY-MM (also YYYY/MM, YYYY.MM, YYYY MM)
    m = re.search(r"(?<!\d)(20\d{2})[-/.\s](0[1-9]|1[0-2])(?!\d)", text_stripped)
    if m:
        result = _safe_date(int(m.group(1)), int(m.group(2)), 1)
        if result:
            return (result, "Month")

    # 2b. MM-YYYY (also MM/YYYY, MM.YYYY)
    m = re.search(r"(?<!\d)(0[1-9]|1[0-2])[-/.](20\d{2})(?!\d)", text_stripped)
    if m:
        result = _safe_date(int(m.group(2)), int(m.group(1)), 1)
        if result:
            return (result, "Month")

    # 2c. <dutch_month> YYYY
    m = re.search(
        rf"(?<![a-z])({_MONTH_PATTERN})\s+(20\d{{2}})(?!\d)",
        text_stripped,
        re.IGNORECASE,
    )
    if m:
        month_num = DUTCH_MONTHS.get(m.group(1).lower())
        if month_num:
            result = _safe_date(int(m.group(2)), month_num, 1)
            if result:
                return (result, "Month")

    # 3. Bare year
    m = re.search(r"\b(20\d{2})\b", text_stripped)
    if m:
        result = _safe_date(int(m.group(1)), 1, 1)
        if result:
            return (result, "Year")

    return (None, "Day")
```

Note: `_safe_date`, `DUTCH_MONTHS`, `_MONTH_PATTERN`, and `re` are already imported/defined at module top. No new imports needed.

- [ ] **Step 4: Run tests — verify pass**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.backend.unit.utils.test_date_extraction
```

Expected: all tests (existing + new) PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/utils/date_extraction.py \
        verenigingen/tests/backend/unit/utils/test_date_extraction.py
git commit -m "feat(date-extraction): add extract_date_with_precision helper"
```

---

## Task 4 — Cleanup patch for legacy `upload_date`

**Goal:** for existing rows where the old import wrote the document's content date into `upload_date`, copy it to `applies_on` (only if `applies_on` is empty), set `applies_on_precision = "Day"`, and reset `upload_date` to `DATE(creation)`. Idempotent: only touches rows where `DATE(upload_date) != DATE(creation)` AND `applies_on IS NULL`.

**Files:**
- Create: `verenigingen/patches/v2_2/clean_overloaded_upload_date.py`
- Modify: `verenigingen/patches.txt`

- [ ] **Step 1: Create the patch file**

```python
# verenigingen/patches/v2_2/clean_overloaded_upload_date.py
"""Clean legacy `upload_date` values overloaded by old MijnRood imports.

The pre-applies_on import path wrote document content dates into
`upload_date`. After this feature, `upload_date` reverts to "when this
record was created" and a separate `applies_on` field carries the
content date.

For rows where the discrepancy is still visible
(DATE(upload_date) != DATE(creation) AND applies_on IS NULL), copy the
old upload_date value into applies_on, set precision to Day, and reset
upload_date to DATE(creation). Idempotent.
"""

import frappe


def execute():
    affected = frappe.db.sql(
        """
        SELECT name, upload_date, DATE(creation) AS creation_date
        FROM `tabOrganization Document`
        WHERE applies_on IS NULL
          AND upload_date IS NOT NULL
          AND DATE(upload_date) != DATE(creation)
        """,
        as_dict=True,
    )

    if not affected:
        return

    for row in affected:
        frappe.db.set_value(
            "Organization Document",
            row["name"],
            {
                "applies_on": row["upload_date"],
                "applies_on_precision": "Day",
                "upload_date": row["creation_date"],
            },
            update_modified=False,
        )

    frappe.db.commit()
    print(f"clean_overloaded_upload_date: healed {len(affected)} Organization Document rows")
```

- [ ] **Step 2: Register the patch in `patches.txt`**

Append to `verenigingen/patches.txt` (after the last `v2_2` entry):

```
verenigingen.patches.v2_2.clean_overloaded_upload_date
```

- [ ] **Step 3: Run the patch via migrate**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate
```

Expected: migration succeeds; if any rows were affected, see the `clean_overloaded_upload_date: healed N ...` line in output.

- [ ] **Step 4: Idempotency check — re-run migrate**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate
```

Expected: patch skipped (already executed marker in `tabPatch Log`).

- [ ] **Step 5: Manual sanity check — query a healed row**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute frappe.db.sql --kwargs '{"query":"SELECT name, upload_date, applies_on, applies_on_precision, DATE(creation) FROM `tabOrganization Document` WHERE applies_on IS NOT NULL LIMIT 5", "as_dict": true}'
```

Expected: `DATE(upload_date) == DATE(creation)`, `applies_on` populated, `applies_on_precision = "Day"`.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/patches/v2_2/clean_overloaded_upload_date.py \
        verenigingen/patches.txt
git commit -m "fix(organization-document): heal legacy upload_date overload via applies_on"
```

---

## Task 5 — `source_folder_id` backfill command

**Goal:** populate `source_folder_id` on existing Organization Documents by matching `file_hash` against MijnRood's document table. Bench-execute only (no HTTP surface). Idempotent.

**Files:**
- Create: `verenigingen/mijnrood_sync/services/source_folder_backfill.py`
- Create: `verenigingen/tests/integration/test_source_folder_backfill.py`

- [ ] **Step 1: Write the failing test**

```python
# verenigingen/tests/integration/test_source_folder_backfill.py
"""Integration tests for source_folder_backfill command.

The backfill connects to the MijnRood DB to fetch {file_hash: folder_id};
in this test we monkey-patch that fetch to a fake mapping so the test
runs without a live MijnRood DB.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSourceFolderBackfill(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = CoreTestDataFactory(cleanup_on_exit=False)
        cls.chapter = cls.factory.create_test_chapter()

    @classmethod
    def tearDownClass(cls):
        cls.factory.cleanup()
        super().tearDownClass()

    def _make_doc(self, file_hash, source_folder_id=None):
        doc = frappe.get_doc(
            {
                "doctype": "Organization Document",
                "organization_type": "Chapter",
                "chapter": self.chapter.name,
                "document_name": f"hash-{file_hash[:6]}",
                "document_type": "Other",
                "document_file": "/private/files/dummy.pdf",
                "file_hash": file_hash,
                "source_folder_id": source_folder_id,
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        self.addCleanup(lambda n=doc.name: frappe.delete_doc(
            "Organization Document", n, ignore_permissions=True, force=True))
        return doc

    def test_backfill_matches_by_hash(self):
        from verenigingen.mijnrood_sync.services import source_folder_backfill

        doc = self._make_doc(file_hash="a" * 64)

        with patch.object(
            source_folder_backfill,
            "_fetch_mijnrood_hash_to_folder",
            return_value={"a" * 64: 42},
        ):
            result = source_folder_backfill.backfill_source_folder_ids()

        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["no_hash_match"], 0)
        doc.reload()
        self.assertEqual(doc.source_folder_id, 42)

    def test_backfill_skips_already_set(self):
        from verenigingen.mijnrood_sync.services import source_folder_backfill

        self._make_doc(file_hash="b" * 64, source_folder_id=99)

        with patch.object(
            source_folder_backfill,
            "_fetch_mijnrood_hash_to_folder",
            return_value={"b" * 64: 42},
        ):
            result = source_folder_backfill.backfill_source_folder_ids()

        # Already-set rows aren't re-considered or counted as matched
        self.assertEqual(result["matched"], 0)
        self.assertGreaterEqual(result["already_set"], 1)

    def test_backfill_records_no_hash_match(self):
        from verenigingen.mijnrood_sync.services import source_folder_backfill

        doc = self._make_doc(file_hash="c" * 64)

        with patch.object(
            source_folder_backfill,
            "_fetch_mijnrood_hash_to_folder",
            return_value={},
        ):
            result = source_folder_backfill.backfill_source_folder_ids()

        self.assertEqual(result["matched"], 0)
        self.assertGreaterEqual(result["no_hash_match"], 1)
        doc.reload()
        self.assertIsNone(doc.source_folder_id)

    def test_backfill_dry_run_does_not_write(self):
        from verenigingen.mijnrood_sync.services import source_folder_backfill

        doc = self._make_doc(file_hash="d" * 64)

        with patch.object(
            source_folder_backfill,
            "_fetch_mijnrood_hash_to_folder",
            return_value={"d" * 64: 7},
        ):
            result = source_folder_backfill.backfill_source_folder_ids(dry_run=True)

        # Counts the would-be match
        self.assertEqual(result["matched"], 1)
        self.assertTrue(result["dry_run"])
        doc.reload()
        self.assertIsNone(doc.source_folder_id)
```

- [ ] **Step 2: Run test — verify failure**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.integration.test_source_folder_backfill
```

Expected: `ImportError` for `source_folder_backfill`.

- [ ] **Step 3: Implement the backfill module**

```python
# verenigingen/mijnrood_sync/services/source_folder_backfill.py
"""Backfill source_folder_id on Organization Documents via SHA256 lookup.

Bench-execute only. Idempotent — safe to re-run; rows already with
source_folder_id set are skipped without a MijnRood query.

Usage:
    bench --site veg11.veganisme.org execute \\
      verenigingen.mijnrood_sync.services.source_folder_backfill.backfill_source_folder_ids \\
      --kwargs '{"dry_run": true}'

Implementation note: if MijnRood does not store SHA256 hashes alongside
documents, _fetch_mijnrood_hash_to_folder must compute them via SFTP per
file. The current implementation tries the DB column first and falls back
to SFTP only if the column doesn't exist or returns no rows.
"""

import logging

import frappe

logger = logging.getLogger("verenigingen.mijnrood_sync.source_folder_backfill")


def backfill_source_folder_ids(dry_run: bool = False, batch_size: int = 200) -> dict:
    """Populate source_folder_id by matching file_hash against MijnRood docs.

    Returns a summary dict with counts.
    """
    # Find all Organization Documents missing source_folder_id but having a hash
    rows = frappe.db.get_all(
        "Organization Document",
        filters={"source_folder_id": ["is", "not set"], "file_hash": ["is", "set"]},
        fields=["name", "file_hash"],
    )

    already_set = frappe.db.count(
        "Organization Document",
        filters={"source_folder_id": ["is", "set"]},
    )

    if not rows:
        return {
            "matched": 0,
            "no_hash_match": 0,
            "already_set": already_set,
            "errors": [],
            "dry_run": dry_run,
        }

    # Fetch MijnRood hash → folder_id mapping
    try:
        hash_to_folder = _fetch_mijnrood_hash_to_folder()
    except Exception as e:
        return {
            "matched": 0,
            "no_hash_match": 0,
            "already_set": already_set,
            "errors": [f"MijnRood fetch failed: {e}"],
            "dry_run": dry_run,
        }

    matched = 0
    no_hash_match = 0
    errors: list[str] = []

    for idx, row in enumerate(rows, 1):
        folder_id = hash_to_folder.get(row["file_hash"])
        if folder_id is None:
            no_hash_match += 1
            continue

        matched += 1
        if not dry_run:
            try:
                frappe.db.set_value(
                    "Organization Document",
                    row["name"],
                    "source_folder_id",
                    folder_id,
                    update_modified=False,
                )
            except Exception as e:
                errors.append(f"{row['name']}: {e}")

        # Commit per batch
        if not dry_run and idx % batch_size == 0:
            frappe.db.commit()

    if not dry_run:
        frappe.db.commit()

    return {
        "matched": matched,
        "no_hash_match": no_hash_match,
        "already_set": already_set,
        "errors": errors,
        "dry_run": dry_run,
    }


def _fetch_mijnrood_hash_to_folder() -> dict[str, int]:
    """Return {sha256_hex: folder_id} for all MijnRood documents.

    Tries the MijnRood DB first (looking for a hash column); falls back
    to SFTP-and-hash if the DB doesn't expose hashes.
    """
    from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient

    settings = frappe.get_single("MijnRood Sync Settings")
    client = MijnRoodDatabaseClient(settings=settings)
    with client:
        try:
            return client.fetch_document_hash_to_folder()
        except AttributeError:
            # Method doesn't exist; fall back to SFTP hashing
            pass
        except Exception as e:
            logger.warning("MijnRood DB hash fetch failed (%s); falling back to SFTP", e)

    return _sftp_hash_to_folder(settings)


def _sftp_hash_to_folder(settings) -> dict[str, int]:
    """Fallback: download each MijnRood file via SFTP, compute sha256, build map."""
    import hashlib

    from verenigingen.mijnrood_sync.client import MijnRoodDatabaseClient
    from verenigingen.mijnrood_sync.sftp_client import MijnRoodSFTPClient

    db_client = MijnRoodDatabaseClient(settings=settings)
    with db_client:
        documents = db_client.fetch_documents()

    sftp_client = MijnRoodSFTPClient(settings=settings)
    out: dict[str, int] = {}
    with sftp_client:
        for doc in documents:
            upload_filename = doc.get("upload_file_name")
            folder_id = doc.get("folder_id")
            if not upload_filename or folder_id is None:
                continue
            try:
                content = sftp_client.download_file(upload_filename)
            except Exception as e:
                logger.warning("SFTP download failed for %s: %s", upload_filename, e)
                continue
            file_hash = hashlib.sha256(content).hexdigest()
            out[file_hash] = folder_id

    return out
```

- [ ] **Step 4: Run test — verify pass**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.integration.test_source_folder_backfill
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/source_folder_backfill.py \
        verenigingen/tests/integration/test_source_folder_backfill.py
git commit -m "feat(mijnrood-sync): add source_folder_id backfill command"
```

---

## Task 6 — Import-side change: write `applies_on` + `source_folder_id`, drop `upload_date` overload

**Goal:** in `_import_single_document`, stop writing the extracted date into `upload_date` (so its `default: "Today"` takes effect = record creation time); write the date+precision into the new fields instead; persist the source folder id.

**Files:**
- Modify: `verenigingen/mijnrood_sync/services/document_import_service.py:545-602`

- [ ] **Step 1: Read the current `_import_single_document` block to confirm line numbers**

```bash
sed -n '540,605p' verenigingen/mijnrood_sync/services/document_import_service.py
```

- [ ] **Step 2: Replace the date-extraction + doc-creation block**

In `verenigingen/mijnrood_sync/services/document_import_service.py`:

Replace the existing block (currently lines ~545-602: from `from verenigingen.utils.date_extraction import extract_date_from_text, extract_year_from_text` down through the `org_doc.insert()` call) with the following.

Old (delete):

```python
        from verenigingen.utils.date_extraction import extract_date_from_text, extract_year_from_text
        from verenigingen.utils.folder_category_detector import detect_category_from_folder_path

        # 1. Try MijnRood's date_uploaded first
        upload_date = self._parse_upload_date(doc)

        # 2. If no DB date, try extracting from document name / upload filename
        if not upload_date:
            upload_date = extract_date_from_text(original_name)

        # 3. If still no date, try the folder path
        folder_path = self._get_folder_path(doc.get("folder_id"))
        if not upload_date and folder_path:
            upload_date = extract_date_from_text(folder_path)

        # 4. Year from full date, or from text patterns, or "Other"
        if upload_date:
            year = str(upload_date.year)
        else:
            year = extract_year_from_text(original_name, default="Other")

        # 5. Auto-detect category from folder path if currently "Other"
        doc_type = detect_category_from_folder_path(folder_path or "", doc_type)

        # Save file to hierarchical storage
        from verenigingen.utils.file_storage import save_organization_document

        file_result = save_organization_document(
            content=content,
            filename=original_name,
            organization_type=org_type,
            organization_name=org_name,
            category=doc_type,
            year=year,
            is_private=1,
        )

        # Create Organization Document record
        org_doc = frappe.get_doc(
            {
                "doctype": "Organization Document",
                "organization_type": org_type,
                "chapter": mapping.get("chapter") if org_type == "Chapter" else None,
                "team": mapping.get("team") if org_type == "Team" else None,
                "movement": mapping.get("movement") if org_type == "Movement" else None,
                "document_name": original_name,
                "document_type": doc_type,
                "document_file": file_result["file_url"],
                "upload_date": upload_date.strftime("%Y-%m-%d") if upload_date else None,
                "uploaded_by": "Administrator",
                "file_hash": file_hash,
            }
        )
```

New (insert):

```python
        from verenigingen.utils.date_extraction import (
            extract_date_with_precision,
            extract_year_from_text,
        )
        from verenigingen.utils.folder_category_detector import detect_category_from_folder_path

        # Folder path for both date extraction and category auto-detect
        folder_path = self._get_folder_path(doc.get("folder_id"))

        # Date cascade for applies_on:
        # 1. Filename → 2. Folder path. (MijnRood's date_uploaded is an upload
        # timestamp on their side, not the document's content date — we
        # therefore don't use it for applies_on.)
        applies_on, applies_precision = extract_date_with_precision(original_name)
        if applies_on is None and folder_path:
            applies_on, applies_precision = extract_date_with_precision(folder_path)

        # File-storage year bucket: full date → year of date; else year-only
        # extraction; else "Other". Storage path is unchanged from before.
        if applies_on:
            year = str(applies_on.year)
        else:
            year = extract_year_from_text(original_name, default="Other")

        # Auto-detect category from folder path if currently "Other"
        doc_type = detect_category_from_folder_path(folder_path or "", doc_type)

        # Save file to hierarchical storage
        from verenigingen.utils.file_storage import save_organization_document

        file_result = save_organization_document(
            content=content,
            filename=original_name,
            organization_type=org_type,
            organization_name=org_name,
            category=doc_type,
            year=year,
            is_private=1,
        )

        # Create Organization Document record. upload_date is NOT set here so
        # the field's default ("Today") fires and reflects the import time —
        # the document's own date lives in applies_on / applies_on_precision.
        org_doc = frappe.get_doc(
            {
                "doctype": "Organization Document",
                "organization_type": org_type,
                "chapter": mapping.get("chapter") if org_type == "Chapter" else None,
                "team": mapping.get("team") if org_type == "Team" else None,
                "movement": mapping.get("movement") if org_type == "Movement" else None,
                "document_name": original_name,
                "document_type": doc_type,
                "document_file": file_result["file_url"],
                "applies_on": applies_on.strftime("%Y-%m-%d") if applies_on else None,
                "applies_on_precision": applies_precision if applies_on else "Day",
                "uploaded_by": "Administrator",
                "file_hash": file_hash,
                "source_folder_id": doc.get("folder_id"),
            }
        )
```

- [ ] **Step 3: Remove the now-unused `_parse_upload_date` method**

In the same file, delete the `_parse_upload_date` method and its docstring (the only caller was the removed code path).

```python
    def _parse_upload_date(self, doc: dict) -> datetime | None:
        """Parse date_uploaded from MijnRood document record.

        Falls back to extracting year from folder name if date is missing.
        """
        date_str = doc.get("date_uploaded")
        if not date_str:
            return None

        if isinstance(date_str, datetime):
            return date_str

        # Handle ISO format from _serialize_row
        try:
            return datetime.fromisoformat(str(date_str))
        except (ValueError, TypeError):
            return None
```

Also remove the now-unused `from datetime import datetime` import if no other code in the file uses it. Check first:

```bash
grep -n '\bdatetime\b' verenigingen/mijnrood_sync/services/document_import_service.py
```

If `datetime` is only used in the removed method's signature/body, drop the import too.

- [ ] **Step 4: Run the existing import service tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.mijnrood_sync.doctype.mijnrood_sync_settings.test_mijnrood_sync_settings
```

Expected: PASS. (If there were tests for `_parse_upload_date` they need to be updated; otherwise this should be green.)

If a deeper integration test for the import exists (search with `grep -rln "import_all\|_import_single_document" verenigingen/tests`), run it too.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/mijnrood_sync/services/document_import_service.py
git commit -m "fix(mijnrood-sync): write applies_on + source_folder_id; stop overloading upload_date"
```

---

## Task 7 — Reclassify backend service

**Goal:** new whitelisted method `reclassify_documents(names, dry_run=True)` that resolves each Organization Document's `source_folder_id` to a folder mapping row, computes the proposed diff for `(organization_type, chapter|team|movement, document_type, applies_on, applies_on_precision)`, and either returns it (dry-run) or writes via `db.set_value` per field. Caps at 500 names. Permission gated to System Manager / Verenigingen Administrator.

**Files:**
- Create: `verenigingen/mijnrood_sync/services/document_reclassify_service.py`
- Create: `verenigingen/tests/integration/test_document_reclassify_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# verenigingen/tests/integration/test_document_reclassify_service.py
"""Integration tests for document_reclassify_service.reclassify_documents."""

from datetime import date

import frappe

from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory
from verenigingen.tests.utils.base import VereningingenTestCase


class TestReclassifyDocuments(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = CoreTestDataFactory(cleanup_on_exit=False)
        cls.chapter_a = cls.factory.create_test_chapter()
        cls.chapter_b = cls.factory.create_test_chapter()

        # Configure the MijnRood Sync Settings child table with two mappings.
        # Snapshot the original mapping so tearDownClass restores it.
        settings = frappe.get_single("MijnRood Sync Settings")
        cls._original_mapping = [
            {
                "mijnrood_folder_id": r.mijnrood_folder_id,
                "folder_name": r.folder_name,
                "folder_path": r.folder_path,
                "organization_type": r.organization_type,
                "chapter": r.chapter,
                "team": r.team,
                "movement": r.movement,
                "document_type": r.document_type,
            }
            for r in (settings.document_folder_mapping or [])
        ]

        settings.set("document_folder_mapping", [])
        settings.append(
            "document_folder_mapping",
            {
                "mijnrood_folder_id": 100,
                "folder_name": "Notulen",
                "folder_path": "Afdelingen / Test A / Notulen",
                "organization_type": "Chapter",
                "chapter": cls.chapter_a.name,
                "document_type": "Notulen",
            },
        )
        settings.append(
            "document_folder_mapping",
            {
                "mijnrood_folder_id": 101,
                "folder_name": "Overig",
                "folder_path": "Afdelingen / Test B / Overig",
                "organization_type": "Chapter",
                "chapter": cls.chapter_b.name,
                "document_type": "Other",
            },
        )
        settings.flags.ignore_validate = True
        settings.flags.ignore_permissions = True
        settings.save()

        cls.settings_doc = settings

    @classmethod
    def tearDownClass(cls):
        # Restore the original mapping so we don't pollute the dev site
        settings = frappe.get_single("MijnRood Sync Settings")
        settings.set("document_folder_mapping", [])
        for row in cls._original_mapping:
            settings.append("document_folder_mapping", row)
        settings.flags.ignore_validate = True
        settings.flags.ignore_permissions = True
        settings.save()

        cls.factory.cleanup()
        super().tearDownClass()

    def _make_doc(self, **overrides):
        defaults = dict(
            doctype="Organization Document",
            organization_type="Chapter",
            chapter=self.chapter_b.name,  # "wrong" chapter on purpose
            document_name="2024-05-17 notulen.pdf",
            document_type="Other",
            document_file="/private/files/dummy.pdf",
            source_folder_id=100,  # mapped to chapter_a + Notulen
        )
        defaults.update(overrides)
        doc = frappe.get_doc(defaults)
        doc.flags.ignore_permissions = True
        doc.insert()
        self.addCleanup(lambda n=doc.name: frappe.delete_doc(
            "Organization Document", n, ignore_permissions=True, force=True))
        return doc

    def test_dry_run_returns_diff_without_writing(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        doc = self._make_doc()
        result = reclassify_documents([doc.name], dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["applied"], 0)
        self.assertEqual(len(result["changes"]), 1)

        change = result["changes"][0]
        self.assertEqual(change["name"], doc.name)
        self.assertIn("document_type", change["diff_fields"])
        self.assertIn("chapter", change["diff_fields"])
        self.assertIn("applies_on", change["diff_fields"])
        self.assertEqual(change["proposed"]["document_type"], "Notulen")
        self.assertEqual(change["proposed"]["chapter"], self.chapter_a.name)
        self.assertEqual(change["proposed"]["applies_on"], "2024-05-17")
        self.assertEqual(change["proposed"]["applies_on_precision"], "Day")

        # Verify nothing actually written
        doc.reload()
        self.assertEqual(doc.document_type, "Other")
        self.assertEqual(doc.chapter, self.chapter_b.name)
        self.assertIsNone(doc.applies_on)

    def test_apply_mode_writes_diff(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        doc = self._make_doc()
        result = reclassify_documents([doc.name], dry_run=False)

        self.assertEqual(result["applied"], 1)
        doc.reload()
        self.assertEqual(doc.document_type, "Notulen")
        self.assertEqual(doc.chapter, self.chapter_a.name)
        self.assertEqual(doc.applies_on, date(2024, 5, 17))
        self.assertEqual(doc.applies_on_precision, "Day")

    def test_unchanged_doc_skipped(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        # Doc that already matches the mapping
        doc = self._make_doc(
            chapter=self.chapter_a.name,
            document_type="Notulen",
            applies_on="2024-05-17",
            applies_on_precision="Day",
        )
        result = reclassify_documents([doc.name], dry_run=True)
        self.assertEqual(len(result["changes"]), 0)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["reason"], "unchanged")

    def test_no_source_folder_id_skipped(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        doc = self._make_doc(source_folder_id=None)
        result = reclassify_documents([doc.name], dry_run=True)
        self.assertEqual(len(result["changes"]), 0)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertIn("no source_folder_id", result["skipped"][0]["reason"])

    def test_unmapped_folder_skipped(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        doc = self._make_doc(source_folder_id=99999)  # not in mapping
        result = reclassify_documents([doc.name], dry_run=True)
        self.assertEqual(len(result["changes"]), 0)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["reason"], "no folder mapping")

    def test_date_falls_back_to_folder_path(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        # Folder 101's folder_path is "Afdelingen / Test B / Overig" — no date.
        # Append a year so the path-fallback fires:
        settings = frappe.get_single("MijnRood Sync Settings")
        for row in settings.document_folder_mapping:
            if row.mijnrood_folder_id == 101:
                row.folder_path = "Afdelingen / Test B / Overig / 2023"
        settings.flags.ignore_validate = True
        settings.flags.ignore_permissions = True
        settings.save()

        doc = self._make_doc(
            source_folder_id=101,
            chapter=self.chapter_a.name,  # wrong on purpose
            document_name="overige notulen.pdf",  # no date in name
        )
        result = reclassify_documents([doc.name], dry_run=True)

        change = result["changes"][0]
        self.assertEqual(change["proposed"]["applies_on"], "2023-01-01")
        self.assertEqual(change["proposed"]["applies_on_precision"], "Year")

    def test_cap_at_500(self):
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        names = [f"doc-{i}" for i in range(501)]
        with self.assertRaises(frappe.ValidationError):
            reclassify_documents(names, dry_run=True)

    def test_permission_denied_for_non_admin(self):
        """A user without System Manager / Verenigingen Administrator gets PermissionError.

        Per MEMORY.md: tests must exercise non-Admin role paths (Admin bypasses
        all DocPerms / only_for checks).
        """
        from verenigingen.mijnrood_sync.services.document_reclassify_service import (
            reclassify_documents,
        )

        # Create a member-only test user (no admin roles)
        member = self.factory.create_test_member()
        # The factory's create_test_member should produce a User; if not, skip with reason
        if not getattr(member, "user", None):
            self.skipTest("Test factory did not link a User to the Member")

        with self.as_user(member.user):
            with self.assertRaises(frappe.PermissionError):
                reclassify_documents(["nonexistent"], dry_run=True)
```

- [ ] **Step 2: Run test — verify failure**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.integration.test_document_reclassify_service
```

Expected: `ImportError` for `document_reclassify_service`.

- [ ] **Step 3: Implement the service**

```python
# verenigingen/mijnrood_sync/services/document_reclassify_service.py
"""Re-apply MijnRood folder mapping + extracted date to existing
Organization Documents.

Same backend serves both the single-doc form button and the list-view
bulk action. Dry-run produces a diff structure; apply mode writes via
db.set_value (bypassing OrganizationDocument.validate's board-membership
check, which would fail for sweeps across multiple chapters — entry is
already gated to admin roles via frappe.only_for).
"""

import json
import logging

import frappe
from frappe import _

logger = logging.getLogger("verenigingen.mijnrood_sync.document_reclassify")

MAX_BATCH = 500
ADMIN_ROLES = ["System Manager", "Verenigingen Administrator"]
DIFF_FIELDS = (
    "organization_type",
    "chapter",
    "team",
    "movement",
    "document_type",
    "applies_on",
    "applies_on_precision",
)


@frappe.whitelist()
def reclassify_documents(names, dry_run: bool = True) -> dict:
    """Re-apply MijnRood folder mapping + extracted date to existing docs.

    Args:
        names: List of Organization Document names (or JSON-encoded string).
        dry_run: If True, return preview only; no writes.

    Returns:
        {
          "dry_run": bool,
          "total": int,
          "applied": int,           # 0 in dry_run
          "changes": [...],         # per-doc diff
          "skipped": [...],         # per-doc skip reasons
        }
    """
    frappe.only_for(ADMIN_ROLES)

    # JSON-decode if called via HTTP (Frappe passes lists as JSON strings)
    if isinstance(names, str):
        names = json.loads(names)
    if not isinstance(names, list):
        frappe.throw(_("`names` must be a list of Organization Document names"))

    # Coerce dry_run when called via HTTP (it arrives as str "true"/"false")
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() == "true"

    if len(names) > MAX_BATCH:
        frappe.throw(
            _("Too many documents in one call ({0} > {1}); split into smaller batches.").format(
                len(names), MAX_BATCH
            )
        )

    settings = frappe.get_single("MijnRood Sync Settings")
    mapping_by_id = {
        row.mijnrood_folder_id: row for row in (settings.document_folder_mapping or [])
    }

    changes: list[dict] = []
    skipped: list[dict] = []
    applied = 0

    for name in names:
        try:
            doc = frappe.get_doc("Organization Document", name)
        except frappe.DoesNotExistError:
            skipped.append({"name": name, "reason": "document not found"})
            continue

        result = _process_doc(doc, mapping_by_id, dry_run)
        if result["status"] == "changed":
            changes.append(result["change"])
            if not dry_run:
                applied += 1
        else:
            skipped.append({"name": name, "reason": result["reason"]})

    return {
        "dry_run": dry_run,
        "total": len(names),
        "applied": applied,
        "changes": changes,
        "skipped": skipped,
    }


def _process_doc(doc, mapping_by_id: dict, dry_run: bool) -> dict:
    """Resolve mapping → compute diff → optionally write. Returns a status dict."""
    from verenigingen.utils.date_extraction import extract_date_with_precision

    if not doc.source_folder_id:
        return {"status": "skipped", "reason": "no source_folder_id (run backfill first)"}

    mapping_row = mapping_by_id.get(doc.source_folder_id)
    if mapping_row is None:
        return {"status": "skipped", "reason": "no folder mapping"}

    org_type = mapping_row.organization_type or doc.organization_type
    proposed = {
        "organization_type": org_type,
        "chapter": mapping_row.chapter if org_type == "Chapter" else None,
        "team": mapping_row.team if org_type == "Team" else None,
        "movement": mapping_row.movement if org_type == "Movement" else None,
        "document_type": mapping_row.document_type or doc.document_type,
    }

    # Date cascade: filename → folder_path (from mapping row)
    applies_on, precision = extract_date_with_precision(doc.document_name or "")
    if applies_on is None:
        applies_on, precision = extract_date_with_precision(mapping_row.folder_path or "")

    proposed["applies_on"] = applies_on.strftime("%Y-%m-%d") if applies_on else None
    proposed["applies_on_precision"] = precision if applies_on else (doc.applies_on_precision or "Day")

    current = {f: doc.get(f) for f in DIFF_FIELDS}
    # Normalise current applies_on to ISO string for comparison
    if current["applies_on"] is not None:
        current["applies_on"] = frappe.utils.formatdate(current["applies_on"], "yyyy-MM-dd")

    diff_fields = [f for f in DIFF_FIELDS if (current.get(f) or None) != (proposed.get(f) or None)]
    if not diff_fields:
        return {"status": "skipped", "reason": "unchanged"}

    if not dry_run:
        for f in diff_fields:
            frappe.db.set_value(
                "Organization Document",
                doc.name,
                f,
                proposed[f],
                update_modified=False,
            )
        frappe.db.commit()

    return {
        "status": "changed",
        "change": {
            "name": doc.name,
            "current": current,
            "proposed": proposed,
            "diff_fields": diff_fields,
        },
    }
```

- [ ] **Step 4: Run test — verify pass**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.integration.test_document_reclassify_service
```

Expected: 7 tests PASS (one may skip if the test factory doesn't link a User to a Member — that's the SkipTest in `test_permission_denied_for_non_admin`).

- [ ] **Step 5: Commit (skip the broken pre-commit hook)**

```bash
SKIP=whitelist-type-safety,javascript-doctype-validator,jest-testing git add \
  verenigingen/mijnrood_sync/services/document_reclassify_service.py \
  verenigingen/tests/integration/test_document_reclassify_service.py
SKIP=whitelist-type-safety,javascript-doctype-validator,jest-testing git commit \
  -m "feat(mijnrood-sync): reclassify_documents service for Organization Documents"
```

---

## Task 8 — Form JS: precision snap + reclassify button

**Goal:** extend `organization_document.js` with `applies_on_precision` / `applies_on` snap-to-1 handlers, and a `Reclassify from MijnRood folder` form button that calls the backend dry-run, shows a confirm dialog with the proposed diff, and applies on confirm. Visible only when `frm.doc.source_folder_id` is set.

**Files:**
- Modify: `verenigingen/verenigingen/doctype/organization_document/organization_document.js`

- [ ] **Step 1: Replace the form script**

Full new contents:

```javascript
// Copyright (c) 2025, Veganisme.org and contributors
// For license information, please see license.txt

frappe.ui.form.on('Organization Document', {
	setup(frm) {
		// Load document categories from Settings (single source of truth)
		frappe.call({
			method: 'verenigingen.utils.document_categories.get_document_category_options',
			callback(r) {
				if (r.message) {
					frm.set_df_property('document_type', 'options', r.message);
				}
			}
		});
	},

	refresh(frm) {
		if (frm.is_new() || !frm.doc.source_folder_id) {
			return;
		}
		frm.add_custom_button(__('Reclassify from MijnRood folder'), () => {
			run_reclassify_flow(frm, [frm.doc.name], () => frm.reload_doc());
		}, __('Actions'));
	},

	applies_on_precision(frm) {
		if (!frm.doc.applies_on) return;
		const d = frappe.datetime.str_to_obj(frm.doc.applies_on);
		if (!d) return;

		if (frm.doc.applies_on_precision === 'Month' && d.getDate() !== 1) {
			d.setDate(1);
			frm.set_value('applies_on', frappe.datetime.obj_to_str(d));
		} else if (frm.doc.applies_on_precision === 'Year' && (d.getMonth() !== 0 || d.getDate() !== 1)) {
			d.setMonth(0);
			d.setDate(1);
			frm.set_value('applies_on', frappe.datetime.obj_to_str(d));
		}
	},

	applies_on(frm) {
		if (!frm.doc.applies_on) return;
		const d = frappe.datetime.str_to_obj(frm.doc.applies_on);
		if (!d) return;

		// If the user picked a non-1 day, force precision to Day. Don't touch
		// precision when day is 1 — could be a real Jan 1 or month-precision.
		if (d.getDate() !== 1 && frm.doc.applies_on_precision !== 'Day') {
			frm.set_value('applies_on_precision', 'Day');
		}
	}
});

// Shared dry-run → confirm → apply flow used by both the form button
// (single doc) and the list-view bulk action.
window.verenigingen = window.verenigingen || {};
window.verenigingen.run_reclassify_flow = run_reclassify_flow;

function run_reclassify_flow(callerFrm, names, onApplied) {
	frappe.call({
		method: 'verenigingen.mijnrood_sync.services.document_reclassify_service.reclassify_documents',
		args: { names: names, dry_run: true },
		freeze: true,
		freeze_message: __('Computing reclassification preview…'),
		callback(r) {
			if (!r.message) return;
			show_reclassify_preview(r.message, () => {
				frappe.call({
					method: 'verenigingen.mijnrood_sync.services.document_reclassify_service.reclassify_documents',
					args: { names: names, dry_run: false },
					freeze: true,
					freeze_message: __('Applying reclassification…'),
					callback(r2) {
						if (!r2.message) return;
						frappe.show_alert({
							message: __('Reclassified {0} documents.', [r2.message.applied]),
							indicator: 'green'
						});
						if (onApplied) onApplied();
					}
				});
			});
		}
	});
}

function show_reclassify_preview(result, onConfirm) {
	const changes = result.changes || [];
	const skipped = result.skipped || [];

	if (!changes.length) {
		frappe.msgprint({
			title: __('Nothing to reclassify'),
			message: __('All {0} documents are unchanged or skipped (skipped: {1}).',
				[result.total, skipped.length]),
			indicator: 'blue'
		});
		return;
	}

	const rows = changes.flatMap(c => c.diff_fields.map(f => `
		<tr>
			<td>${frappe.utils.escape_html(c.name)}</td>
			<td>${frappe.utils.escape_html(f)}</td>
			<td>${frappe.utils.escape_html(String(c.current[f] ?? ''))}</td>
			<td>${frappe.utils.escape_html(String(c.proposed[f] ?? ''))}</td>
		</tr>
	`)).join('');

	const html = `
		<div style="max-height: 400px; overflow-y: auto;">
			<table class="table table-bordered" style="font-size: 12px;">
				<thead><tr>
					<th>${__('Document')}</th><th>${__('Field')}</th>
					<th>${__('Current')}</th><th>${__('Proposed')}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
		<p>${__('{0} change(s), {1} skipped.', [changes.length, skipped.length])}</p>
	`;

	const dialog = new frappe.ui.Dialog({
		title: __('Reclassify preview'),
		size: 'large',
		primary_action_label: __('Apply'),
		primary_action() {
			dialog.hide();
			onConfirm();
		}
	});
	dialog.$body.html(html);
	dialog.show();
}
```

- [ ] **Step 2: Build assets and clear cache**

```bash
cd ~/frappe-bench && bench build --app verenigingen && bench --site veg11.veganisme.org clear-cache
```

- [ ] **Step 3: Manual smoke test (browser)**

1. Open an existing Organization Document with `source_folder_id` set.
2. Verify the `Actions → Reclassify from MijnRood folder` button appears.
3. Click; preview dialog renders the diff; clicking Apply writes the change and reloads the form.
4. Open a fresh doc, set Precision to Month, set Applies On to a non-1 day → day snaps to 1.
5. Set Precision to Year, set Applies On to mid-year → date snaps to YYYY-01-01.
6. With Precision = Month, manually change Applies On day to 17 → Precision flips to Day.

If `source_folder_id` is empty, the button must be hidden.

- [ ] **Step 4: Commit**

```bash
git add verenigingen/verenigingen/doctype/organization_document/organization_document.js
git commit -m "feat(organization-document): JS precision snap-to-1 + reclassify form button"
```

---

## Task 9 — List-view bulk action

**Goal:** add an Actions menu entry on the Organization Document list view that invokes the same dry-run → confirm → apply flow over the user's selected items. Visible only to System Manager / Verenigingen Administrator.

**Files:**
- Create: `verenigingen/verenigingen/doctype/organization_document/organization_document_list.js`

- [ ] **Step 1: Create the list-view script**

```javascript
// Copyright (c) 2025, Veganisme.org and contributors
// List-view customization for Organization Document.

frappe.listview_settings['Organization Document'] = {
	onload(listview) {
		const roles = frappe.user_roles || [];
		const allowed = roles.includes('System Manager') || roles.includes('Verenigingen Administrator');
		if (!allowed) return;

		listview.page.add_actions_menu_item(__('Reclassify from MijnRood folder'), () => {
			const items = listview.get_checked_items();
			if (!items.length) {
				frappe.msgprint(__('Select at least one document.'));
				return;
			}
			const names = items.map(i => i.name);

			// Reuse the form's flow if loaded; otherwise call directly.
			if (window.verenigingen && window.verenigingen.run_reclassify_flow) {
				window.verenigingen.run_reclassify_flow(null, names, () => listview.refresh());
			} else {
				// The form bundle defines the helper; if a user opens the list
				// without ever opening a form, fall back to a minimal flow.
				frappe.call({
					method: 'verenigingen.mijnrood_sync.services.document_reclassify_service.reclassify_documents',
					args: { names: names, dry_run: false },
					freeze: true,
					callback(r) {
						if (!r.message) return;
						frappe.show_alert({
							message: __('Reclassified {0} documents.', [r.message.applied]),
							indicator: 'green'
						});
						listview.refresh();
					}
				});
			}
		});
	}
};
```

- [ ] **Step 2: Build assets and clear cache**

```bash
cd ~/frappe-bench && bench build --app verenigingen && bench --site veg11.veganisme.org clear-cache
```

- [ ] **Step 3: Manual smoke test (browser)**

1. Open the Organization Document list as a System Manager.
2. Confirm the `Actions → Reclassify from MijnRood folder` menu entry is present.
3. Select 2–3 docs, run the action, confirm the preview, verify writes.
4. Log in as a non-admin (e.g. a Verenigingen Member) → confirm the action item is absent.

- [ ] **Step 4: Commit**

```bash
git add verenigingen/verenigingen/doctype/organization_document/organization_document_list.js
git commit -m "feat(organization-document): list-view bulk Reclassify action"
```

---

## Operator runbook (post-deploy)

Run these once after the patch + code lands:

1. **Patch already ran** as part of `bench migrate` (Task 4). Verify by inspecting `tabPatch Log` for `verenigingen.patches.v2_2.clean_overloaded_upload_date`.
2. **Backfill source_folder_id** (Task 5):
   ```bash
   cd ~/frappe-bench && bench --site veg11.veganisme.org execute \
     verenigingen.mijnrood_sync.services.source_folder_backfill.backfill_source_folder_ids \
     --kwargs '{"dry_run": true}'
   ```
   Inspect counts. When happy:
   ```bash
   cd ~/frappe-bench && bench --site veg11.veganisme.org execute \
     verenigingen.mijnrood_sync.services.source_folder_backfill.backfill_source_folder_ids
   ```
3. **(Optional) Refresh folder mapping** before sweeping reclassify so `folder_path` is current:
   - Open MijnRood Sync Settings → Fetch document folders.
4. **Reclassify** via the list view (filter by chapter, select all, Actions → Reclassify from MijnRood folder, Apply).

---

## Self-review notes

- **Spec coverage:**
  - § 1 Schema → Task 1
  - § 2 Precision snap (server) → Task 2
  - § 2 Precision snap (JS) → Task 8
  - § 3 Date helper → Task 3
  - § 4 Reclassify backend → Task 7
  - § 5 Reclassify JS (form button) → Task 8; (list view) → Task 9
  - § 6 Import-side change → Task 6
  - § 7 Backfill command → Task 5
  - § 8 Cleanup patch → Task 4
  - § 9 Permissions → Task 7 (server-side `frappe.only_for`); Task 9 (list-view visibility, cosmetic)
  - § 10 Rollout order → Task ordering follows spec § 10
  - § 11 Testing → Tasks 2, 3, 5, 7

- **Type / name consistency:** the helper is `extract_date_with_precision` in Tasks 3, 6, 7. Backend service file is `document_reclassify_service.py` and method is `reclassify_documents` in Tasks 7, 8, 9. Field names `applies_on`, `applies_on_precision`, `source_folder_id` are consistent across all tasks.

- **No placeholders:** every step has either complete code, an exact command, or expected output. The two manual UI smoke checks (Tasks 8 & 9) enumerate the specific scenarios to click.
