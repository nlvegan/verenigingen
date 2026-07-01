# BaseCSVImport Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate ~120 LOC of structural duplication between `procurios_mandate_import.py` and `procurios_csv_import.py` by extracting a `BaseCSVImport(Document)` class plus a small set of module-level helpers for whitelisted entry points.

**Architecture:** Subclass-of-Document base class for shared *instance* methods/properties (`_parser`, `validate`, `_read_csv_file`, `on_submit`). Module-level helpers for whitelisted entry points (`run_csv_validation`, `mark_failed`, `prepare_background_import`, `format_truncated_error_log`) because Frappe's `frappe.enqueue` resolves jobs by dotted module path — the whitelisted functions themselves must live at module scope in each DocType file. Both Procurios DocType controllers become thin subclasses that supply only their own validator type, validation body, per-row processor, and finalize body.

**Tech Stack:** Frappe Framework, Python 3.14, pytest/unittest, EnhancedTestCase fixtures.

**Out of scope:**
- `mijnrood_csv_import.py` — uses the explicit-mangled-name idiom and ~2000 LOC of domain orchestration (Account Creation Requests, Bulk Volunteer Service, Mollie sync) that would fight a base class. Per handoff §8 it gets a short *referencing-the-gotcha* comment, no inheritance.
- Reworking `csv_import_processor.py` (`CSVImportBackgroundProcessor`, `progress_field_map`, `bulk_member_operations` context manager). This module is a stable extension point used by all three importers and stays untouched.
- The per-row processors and `_build_caches` — domain-specific.
- The `_validate_and_preview_csv` *body* in each subclass — genuinely different validator return shapes. Only the failure-path skeleton is extracted as a helper.

