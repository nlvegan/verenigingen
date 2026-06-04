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

        original_user = frappe.session.user
        try:
            frappe.set_user("Guest")
            with self.assertRaisesRegex(frappe.PermissionError, "only allowed"):
                run_csv_validation("Procurios Mandate Import", "PMI-NON-EXISTENT")
        finally:
            frappe.set_user(original_user)

    def test_admin_caller_passes_only_for_then_get_doc_raises(self):
        from verenigingen.utils.csv.base_csv_import import run_csv_validation

        # As Administrator, only_for passes; get_doc on a non-existent name
        # raises DoesNotExistError. The helper deliberately does NOT catch
        # this (mirroring the existing controller behaviour) — the try/except
        # only wraps the _validate_and_preview_csv delegate call, so missing
        # docs surface as a real Frappe error rather than a generic
        # status=error dict that would hide the cause from logs.
        with self.assertRaises(frappe.DoesNotExistError):
            run_csv_validation("Procurios Mandate Import", "PMI-DOES-NOT-EXIST")

    def test_ready_for_import_status_returns_success(self):
        # Regression guard: a future rename of the "Ready for Import" status
        # string would silently turn every successful validation into
        # status="error" without any test catching it. Mock the delegate
        # to isolate the helper's return-shape contract.
        # Mock justified: testing the helper's status-string comparison
        # without a real CSV file fixture.
        from verenigingen.utils.csv.base_csv_import import run_csv_validation

        stub = MagicMock()
        stub._validate_and_preview_csv = MagicMock()
        stub.reload = MagicMock()
        stub.import_status = "Ready for Import"
        with patch.object(frappe, "get_doc", return_value=stub):
            result = run_csv_validation("Procurios Mandate Import", "PMI-X")
        self.assertEqual(result["status"], "success")
        self.assertIn("Ready for Import", result["message"])


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
        original_user = frappe.session.user
        try:
            frappe.set_user("Guest")
            with self.assertRaisesRegex(frappe.PermissionError, "only allowed"):
                prepare_background_import(
                    "Procurios Mandate Import", "PMI-X", False
                )
        finally:
            frappe.set_user(original_user)
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

    def test_happy_path_sets_both_base_flags(self):
        # Regression guard: a future change deleting either
        # `frappe.flags.in_background_job = True` or
        # `frappe.flags.ignore_version_changes = True` from the helper would
        # silently break both Procurios importers. This test pins the
        # contract that BOTH flags get set on the admin-success path.
        # Mock justified: avoids needing a real import doc to test pure
        # flag side-effects.
        from verenigingen.utils.csv.base_csv_import import prepare_background_import

        frappe.flags.in_background_job = False
        frappe.flags.ignore_version_changes = False
        try:
            with patch.object(frappe, "get_doc") as mocked:
                mocked.return_value = MagicMock(name="ProcuriosMandateImport")
                prepare_background_import("Procurios Mandate Import", "PMI-X", False)
            self.assertTrue(frappe.flags.in_background_job)
            self.assertTrue(frappe.flags.ignore_version_changes)
        finally:
            frappe.flags.in_background_job = False
            frappe.flags.ignore_version_changes = False


class TestBeforeSubmitBackgroundMethodGuard(unittest.TestCase):
    """BaseCSVImport.before_submit raises when _BACKGROUND_METHOD missing.

    Future-proofing guard: a hypothetical third subclass that forgets to set
    `_BACKGROUND_METHOD` would otherwise reach the on_submit enqueue with
    a None method. Frappe's submit lifecycle runs `before_submit` BEFORE
    writing docstatus=1, so this guard rejects the submit cleanly — the
    doc stays in Draft (docstatus=0), no half-submitted state, no enqueue
    attempt.
    """

    def test_missing_attribute_throws(self):
        # Mock justified: testing the guard in isolation; constructing a
        # real misconfigured Document subclass and instantiating it would
        # require registering a fake DocType.
        from verenigingen.utils.csv.base_csv_import import BaseCSVImport

        class FakeSelf:
            pass

        fake_self = FakeSelf()
        with self.assertRaises(frappe.ValidationError):
            BaseCSVImport.before_submit(fake_self)

    def test_whitespace_only_attribute_throws(self):
        # The strip-check catches accidental whitespace-only values too —
        # a developer typing `_BACKGROUND_METHOD = "   "` would have passed
        # `if not method:` alone.
        from verenigingen.utils.csv.base_csv_import import BaseCSVImport

        class FakeSelf:
            _BACKGROUND_METHOD = "   "

        with self.assertRaises(frappe.ValidationError):
            BaseCSVImport.before_submit(FakeSelf())


