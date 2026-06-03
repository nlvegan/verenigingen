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


class TestMarkImportFailed(EnhancedTestCase):
    """mark_import_failed: reload + Failed status + sanitized error_log + commit."""

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