**Reference:**
- Spec / what to extract: `docs/plans/2026-06-03-procurios-mandate-import-handoff.md` §8 (Skeptical TD-3), §9 (don't-break list).
- Existing tests guarding the property-cache pattern: `TestPropertyCacheHits` (mandate) and `TestProcuriosCSVImportPropertyCache` (sibling) — both assert `doc._validator is doc._validator`. These will catch any base-class implementation that re-breaks the name-mangling fix automatically.

---

## File Structure

**New:**
- `verenigingen/utils/csv/base_csv_import.py` — `BaseCSVImport` Document subclass + module-level helpers. Single file, ~150 LOC.
- `verenigingen/tests/utils/csv/test_base_csv_import.py` — focused tests for the module-level helpers and the property-cache contract.

**Modified:**
- `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py` — inherit from `BaseCSVImport`; delete `_parser`, `validate`, `_read_csv_file`, `on_submit`, `_ADMIN_ROLES`; delegate `validate_import_file` and the outer skeleton of `process_import_background` to shared helpers.
- `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py` — same refactor as mandate.
- `verenigingen/verenigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py` — add a one-paragraph header comment explaining *why* it does NOT inherit from `BaseCSVImport` (different name-mangling pattern + heavy orchestration). Per handoff §8.

**Untouched:**
- `verenigingen/utils/csv_import_processor.py`
- The three validator modules (`procurios_mandate_validator.py`, `procurios_data_validator.py`, `csv_data_validator.py`)
- All existing tests at `tests/payment/test_procurios_mandate_*.py` and `tests/member/test_procurios_csv_import.py` — they MUST pass unchanged.

---

## Task 1: Branch + scratch sanity check

**Files:** none (workspace setup only)

- [ ] **Step 1: Confirm a clean working tree for the refactor**

The current `develop` has unrelated uncommitted changes (donor tests, donor.py, volunteer assignment tests, the handoff doc). Do the refactor on a feature branch off `develop` so the diff is reviewable in isolation.

Run:
```bash
cd ~/frappe-bench/apps/verenigingen
git status --short
git checkout -b refactor/base-csv-import-extraction
```

Expected: a new branch `refactor/base-csv-import-extraction` exists; uncommitted files come along but stay uncommitted.

- [ ] **Step 2: Verify the two affected suites pass on the current branch before any change**

This is the regression baseline. If anything fails *before* we touch code, that's a pre-existing issue and must be noted but not "fixed" inside this refactor.

Run:
```bash
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_procurios_mandate_import 2>&1 | tail -30
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.member.test_procurios_csv_import 2>&1 | tail -30
```

Expected: both report "OK" (or skip counts but no failures). If failures appear, record them in a `BASELINE.md` scratch note before proceeding — those failures must still be failing in exactly the same way at the end of Task 5.

---

## Task 2: Module-level helpers + tests (TDD, no behaviour change yet)

**Files:**
- Create: `verenigingen/utils/csv/base_csv_import.py`
- Create: `verenigingen/tests/utils/csv/__init__.py` (empty)
- Test: `verenigingen/tests/utils/csv/test_base_csv_import.py`

These helpers are pure functions, so they can be unit-tested without a DocType. We extract them first because the base class methods will call them.

### What goes in the helpers

The handoff inventory of duplication (§8 TD-3): the `validate_import_file` wrapper, the `process_import_background` outer structure, the finalize skeleton's error-log truncation, the admin-role constant, and the `test_mode` coercion entry point.

The helpers we create:
1. `ADMIN_ROLES: list[str]` — constant `["System Manager", "Verenigingen Administrator"]`.
2. `run_csv_validation(doctype: str, import_doc_name: str) -> dict` — the body of `validate_import_file` (only_for gate, `get_doc`, call `doc._validate_and_preview_csv()`, reload, return success/error dict, catch and sanitize exceptions).
3. `prepare_background_import(doctype: str, import_doc_name: str, test_mode) -> tuple[Document, bool]` — the entry-prologue of `process_import_background`: `only_for` (BEFORE any flag side-effects), `coerce_test_mode`, set `frappe.flags.in_background_job` and `frappe.flags.ignore_version_changes` (NOT `bulk_member_operations` — that one is sibling-specific and the sibling keeps its own context manager), `get_doc`, return `(doc, test_mode_bool)`.
4. `mark_import_failed(doc, error_message: str) -> None` — reload + db_set "Failed" + db_set error_log (sanitised) + commit. Used in both the validate-stage failure paths and the background-job catastrophic except-block. Reload is needed because the caller is a background job whose in-memory state may be stale.
5. `format_truncated_error_log(error_log: list[str], max_lines: int = 50) -> str` — the `"\n".join(error_log[:max_lines])` + `... and N more` pattern, factored out.

- [ ] **Step 1: Write the failing tests**

Write tests for each helper. Use `unittest.TestCase` (pure-Python where possible) and `EnhancedTestCase` only where Frappe-DB access is required.

```python
# verenigingen/tests/utils/csv/test_base_csv_import.py
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFormatTruncatedErrorLog(unittest.TestCase):
    """format_truncated_error_log: pure string-list helper."""

    def test_empty_list_returns_empty_string(self):
        from verenigingen.utils.csv.base_csv_import import format_truncated_error_log

        self.assertEqual(format_truncated_error_log([]), "")

    def test_under_limit_joins_all(self):
        from verenigingen.utils.csv.base_csv_import import format_truncated_error_log

        result = format_truncated_error_log(["a", "b", "c"], max_lines=50)
        self.assertEqual(result, "a\nb\nc")

    def test_over_limit_truncates_and_appends_tail(self):
        from verenigingen.utils.csv.base_csv_import import format_truncated_error_log

        errors = [f"row {i}" for i in range(60)]
        result = format_truncated_error_log(errors, max_lines=50)
        lines = result.split("\n")
        # 50 truncated lines + 1 tail line
        self.assertEqual(len(lines), 51)
        self.assertEqual(lines[0], "row 0")
        self.assertEqual(lines[49], "row 49")
        self.assertEqual(lines[50], "... and 10 more errors")

    def test_custom_max_lines(self):
        from verenigingen.utils.csv.base_csv_import import format_truncated_error_log

        errors = ["a", "b", "c", "d", "e"]
        result = format_truncated_error_log(errors, max_lines=2)
        self.assertEqual(result, "a\nb\n... and 3 more errors")


class TestRunCsvValidation(EnhancedTestCase):
    """run_csv_validation: orchestrates only_for + get_doc + delegate + return dict.

    Uses Procurios Mandate Import as the concrete doctype since it's
    already present and has a working _validate_and_preview_csv.
    """

    def test_non_admin_caller_is_rejected(self):
        # Mock justified: frappe.only_for() raises PermissionError when the
        # session user lacks the role. We assert the raise propagates from
        # the helper without being swallowed by the broad except.
        from verenigingen.utils.csv.base_csv_import import run_csv_validation

        with self.set_user("Guest"):
            with self.assertRaisesRegex(frappe.PermissionError, "only allowed"):
                run_csv_validation("Procurios Mandate Import", "PMI-NON-EXISTENT")

    def test_admin_caller_passes_only_for_then_get_doc_fails_cleanly(self):
        from verenigingen.utils.csv.base_csv_import import run_csv_validation

        # As Administrator, only_for passes; get_doc on a non-existent name
        # raises DoesNotExistError which the helper catches and reports as
        # an error dict (sanitized).
        result = run_csv_validation("Procurios Mandate Import", "PMI-DOES-NOT-EXIST")
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)


class TestPrepareBackgroundImport(EnhancedTestCase):
    """prepare_background_import: only_for runs BEFORE flag side-effects."""

    def test_non_admin_caller_is_rejected_before_flags_set(self):
        # Mock justified: this is the security regression that round 2 of
        # the original review caught. only_for() must throw before
        # frappe.flags.in_background_job is set, or an unauthorised caller
        # can flip flags for their own session.
        from verenigingen.utils.csv.base_csv_import import prepare_background_import

        # Pre-set the flag to a known value to detect side-effects.
        frappe.flags.in_background_job = False
        with self.set_user("Guest"):
            with self.assertRaisesRegex(frappe.PermissionError, "only allowed"):
                prepare_background_import(
                    "Procurios Mandate Import", "PMI-X", False
                )
        # Flag was NOT flipped by the rejected call.
        self.assertFalse(getattr(frappe.flags, "in_background_job", False))

    def test_string_test_mode_is_coerced(self):
        # Round-2 finding: REST callers send strings; "false" is truthy if not coerced.
        from verenigingen.utils.csv.base_csv_import import prepare_background_import

        # We can't easily exercise this without a real import doc, but we
        # can verify coerce_test_mode is invoked by checking that "false"
        # comes back as False (via a stubbed get_doc).
        with patch.object(frappe, "get_doc") as mocked:
            mocked.return_value = MagicMock(name="ProcuriosMandateImport")
            doc, test_mode = prepare_background_import(
                "Procurios Mandate Import", "PMI-DUMMY", "false"
            )
            self.assertFalse(test_mode)
        # Cleanup: prepare_background_import sets in_background_job=True;
        # reset so the next test sees the expected baseline.
        frappe.flags.in_background_job = False
        frappe.flags.ignore_version_changes = False


class TestMarkImportFailed(EnhancedTestCase):
    """mark_import_failed: reload + Failed status + sanitized error_log + commit."""

    def test_sets_failed_status_and_sanitized_log(self):
        from verenigingen.utils.csv.base_csv_import import mark_import_failed

        # Create a real Procurios Mandate Import in a Validating state.
        doc = frappe.get_doc(
            {
                "doctype": "Procurios Mandate Import",
                "import_date": frappe.utils.today(),
                "encoding": "auto-detect",
                "csv_delimiter": ";",
                "import_status": "Validating",
            }
        ).insert(ignore_permissions=True)
        try:
            mark_import_failed(doc, "boom: something/with/a/path.csv")
            doc.reload()
            self.assertEqual(doc.import_status, "Failed")
            # sanitize_error_for_audit should redact path-like content; we
            # only assert the status was set and the log is non-empty.
            self.assertTrue(doc.error_log)
        finally:
            frappe.delete_doc("Procurios Mandate Import", doc.name, force=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.utils.csv.test_base_csv_import 2>&1 | tail -20
```

Expected: all tests fail with `ImportError: cannot import name '...' from 'verenigingen.utils.csv.base_csv_import'` (the module doesn't exist yet).

- [ ] **Step 3: Write the minimal implementation**

Create `verenigingen/utils/csv/base_csv_import.py`:

```python
# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Shared scaffolding for Procurios CSV importers.

Two DocType controllers share ~120 LOC of structural boilerplate
(`procurios_mandate_import.py` and `procurios_csv_import.py`). This
module hosts:

  - `BaseCSVImport`: a Document subclass providing the shared
    instance methods (parser/validator caching, the `validate()` hook,
    `_read_csv_file`, `on_submit`).
  - Module-level helpers used by the whitelisted entry points
    (`validate_import_file`, `process_import_background`) of each
    concrete doctype. These can't live on the class because
    `frappe.enqueue` resolves jobs by dotted module path — every
    concrete doctype must still expose `validate_import_file` and
    `process_import_background` at its own module level.

`mijnrood_csv_import.py` deliberately does NOT inherit from this
class — see the header comment on that file for why.

Design / handoff: docs/plans/2026-06-03-procurios-mandate-import-handoff.md §8.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import frappe
from frappe.model.document import Document
from frappe.utils import today

from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.csv_import_processor import coerce_test_mode
from verenigingen.utils.error_handling import sanitize_error_for_audit


ADMIN_ROLES: List[str] = ["System Manager", "Verenigingen Administrator"]


# ---- module-level helpers ----------------------------------------------


def format_truncated_error_log(error_log: List[str], max_lines: int = 50) -> str:
    """Join up to `max_lines` errors with a `... and N more` tail.

    Both Procurios importers truncate error_log identically before
    persisting to the UI-displayed text field. Single definition keeps
    the tail format consistent.
    """
    if not error_log:
        return ""
    truncated = "\n".join(error_log[:max_lines])
    if len(error_log) > max_lines:
        truncated += f"\n... and {len(error_log) - max_lines} more errors"
    return truncated


def run_csv_validation(doctype: str, import_doc_name: str) -> dict:
    """Body of every concrete `validate_import_file` whitelisted helper.

    Each concrete doctype's @frappe.whitelist() entry just calls
    `return run_csv_validation("<doctype>", import_doc_name)`. We can't
    @frappe.whitelist() this function itself because Frappe's whitelist
    is keyed on object identity per module path.
    """
    frappe.only_for(ADMIN_ROLES, message=True)
    doc = frappe.get_doc(doctype, import_doc_name)
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


def prepare_background_import(
    doctype: str, import_doc_name: str, test_mode
) -> Tuple[Document, bool]:
    """Entry-prologue for every concrete `process_import_background`.

    Performs the four things every importer's background job needs to do
    before its specific work:

    1. `frappe.only_for(ADMIN_ROLES)` — gates the call. MUST run BEFORE
       any flag side-effects (round-2 review finding); an unauthorised
       caller must not be able to flip `frappe.flags.in_background_job`
       for their own session before the exception fires.
    2. Coerce `test_mode` from whatever the REST layer handed us
       (could be `"false"`, `0`, `None`, etc.) to a real `bool`.
    3. Set the two flags every CSV importer needs:
       `in_background_job` and `ignore_version_changes`. Note: the
       per-importer `bulk_member_operations` flag is NOT set here — only
       the sibling member-importer needs it, and it manages its own
       context manager.
    4. Load the import doc and hand both back to the caller.

    Returns `(doc, coerced_test_mode_bool)`.
    """
    frappe.only_for(ADMIN_ROLES, message=True)
    test_mode = coerce_test_mode(test_mode)

    frappe.flags.in_background_job = True
    frappe.flags.ignore_version_changes = True

    doc = frappe.get_doc(doctype, import_doc_name)
    return doc, test_mode


def mark_import_failed(doc: Document, error_message: str) -> None:
    """Mark an import doc Failed with a sanitized error log and commit.

    Used by the validate-stage failure paths and the background-job
    catastrophic except-block in both Procurios controllers. Reloads
    first because background-job callers may hold a stale in-memory
    document.
    """
    doc.reload()
    doc.db_set("import_status", "Failed")
    doc.db_set("error_log", sanitize_error_for_audit(error_message))
    frappe.db.commit()


# ---- base class --------------------------------------------------------


class BaseCSVImport(Document):
    """Shared scaffolding for Procurios CSV importers.

    Subclasses MUST define:
      - `_BACKGROUND_METHOD: str` — dotted path to their module-level
        `process_import_background` for `frappe.enqueue`.
      - `_validator` property — the subclass-specific validator type
        (e.g. `ProcuriosMandateValidator()` vs
        `ProcuriosDataValidator(import_gender=...)`).
      - `_validate_and_preview_csv()` — the validation+preview body
        (different validators yield different return shapes; the outer
        skeleton stays per-subclass).
      - per-row processor and `_finalize_import_results` — domain logic.

    Subclasses MAY override `validate()`, `on_submit()`, `_parser`,
    `_read_csv_file()` if they need additional behaviour, but they
    should call `super()` to keep the shared logic intact.

    NOTE on name mangling: the cache slot is `_parser_instance` /
    `_validator_instance` (single underscore). A double-underscore name
    like `__parser` would mangle to `_BaseCSVImport__parser` in *this*
    class but `_ConcreteSubclass__parser` in subclass code, breaking
    the hasattr-then-set idiom. Single-underscore + single-hyphenated
    cache-slot name keeps the cache shared across the inheritance
    chain and consistent with `hasattr(self, "_parser_instance")`.
    Tests `TestPropertyCacheHits` /
    `TestProcuriosCSVImportPropertyCache` are explicit regression
    guards on this.
    """

    @property
    def _parser(self) -> SecureCSVParser:
        if not hasattr(self, "_parser_instance"):
            encoding = None if self.encoding == "auto-detect" else self.encoding
            self._parser_instance = SecureCSVParser(
                encoding=encoding,
                delimiter=getattr(self, "csv_delimiter", None),
            )
        return self._parser_instance

    def validate(self) -> None:
        if not getattr(self, "import_date", None):
            self.import_date = today()

    def _read_csv_file(self) -> List[dict]:
        return self._parser.read_csv_file(self.csv_file)

    def on_submit(self) -> None:
        """Enqueue the subclass-specific background job.

        Subclasses MUST set `_BACKGROUND_METHOD` to their module-level
        `process_import_background`'s dotted path. test_mode is coerced
        to bool here so the enqueued args are unambiguous; the receiver
        re-coerces defensively via `coerce_test_mode`.
        """
        self.db_set("import_status", "Queued")
        frappe.enqueue(
            method=self._BACKGROUND_METHOD,
            queue="long",
            timeout=3600,
            import_doc_name=self.name,
            test_mode=bool(getattr(self, "test_mode", False)),
            now=False,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.utils.csv.test_base_csv_import 2>&1 | tail -20
```

Expected: all helper tests pass. If `TestPrepareBackgroundImport.test_string_test_mode_is_coerced` fails because the mocked `get_doc` doesn't quite work, simplify to checking `coerce_test_mode("false") is False` directly via the helper module.

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/utils/csv/base_csv_import.py \
        verenigingen/tests/utils/csv/__init__.py \
        verenigingen/tests/utils/csv/test_base_csv_import.py
git commit -m "feat(csv): add BaseCSVImport scaffolding + helpers

Pulls the ~120 LOC of structural duplication between
procurios_mandate_import.py and procurios_csv_import.py into a
shared module:

- BaseCSVImport(Document) with shared _parser/_validate/_read_csv_file/on_submit
- run_csv_validation, prepare_background_import, mark_import_failed
- format_truncated_error_log

Subclass migration in the next commits."
```

---

## Task 3: Migrate `procurios_mandate_import.py`

**Files:**
- Modify: `verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py`
- Test (no change): `verenigingen/tests/payment/test_procurios_mandate_import.py`, `verenigingen/tests/payment/test_procurios_mandate_validator.py`

The integration tests in `test_procurios_mandate_import.py` ARE the regression net. After this refactor they must pass without any test-file changes. The `TestPropertyCacheHits` test guards the name-mangling fix.

- [ ] **Step 1: Edit the controller to inherit and remove duplicated members**

Apply in one edit:

**A.** Imports — drop `today`, drop the `SecureCSVParser` import (re-exported via base), add the `BaseCSVImport` and helper imports. Keep `sanitize_error_for_audit` (still used in the `_validate_and_preview_csv` exception path and per-row processor).

Replace:
```python
import frappe
from frappe.model.document import Document
from frappe.utils import today

from verenigingen.utils.csv.procurios_mandate_validator import (
    ProcuriosMandateRow,
    ProcuriosMandateValidator,
)
from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.error_handling import sanitize_error_for_audit
```

with:
```python
import frappe

from verenigingen.utils.csv.base_csv_import import (
    ADMIN_ROLES,
    BaseCSVImport,
    format_truncated_error_log,
    mark_import_failed,
    prepare_background_import,
    run_csv_validation,
)
from verenigingen.utils.csv.procurios_mandate_validator import (
    ProcuriosMandateRow,
    ProcuriosMandateValidator,
)
from verenigingen.utils.error_handling import sanitize_error_for_audit
```

**B.** Class declaration and shared methods — change the base, drop `_parser`, drop `validate`, drop `_read_csv_file`, drop `on_submit`, KEEP `_validator` (subclass-specific type), add `_BACKGROUND_METHOD` class attribute.

Replace:
```python
class ProcuriosMandateImport(Document):
    # Cache slots: single underscore so Python name-mangling doesn't break
    # the hasattr-then-set idiom (a double-underscore attribute would mangle
    # to _ProcuriosMandateImport__x, leaving the hasattr check perpetually
    # False against the unmangled name).
    @property
    def _parser(self) -> SecureCSVParser:
        if not hasattr(self, "_parser_instance"):
            encoding = None if self.encoding == "auto-detect" else self.encoding
            self._parser_instance = SecureCSVParser(encoding=encoding, delimiter=self.csv_delimiter)
        return self._parser_instance

    @property
    def _validator(self) -> ProcuriosMandateValidator:
        if not hasattr(self, "_validator_instance"):
            self._validator_instance = ProcuriosMandateValidator()
        return self._validator_instance

    def validate(self):
        if not self.import_date:
            self.import_date = today()

    # ---- validate / preview -------------------------------------------

    def _read_csv_file(self) -> List[Dict]:
        return self._parser.read_csv_file(self.csv_file)

    def _validate_and_preview_csv(self) -> None:
```

with:
```python
class ProcuriosMandateImport(BaseCSVImport):
    _BACKGROUND_METHOD = (
        "verenigingen.verenigingen_payments.doctype.procurios_mandate_import."
        "procurios_mandate_import.process_import_background"
    )

    @property
    def _validator(self) -> ProcuriosMandateValidator:
        # Cache slot is `_validator_instance` (single underscore) to match
        # the BaseCSVImport name-mangling-safe pattern. See base class
        # docstring + TestPropertyCacheHits.
        if not hasattr(self, "_validator_instance"):
            self._validator_instance = ProcuriosMandateValidator()
        return self._validator_instance

    # ---- validate / preview -------------------------------------------

    def _validate_and_preview_csv(self) -> None:
```

**C.** Use `format_truncated_error_log` inside `_validate_and_preview_csv` and `_finalize_import_results`.

In `_validate_and_preview_csv`, replace:
```python
            if errors:
                truncated = "\n".join(errors[:50])
                if len(errors) > 50:
                    truncated += f"\n... and {len(errors) - 50} more errors"
                self.db_set("error_log", truncated)
```
with:
```python
            if errors:
                self.db_set("error_log", format_truncated_error_log(errors))
```

In `_finalize_import_results`, replace:
```python
        if error_log:
            truncated = error_log[:50]
            self.error_log = "\n".join(truncated)
            if len(error_log) > 50:
                self.error_log += f"\n... and {len(error_log) - 50} more errors"
```
with:
```python
        if error_log:
            self.error_log = format_truncated_error_log(error_log)
```

**D.** Drop the now-redundant `on_submit` method (the base class does it). Verify by reading the surrounding code.

**E.** Drop the local `_ADMIN_ROLES = ["System Manager", "Verenigingen Administrator"]` constant — replaced by the imported `ADMIN_ROLES`.

**F.** Refactor `validate_import_file` to one-line delegation:

Replace:
```python
@frappe.whitelist()
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation (called from the client script)."""
    frappe.only_for(_ADMIN_ROLES, message=True)
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
with:
```python
@frappe.whitelist()
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation (called from the client script)."""
    return run_csv_validation("Procurios Mandate Import", import_doc_name)
```

**G.** Refactor `process_import_background` to use `prepare_background_import` for the prologue and `mark_import_failed` for the inner failure paths. Keep the rest of the body (mandate-specific cache building + processor invocation) verbatim.

Replace the prologue:
```python
@frappe.whitelist()
def process_import_background(import_doc_name: str, test_mode=False):
    """Background job: validate, build caches, process, finalize."""
    import traceback

    from verenigingen.utils.csv_import_processor import (
        CSVImportBackgroundProcessor,
        coerce_test_mode,
    )

    # Enqueued context: session.user is the original caller, who must be admin.
    frappe.only_for(_ADMIN_ROLES, message=True)
    test_mode = coerce_test_mode(test_mode)

    frappe.flags.in_background_job = True
    frappe.flags.ignore_version_changes = True

    doc = frappe.get_doc("Procurios Mandate Import", import_doc_name)
    try:
```
with:
```python
@frappe.whitelist()
def process_import_background(import_doc_name: str, test_mode=False):
    """Background job: validate, build caches, process, finalize."""
    import traceback

    from verenigingen.utils.csv_import_processor import CSVImportBackgroundProcessor

    doc, test_mode = prepare_background_import(
        "Procurios Mandate Import", import_doc_name, test_mode
    )
    try:
```

Replace the three inner "Failed" paths to use `mark_import_failed` where the path is a plain "set failed + set log + commit" sequence. Specifically:

Replace (missing-columns path):
```python
        if missing:
            doc.db_set("import_status", "Failed")
            doc.db_set("error_log", "Missing required columns: " + ", ".join(missing))
            frappe.db.commit()
            return
```
with:
```python
        if missing:
            mark_import_failed(doc, "Missing required columns: " + ", ".join(missing))
            return
```

Replace (genuinely-empty path inside the `if not mapped:` block):
```python
            doc.db_set("import_status", "Failed")
            doc.db_set(
                "error_log",
                "\n".join(validator_errors[:50]) if validator_errors else "No valid rows to import",
            )
            frappe.db.commit()
            return
```
with:
```python
            mark_import_failed(
                doc,
                format_truncated_error_log(validator_errors) if validator_errors else "No valid rows to import",
            )
            return
```

Replace the catastrophic except-block:
```python
    except Exception:
        doc.reload()
        doc.db_set("import_status", "Failed")
        doc.db_set("error_log", sanitize_error_for_audit(traceback.format_exc()))
        frappe.db.commit()
    finally:
        frappe.flags.in_background_job = False
        frappe.flags.ignore_version_changes = False
```
with:
```python
    except Exception:
        mark_import_failed(doc, traceback.format_exc())
    finally:
        frappe.flags.in_background_job = False
        frappe.flags.ignore_version_changes = False
```

Leave the `_validate_and_preview_csv` interior try/except handling alone — its early-return for "CSV file is empty" sets a fixed message and then commits, which is fine to keep verbatim (it doesn't call `sanitize_error_for_audit` on a user-controlled string, so there's nothing to consolidate cleanly). Or replace it for consistency:

Replace (in `_validate_and_preview_csv`):
```python
            csv_data = self._read_csv_file()
            if not csv_data:
                self.db_set("import_status", "Failed")
                self.db_set("error_log", "CSV file is empty or could not be read")
                frappe.db.commit()
                return
```
with:
```python
            csv_data = self._read_csv_file()
            if not csv_data:
                mark_import_failed(self, "CSV file is empty or could not be read")
                return
```
And similarly for the missing-columns block within `_validate_and_preview_csv` and the final empty-mapped catch.

Note `_validate_and_preview_csv` ends with `raise` inside the outer `except Exception as e:` — keep that semantics so the helper preserves the raise-after-marking-Failed contract. Replace:
```python
        except Exception as e:
            self.db_set("import_status", "Failed")
            self.db_set("error_log", sanitize_error_for_audit(str(e)))
            frappe.db.commit()
            raise
```
with:
```python
        except Exception as e:
            mark_import_failed(self, str(e))
            raise
```

(`mark_import_failed` already sanitizes, so we just pass `str(e)`.)

- [ ] **Step 2: Run the mandate test suite to verify zero regression**

Run:
```bash
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_procurios_mandate_import 2>&1 | tail -30
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_procurios_mandate_validator 2>&1 | tail -10
```

Expected: same OK count as the Task 1 baseline. `TestPropertyCacheHits` MUST pass — it asserts the property-cache idiom didn't regress through inheritance. If anything fails, read the failure carefully:

- "AttributeError: 'ProcuriosMandateImport' object has no attribute 'csv_delimiter'" → the base `_parser` uses `getattr(self, "csv_delimiter", None)` which should fall through fine. Verify the field exists in the doctype JSON.
- "TypeError: object is not iterable" in `_finalize_import_results` → check the `format_truncated_error_log` swap didn't drop the `if error_log:` guard.
- `frappe.PermissionError` in tests using `set_user("Guest")` → expected.

- [ ] **Step 3: Also check the Error Log table for silent fails**

Per project feedback memory, `bench run-tests` doesn't surface enqueued/logged errors:
```bash
bench --site veg11.veganisme.org execute frappe.client.get_list \
  --kwargs '{"doctype":"Error Log","filters":[["creation",">",frappe.utils.add_to_date(frappe.utils.now(), minutes=-15)]],"fields":["error","method","creation"],"limit_page_length":50}' \
  2>&1 | tail -50
```

Expected: no new errors mentioning `procurios_mandate_import` or `base_csv_import`. (Pre-existing unrelated entries are fine.)

- [ ] **Step 4: Commit**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py
git commit -m "refactor(csv): migrate procurios_mandate_import to BaseCSVImport

- ProcuriosMandateImport now inherits BaseCSVImport
- _parser, validate, _read_csv_file, on_submit moved to base
- validate_import_file delegates to run_csv_validation
- process_import_background uses prepare_background_import +
  mark_import_failed for the prologue + failure paths
- error_log truncation uses format_truncated_error_log

Existing test suite (incl. TestPropertyCacheHits) passes unchanged."
```

---

## Task 4: Migrate `procurios_csv_import.py`

**Files:**
- Modify: `verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py`
- Test (no change): `verenigingen/tests/member/test_procurios_csv_import.py`

Same shape as Task 3. The sibling has one extra wrinkle: it sets `frappe.flags.bulk_member_operations = True` in its `process_import_background` and uses the `bulk_member_operations(import_doc_name)` context manager. This flag is sibling-specific (the mandate importer never sets it) and stays in the subclass — `prepare_background_import` deliberately does NOT touch it.

- [ ] **Step 1: Edit the controller to inherit and remove duplicated members**

**A.** Imports — drop `today`, `Document`, `SecureCSVParser`; add `BaseCSVImport` + helpers; keep `bulk_member_operations`, `ensure_bulk_import_members_set` (still used by the sibling).

Replace:
```python
import json
import traceback
from typing import Dict, List, Tuple

import frappe
from frappe.model.document import Document
from frappe.utils import today

from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator
from verenigingen.utils.csv.secure_csv_parser import SecureCSVParser
from verenigingen.utils.csv_import_processor import (
    CSVImportBackgroundProcessor,
    bulk_member_operations,
    ensure_bulk_import_members_set,
)
from verenigingen.utils.error_handling import sanitize_error_for_audit
```

with:
```python
import json
import traceback
from typing import Dict, List, Tuple

import frappe

from verenigingen.utils.csv.base_csv_import import (
    BaseCSVImport,
    format_truncated_error_log,
    mark_import_failed,
    prepare_background_import,
    run_csv_validation,
)
from verenigingen.utils.csv.procurios_data_validator import ProcuriosDataValidator
from verenigingen.utils.csv_import_processor import (
    CSVImportBackgroundProcessor,
    bulk_member_operations,
    ensure_bulk_import_members_set,
)
from verenigingen.utils.error_handling import sanitize_error_for_audit
```

**B.** Class declaration and shared methods.

Replace:
```python
class ProcuriosCSVImport(Document):
    # Cache slots: single underscore so Python name-mangling doesn't break
    # the hasattr-then-set idiom. `self.__validator = ...` mangles to
    # `_ProcuriosCSVImport__validator`, but `hasattr(self, "__validator")`
    # checks the unmangled string — perpetually False, defeating the cache.
    @property
    def _validator(self) -> ProcuriosDataValidator:
        if not hasattr(self, "_validator_instance"):
            self._validator_instance = ProcuriosDataValidator(
                import_gender=bool(self.import_gender),
            )
        return self._validator_instance

    @property
    def _parser(self) -> SecureCSVParser:
        if not hasattr(self, "_parser_instance"):
            encoding = None if self.encoding == "auto-detect" else self.encoding
            self._parser_instance = SecureCSVParser(encoding=encoding, delimiter=self.csv_delimiter)
        return self._parser_instance

    def validate(self):
        if not self.import_date:
            self.import_date = today()

    def on_submit(self):
        self.db_set("import_status", "Queued")
        frappe.enqueue(
            method="verenigingen.verenigingen.doctype.procurios_csv_import.procurios_csv_import.process_import_background",
            queue="long",
            timeout=3600,
            import_doc_name=self.name,
            test_mode=self.test_mode,
            now=False,
        )

    def _read_csv_file(self) -> List[Dict]:
        return self._parser.read_csv_file(self.csv_file)
```

with:
```python
class ProcuriosCSVImport(BaseCSVImport):
    _BACKGROUND_METHOD = (
        "verenigingen.verenigingen.doctype.procurios_csv_import."
        "procurios_csv_import.process_import_background"
    )

    @property
    def _validator(self) -> ProcuriosDataValidator:
        # Cache slot is `_validator_instance` (single underscore) to match
        # the BaseCSVImport name-mangling-safe pattern. See base class
        # docstring + TestProcuriosCSVImportPropertyCache.
        if not hasattr(self, "_validator_instance"):
            self._validator_instance = ProcuriosDataValidator(
                import_gender=bool(self.import_gender),
            )
        return self._validator_instance
```

Note: this fixes a latent inconsistency the handoff identified — the sibling's old `on_submit` passed `test_mode=self.test_mode` (uncoerced); the base `on_submit` passes `bool(self.test_mode)`. The downstream `coerce_test_mode` already handled this, so behaviour is unchanged but the contract is now uniform.

**C.** Use `format_truncated_error_log` in `_validate_and_preview_csv` and `_finalize_import_results`.

In `_validate_and_preview_csv`, replace:
```python
            if errors:
                self.db_set("error_log", "\n".join(errors[:50]))
```
with:
```python
            if errors:
                self.db_set("error_log", format_truncated_error_log(errors))
```

In `_finalize_import_results`, replace:
```python
        if error_log:
            truncated = error_log[:50]
            self.error_log = "\n".join(truncated)
            if len(error_log) > 50:
                self.error_log += f"\n... and {len(error_log) - 50} more errors"
```
with:
```python
        if error_log:
            self.error_log = format_truncated_error_log(error_log)
```

In the failure paths within `_validate_and_preview_csv` (CSV-empty + outer except), use `mark_import_failed`:

Replace:
```python
            csv_data = self._read_csv_file()
            if not csv_data:
                self.db_set("import_status", "Failed")
                self.db_set("error_log", "CSV file is empty or could not be read")
                frappe.db.commit()
                return
```
with:
```python
            csv_data = self._read_csv_file()
            if not csv_data:
                mark_import_failed(self, "CSV file is empty or could not be read")
                return
```

Replace the outer except:
```python
        except Exception as e:
            self.db_set("import_status", "Failed")
            self.db_set("error_log", sanitize_error_for_audit(str(e)))
            frappe.db.commit()
            raise
```
with:
```python
        except Exception as e:
            mark_import_failed(self, str(e))
            raise
```

**D.** Drop the local `_ADMIN_ROLES = [...]` constant.

**E.** Refactor `validate_import_file`:

Replace:
```python
@frappe.whitelist()
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation."""
    frappe.only_for(_ADMIN_ROLES, message=True)
    doc = frappe.get_doc("Procurios CSV Import", import_doc_name)
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
with:
```python
@frappe.whitelist()
def validate_import_file(import_doc_name: str) -> dict:
    """Manually trigger CSV validation."""
    return run_csv_validation("Procurios CSV Import", import_doc_name)
```

**F.** Refactor `process_import_background`. KEEP the `bulk_member_operations` flag set + the `with bulk_member_operations(import_doc_name):` block — those are sibling-specific. Use `prepare_background_import` for the only_for + test_mode + base flags + get_doc, then ADD the sibling-specific `bulk_member_operations` flag after.

Replace:
```python
@frappe.whitelist()
def process_import_background(import_doc_name: str, test_mode=False):
    """Background job: process the validated CSV and create members."""
    from verenigingen.utils.csv_import_processor import coerce_test_mode

    # only_for must run BEFORE any flag-setting side effects, so an
    # unauthorised caller can't flip frappe.flags.bulk_member_operations
    # for their own session before the exception is raised.
    frappe.only_for(_ADMIN_ROLES, message=True)

    # REST callers pass strings; without coercion `"false"` is truthy.
    test_mode = coerce_test_mode(test_mode)

    frappe.flags.in_background_job = True
    frappe.flags.bulk_member_operations = True
    frappe.flags.ignore_version_changes = True

    doc = frappe.get_doc("Procurios CSV Import", import_doc_name)

    try:
```
with:
```python
@frappe.whitelist()
def process_import_background(import_doc_name: str, test_mode=False):
    """Background job: process the validated CSV and create members."""
    doc, test_mode = prepare_background_import(
        "Procurios CSV Import", import_doc_name, test_mode
    )
    # Sibling-specific flag (the mandate importer does NOT set this).
    # Authorisation is already enforced by prepare_background_import.
    frappe.flags.bulk_member_operations = True

    try:
```

Replace the inner Failed-path:
```python
        if not mapped_data:
            doc.db_set("import_status", "Failed")
            doc.db_set("error_log", "No valid rows to import")
            frappe.db.commit()
            return
```
with:
```python
        if not mapped_data:
            mark_import_failed(doc, "No valid rows to import")
            return
```

Replace the outer except:
```python
    except Exception:
        doc.reload()
        doc.db_set("import_status", "Failed")
        doc.db_set("error_log", sanitize_error_for_audit(traceback.format_exc()))
        frappe.db.commit()

    finally:
        frappe.flags.in_background_job = False
        frappe.flags.bulk_member_operations = False
        frappe.flags.ignore_version_changes = False
```
with:
```python
    except Exception:
        mark_import_failed(doc, traceback.format_exc())

    finally:
        frappe.flags.in_background_job = False
        frappe.flags.bulk_member_operations = False
        frappe.flags.ignore_version_changes = False
```

- [ ] **Step 2: Run the sibling test suite to verify zero regression**

Run:
```bash
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.member.test_procurios_csv_import 2>&1 | tail -30
```

Expected: same OK count as the Task 1 baseline. `TestProcuriosCSVImportPropertyCache` MUST pass.

- [ ] **Step 3: Check Error Log for silent failures**

```bash
bench --site veg11.veganisme.org execute frappe.client.get_list \
  --kwargs '{"doctype":"Error Log","filters":[["creation",">",frappe.utils.add_to_date(frappe.utils.now(), minutes=-15)]],"fields":["error","method"],"limit_page_length":50}' \
  2>&1 | tail -50
```

Expected: no new errors mentioning `procurios_csv_import` or `base_csv_import`.

- [ ] **Step 4: Commit**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py
git commit -m "refactor(csv): migrate procurios_csv_import to BaseCSVImport

Sibling controller now inherits BaseCSVImport identically to the
mandate importer. The sibling-specific bulk_member_operations flag
and context manager are kept in the subclass — only the base flags
(in_background_job, ignore_version_changes) move to the helper.

Latent contract drift fixed: the old on_submit passed
test_mode=self.test_mode (uncoerced); the base on_submit passes
bool(self.test_mode). Behaviourally identical because the receiver
already coerces."
```

---

## Task 5: Add the gotcha-note to `mijnrood_csv_import.py`

**Files:**
- Modify: `verenigingen/verenigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py`

Per handoff §8: a short comment in mijnrood_csv_import.py referencing the gotcha would prevent a confused future revert. Mijnrood uses the explicit-mangled-name idiom (`self._MijnroodCSVImport__validator`) — a DIFFERENT pattern from the two now-fixed Procurios importers. Someone "cleaning up" might assume mijnrood is broken and "fix" it back to the bug. This comment heads that off.

- [ ] **Step 1: Add the explanatory header comment**

Insert at the top of the `class MijnroodCSVImport(Document):` body, just above the `# Lazy-initialized instances...` comment that's already there:

Replace:
```python
class MijnroodCSVImport(Document):
    """DocType for importing member data from CSV files with validation and preview."""

    # Lazy-initialized instances to avoid repeated instantiation
    @property
    def _validator(self):
        """Lazy-initialized CSVDataValidator instance."""
        if not hasattr(self, "_MijnroodCSVImport__validator"):
            self.__validator = CSVDataValidator()
        return self.__validator
```
with:
```python
class MijnroodCSVImport(Document):
    """DocType for importing member data from CSV files with validation and preview.

    Why this class does NOT inherit from BaseCSVImport:

    1. The property-cache idiom here uses the explicit-mangled-name form
       (`hasattr(self, "_MijnroodCSVImport__validator")` + `self.__validator = ...`).
       The two Procurios importers use the single-underscore form
       (`hasattr(self, "_validator_instance")` + `self._validator_instance = ...`)
       via BaseCSVImport. Both are correct; they are NOT interchangeable
       because the mangled form embeds this class's name. Do not
       "clean up" the underscores here — switching to the BaseCSVImport
       form would silently break the cache the moment a subclass appears.

    2. This controller is ~2000 LOC of domain orchestration (Account
       Creation Requests, Bulk Volunteer Service, Mollie sync, chapter
       provisioning, atomic tracker linking). A shared base class buys
       little and would have to host carve-outs for every one of those
       concerns.

    See `verenigingen/utils/csv/base_csv_import.py` for the shared
    scaffolding used by the Procurios importers.
    """

    # Lazy-initialized instances to avoid repeated instantiation
    @property
    def _validator(self):
        """Lazy-initialized CSVDataValidator instance."""
        if not hasattr(self, "_MijnroodCSVImport__validator"):
            self.__validator = CSVDataValidator()
        return self.__validator
```

- [ ] **Step 2: Run the mijnrood smoke test (if any) to confirm zero impact**

The handoff notes the mijnrood importer doesn't have its own end-to-end integration test in this repo (test gap from §8). A docstring change can't break anything, but verify by reloading the doctype:

```bash
cd ~/frappe-bench
bench --site veg11.veganisme.org reload-doctype "Mijnrood CSV Import" 2>&1 | tail -5
bench --site veg11.veganisme.org execute \
  "verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import.MijnroodCSVImport" \
  2>&1 | tail -5
```

Expected: doctype reloads cleanly; importing the class symbol works (no syntax error, no import error from the docstring change).

- [ ] **Step 3: Commit**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/verenigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py
git commit -m "docs(csv): note why mijnrood_csv_import does NOT inherit BaseCSVImport

Heads off a confused future 'cleanup' that would replace the
mangled-name property cache idiom with the BaseCSVImport
single-underscore form. The two patterns are NOT interchangeable;
the mangled form embeds the class name and silently breaks the
moment a subclass appears.

Per docs/plans/2026-06-03-procurios-mandate-import-handoff.md §8."
```

---

## Task 6: Final integration + pre-commit + push

**Files:** none (verification only)

- [ ] **Step 1: Run all three affected test suites together**

```bash
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_procurios_mandate_validator 2>&1 | tail -10
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_procurios_mandate_import 2>&1 | tail -30
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.member.test_procurios_csv_import 2>&1 | tail -30
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.utils.csv.test_base_csv_import 2>&1 | tail -10
```

Expected: each report shows the same OK count as the Task 1 baseline plus the new base-class tests. No new failures.

- [ ] **Step 2: Run pre-commit on the touched files**

```bash
cd ~/frappe-bench/apps/verenigingen
SKIP=whitelist-type-safety,jest-testing pre-commit run --files \
  verenigingen/utils/csv/base_csv_import.py \
  verenigingen/tests/utils/csv/test_base_csv_import.py \
  verenigingen/verenigingen_payments/doctype/procurios_mandate_import/procurios_mandate_import.py \
  verenigingen/verenigingen/doctype/procurios_csv_import/procurios_csv_import.py \
  verenigingen/verenigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py \
  2>&1 | tail -40
```

Expected: all hooks pass (or report pre-existing failures already in the memory `SKIP` list — those don't block the refactor). If `ast-field-analyzer` or `doctype-field-validator` flags something on the modified controllers, that's a real signal — investigate.

- [ ] **Step 3: View the cumulative diff one more time**

```bash
cd ~/frappe-bench/apps/verenigingen
git log --oneline develop..HEAD
git diff develop --stat
```

Expected stats:
- `base_csv_import.py` created (~150 LOC)
- `test_base_csv_import.py` created (~150 LOC)
- `procurios_mandate_import.py` net reduction (~50 LOC)
- `procurios_csv_import.py` net reduction (~60 LOC)
- `mijnrood_csv_import.py` net addition (~20 LOC docstring)

Net LOC: roughly break-even, but duplication eliminated and a third importer becomes a trivial addition.

- [ ] **Step 4: Push and open the PR**

```bash
cd ~/frappe-bench/apps/verenigingen
git push -u origin refactor/base-csv-import-extraction
gh pr create --base develop --title "refactor(csv): extract BaseCSVImport for the two Procurios importers" \
  --body "$(cat <<'EOF'
Extracts ~120 LOC of structural duplication between
`procurios_mandate_import.py` and `procurios_csv_import.py` into a
shared `BaseCSVImport(Document)` class and a small set of
module-level helpers in `verenigingen/utils/csv/base_csv_import.py`.

Per `docs/plans/2026-06-03-procurios-mandate-import-handoff.md` §8 (TD-3).
Detailed plan: `docs/plans/2026-06-03-base-csv-import-extraction.md`.

**Out of scope:**
- `mijnrood_csv_import.py` — different name-mangling pattern + heavy
  domain orchestration. Receives a header docstring instead, per §8.
- `csv_import_processor.py` (`CSVImportBackgroundProcessor`,
  `bulk_member_operations`, `progress_field_map`) — unchanged.

**Tests:**
- All existing tests pass unchanged (incl. `TestPropertyCacheHits`
  and `TestProcuriosCSVImportPropertyCache` — the regression guards
  for the name-mangling fix).
- New focused tests for the module-level helpers in
  `tests/utils/csv/test_base_csv_import.py`.

Run locally:
\`\`\`
bench --site veg11.veganisme.org run-tests --app verenigingen \\
  --module verenigingen.tests.payment.test_procurios_mandate_import
bench --site veg11.veganisme.org run-tests --app verenigingen \\
  --module verenigingen.tests.member.test_procurios_csv_import
bench --site veg11.veganisme.org run-tests --app verenigingen \\
  --module verenigingen.tests.utils.csv.test_base_csv_import
\`\`\`
EOF
)"
```

- [ ] **Step 5: Auto-dispatch reviewers (per project convention)**

The project's memory says: "Always request agent review on PRs — auto-dispatch reviewers when opening any PR." Two parallel reviews land richer findings than one:

```
(In the main session, dispatch via Agent tool:)
- code-quality-reviewer: review the changes in this PR for code quality, DRY, and architectural fit
- skeptical-code-reviewer: review the changes in this PR for tech debt, hidden regressions, and test coverage gaps
```

Address any Important / High findings before requesting merge.

---

## Self-review

Spec coverage (handoff §8 TD-3 items):
- `_parser`/`_validator` properties → BaseCSVImport hosts `_parser`; `_validator` stays subclass-specific because the types differ. ✓
- `on_submit` enqueue → `BaseCSVImport.on_submit` + `_BACKGROUND_METHOD` class attribute. ✓
- `_read_csv_file` → BaseCSVImport. ✓
- whitelisted `validate_import_file` wrapper → `run_csv_validation` helper; each concrete `validate_import_file` is one line. ✓
- `process_import_background` outer structure → `prepare_background_import` + `mark_import_failed`. ✓
- finalize skeleton → `format_truncated_error_log` covers the error-log truncation; the rest of finalize stays per-subclass because the field-name and metadata differences are real. ✓ (cleanest cut)
- mijnrood gotcha-note → Task 5. ✓

Placeholder scan: no "TBD", "implement later", "similar to Task N", or unsourced types. Every replace-this-with-that step shows both sides verbatim.

Type consistency: `_BACKGROUND_METHOD` (string class attribute), `_parser_instance` / `_validator_instance` (single underscore), `ADMIN_ROLES` (list of strings), `prepare_background_import` returns `(Document, bool)`, `format_truncated_error_log` returns `str`, `mark_import_failed` returns `None`, `run_csv_validation` returns `dict`. Consistent across tasks 2–4.