class TestBeforeSubmitGuardIntegration(EnhancedTestCase):
    """Confirm the guard fires INSIDE Frappe's real submit lifecycle.

    The unit tests above use a FakeSelf; they verify the method body but
    don't exercise the submit machinery (validate → before_submit → write
    docstatus → on_submit). This integration test temporarily monkey-patches
    `_BACKGROUND_METHOD` on a real Procurios Mandate Import to simulate a
    misconfigured subclass, then attempts `doc.submit()` and asserts that
    docstatus stays at 0 — proving the guard fired BEFORE Frappe's
    docstatus write.
    """

    def test_guard_prevents_docstatus_write(self):
        from verenigingen.verenigingen_payments.doctype.procurios_mandate_import.procurios_mandate_import import (
            ProcuriosMandateImport,
        )

        original_method = ProcuriosMandateImport._BACKGROUND_METHOD
        ProcuriosMandateImport._BACKGROUND_METHOD = ""
        doc = None
        try:
            doc = frappe.get_doc(
                {
                    "doctype": "Procurios Mandate Import",
                    "import_date": frappe.utils.today(),
                    "encoding": "auto-detect",
                    "csv_delimiter": "Semicolon",
                }
            )
            doc.flags.ignore_permissions = True
            doc.flags.ignore_mandatory = True
            doc.insert()

            # Attempting to submit MUST raise because before_submit's guard
            # rejects the misconfigured class.
            with self.assertRaises(frappe.ValidationError):
                doc.submit()

            # Critical: reload from DB and confirm docstatus is still 0
            # (Draft). If the guard had fired in on_submit instead, the
            # docstatus would already be 1 by the time of the throw.
            doc.reload()
            self.assertEqual(doc.docstatus, 0)
        finally:
            ProcuriosMandateImport._BACKGROUND_METHOD = original_method
            if doc is not None:
                frappe.delete_doc(
                    "Procurios Mandate Import",
                    doc.name,
                    force=1,
                    ignore_permissions=True,
                )


class TestMarkImportFailed(EnhancedTestCase):
    """mark_import_failed: reload + Failed status + sanitized error_log + commit."""

    def _make_doc(self):
        """Build a real Procurios Mandate Import in Validating state."""
        doc = frappe.get_doc(
            {
                "doctype": "Procurios Mandate Import",
                "import_date": frappe.utils.today(),
                "encoding": "auto-detect",
                "csv_delimiter": "Semicolon",
                "import_status": "Validating",
            }
        )
        doc.flags.ignore_permissions = True
        doc.flags.ignore_mandatory = True
        doc.insert()
        return doc

    def test_empty_string_writes_fallback_diagnostic_not_null(self):
        # Regression guard for the skeptical reviewer's footgun #3 on PR #123:
        # sanitize_error_for_audit("") returns None, and a naive
        # db_set("error_log", None) would silently write SQL NULL — leaving
        # a Failed import with no diagnostic. The helper now substitutes a
        # fallback string.
        from verenigingen.utils.csv.base_csv_import import mark_import_failed

        doc = self._make_doc()
        try:
            mark_import_failed(doc, "")
            doc.reload()
            self.assertEqual(doc.import_status, "Failed")
            self.assertIsNotNone(doc.error_log)
            self.assertNotEqual((doc.error_log or "").strip(), "")
        finally:
            frappe.delete_doc(
                "Procurios Mandate Import", doc.name, force=1, ignore_permissions=True
            )

    def test_sets_failed_status_and_sanitized_log(self):
        from verenigingen.utils.csv.base_csv_import import mark_import_failed

        # Create a real Procurios Mandate Import in a Validating state.
        # csv_file is reqd so we set ignore_mandatory; csv_delimiter must
        # match the Select options (Comma/Semicolon/Tab), not a literal char.
        doc = frappe.get_doc(
            {
                "doctype": "Procurios Mandate Import",
                "import_date": frappe.utils.today(),
                "encoding": "auto-detect",
                "csv_delimiter": "Semicolon",
                "import_status": "Validating",
            }
        )
        doc.flags.ignore_permissions = True
        doc.flags.ignore_mandatory = True
        doc.insert()
        try:
            mark_import_failed(doc, "boom: something/with/a/path.csv")
            doc.reload()
            self.assertEqual(doc.import_status, "Failed")
            # sanitize_error_for_audit should redact path-like content; we
            # only assert the status was set and the log is non-empty.
            self.assertTrue(doc.error_log)
        finally:
            frappe.delete_doc(
                "Procurios Mandate Import", doc.name, force=1, ignore_permissions=True
            )
