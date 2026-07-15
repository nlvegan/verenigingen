# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Shared scaffolding for Procurios CSV importers.

Two DocType controllers share ~120 LOC of structural boilerplate
(`procurios_mandate_import.py` and `member_import.py`). This
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

from typing import List, Tuple

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


def prepare_background_import(doctype: str, import_doc_name: str, test_mode) -> Tuple[Document, bool]:
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

    Caller contract: this helper SETS `frappe.flags.in_background_job`
    and `frappe.flags.ignore_version_changes` but does NOT clean them
    up. Callers MUST reset both in a `finally` block — the two
    existing Procurios `process_import_background` functions both
    do this. If `frappe.get_doc` raises (e.g. `DoesNotExistError` on
    a stale `import_doc_name`), the exception propagates with the
    flags still set; the caller's `finally` block handles cleanup.
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

    Caller contracts (footguns to be aware of):

    1. The `reload()` discards any unsaved in-memory state. Callers must
       persist via `db_set(...)` INSIDE the try-block — a plain
       `self.some_field = computed_value` written before an exception
       fires will be silently wiped here. The two existing Procurios
       controllers obey this; every Failed-path field write in
       `_validate_and_preview_csv` and `process_import_background` uses
       `db_set`.
    2. The `commit()` flushes ANY pending uncommitted writes from this
       request, not just the Failed status + error_log. If the
       try-block did `db_set("preview_data", ...)` and
       `db_set("total_rows", ...)` before the exception, those land in
       the DB alongside the Failed state. This matches the pre-refactor
       behaviour but is easier to overlook now that the helper hides
       the commit.

    A Failed import doc without any error_log is always a debugging
    hole — `sanitize_error_for_audit("")` returns `None`, so naive
    callers that pass `str(some_empty_exception)` would silently write
    SQL NULL. We always write SOMETHING here.
    """
    doc.reload()
    sanitized = sanitize_error_for_audit(error_message) or "Unknown error (no diagnostic available)"
    doc.db_set("import_status", "Failed")
    doc.db_set("error_log", sanitized)
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
    `TestMemberImportPropertyCache` are explicit regression
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

    def before_submit(self) -> None:
        """Validate the subclass contract BEFORE Frappe writes docstatus=1.

        Frappe's submit lifecycle is: validate → before_submit → write
        docstatus=1 → on_submit. Putting the misconfiguration guard here
        (rather than in on_submit) means a subclass that forgets
        `_BACKGROUND_METHOD` fails out cleanly with docstatus still 0 —
        no half-submitted doc, no enqueue attempt with a None method.

        The strip-check catches both missing and whitespace-only values.
        The message is developer-facing (programming bug, not a user
        error) so no `frappe._()` wrapping.

        Known bypass: `flags.ignore_validate = True` short-circuits
        `run_before_save_methods` in Frappe (frappe/model/document.py),
        skipping both `validate` AND `before_submit`. No production code
        sets this flag on either Procurios importer today, but if a
        future caller does, `on_submit`'s `self._BACKGROUND_METHOD`
        access would raise `AttributeError` instead of this clear
        ValidationError. Not a silent stall — just a less-helpful error.
        """
        method = getattr(self, "_BACKGROUND_METHOD", None)
        if not method or not method.strip():
            frappe.throw("Subclasses of BaseCSVImport must define _BACKGROUND_METHOD")

    def on_submit(self) -> None:
        """Enqueue the subclass-specific background job.

        Subclasses MUST set `_BACKGROUND_METHOD` to their module-level
        `process_import_background`'s dotted path. test_mode is coerced
        to bool here so the enqueued args are unambiguous; the receiver
        re-coerces defensively via `coerce_test_mode`.

        Misconfiguration is caught earlier in `before_submit`; reaching
        this method means `_BACKGROUND_METHOD` is well-formed.
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
