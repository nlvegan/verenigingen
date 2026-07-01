# Copyright (c) 2026, Verenigingen and contributors
# See license.txt
#
# REPORTS / FINALIZATION coverage for the Mijnrood CSV Import controller.
#
# Complements the existing six mijnrood test modules:
#   - test_mijnrood_csv_import.py
#   - test_mijnrood_csv_import_coverage.py
#   - test_mijnrood_csv_import_gapfill.py
#   - test_mijnrood_csv_import_orchestration.py
#   - test_mijnrood_csv_import_orchestration_gaps.py
#   - test_mijnrood_csv_import_pipeline.py
#
# Those drive the import end-to-end through process_import_background(); this
# module exercises the finalization + reporting surfaces DIRECTLY, which lets it
# hit branches the happy-path pipeline does not:
#   - _finalize_import_results(): the full summary-assembly path with REAL Active
#     members but user-account/volunteer creation OFF (the "skipping" else
#     branches), the Mollie "preserved correctly" branch, the validation-warning
#     aggregation + error-log append, the persist-full-error-log branch and the reload/re-apply + itemized-notes
#     tail (lines ~388-539).
#   - _finalize_import_results() with NO processed members: the no-account / no-
#     volunteer / no-mollie short-circuits.
#   - _append_to_error_log(): the no-header truncation branch (line ~1369).
#   - _generate_itemized_member_list(): the updated>100 truncation (line ~1701)
#     and the per-category skipped>20 truncation (line ~1713).
#   - update_import_tracking_after_retry(): the missing-document exception branch
#     (lines ~1928-1933).
#
# Test philosophy: nothing patches frappe.db, the controller, or the extracted
# services. The dues-warning attribute that real imports populate during
# processing (via _record_dues_rate_warning) is seeded as plain in-memory state
# in the exact shape that writer produces, then the REAL finalize code runs and
# we assert the REAL observable effect (persisted import_status / import_summary /
# notes, returned strings, logged Error Logs).

import random

import frappe

from verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import import (
    update_import_tracking_after_retry,
)
from verenigingen.verenigingen.doctype.mijnrood_csv_import.test_mijnrood_csv_import_pipeline import (
    _BaseMijnroodPipelineTest,
)


def _unique_email(prefix="mijnrood_reports"):
    return f"{prefix}_{random.randint(1000000, 9999999)}@integrationtest.invalid"


class TestMijnroodFinalizeResults(_BaseMijnroodPipelineTest):
    """_finalize_import_results(): the full reporting/finalization path."""

    def test_finalize_with_real_member_assembles_full_summary(self):
        """A real Active member with account/volunteer creation OFF drives the
        Mollie 'preserved correctly' branch, validation-warning aggregation +
        error-log append, error-log persistence, and the reload/re-apply +
        itemized-notes tail."""
        member = self._make_member(status="Active")
        doc = self._make_import_doc(
            [{"Voornaam": "Final", "Achternaam": "Member", "E-mailadres": _unique_email()}],
            create_user_accounts=0,
            create_volunteer_records=0,
        )
        # Seed the in-memory dues warning a real import leaves on the doc via
        # _record_dues_rate_warning (exact shape it writes).
        doc._dues_rate_warnings = [
            {"dues_rate": "5.00", "minimum": "10.00", "member": "Lidnr 1 (Final Member)"}
        ]

        # The finalization flag is normally set by _process_import upstream; clear
        # it so we also exercise the "flag was NOT set" re-arming branch.
        frappe.flags.bulk_member_operations = False

        self._finalize(
            doc,
            created_count=1,
            updated_count=0,
            skipped_count=1,
            error_log=["Row 1: some non-fatal note"],
            created_members=[member.name],
            updated_members=[],
            skipped_members=["Lidnr 9: Skipped Person - duplicate entry"],
        )

        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        self.assertIn("Created: 1", doc.import_summary)
        # Mollie validation ran against a member with no customer -> preserved.
        self.assertIn("Mollie data: preserved correctly", doc.import_summary)
        # The seeded dues warning is aggregated into the summary + notes/error log.
        self.assertIn("validation warning", doc.import_summary)
        # Itemized notes list the created + skipped members.
        self.assertIn(member.name, doc.notes)
        self.assertIn("Skipped Members", doc.notes)

    def test_finalize_with_no_processed_members_short_circuits(self):
        """Zero created/updated members skips the account, volunteer and Mollie
        blocks entirely; the import still completes."""
        doc = self._make_import_doc(
            [{"Voornaam": "Empty", "Achternaam": "Final", "E-mailadres": _unique_email()}],
            create_user_accounts=1,  # ON, but no members -> still skipped
            create_volunteer_records=1,
        )
        self._finalize(
            doc,
            created_count=0,
            updated_count=0,
            skipped_count=2,
            error_log=[],
            created_members=[],
            updated_members=[],
            skipped_members=["Lidnr 1: A B - bad email", "Lidnr 2: C D - bad iban"],
        )

        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        self.assertIn("Created: 0", doc.import_summary)
        # No processed members -> no Mollie validation summary fragment.
        self.assertNotIn("Mollie data", doc.import_summary)
        self.assertIn("Skipped Members (2)", doc.notes)

    def _finalize(self, doc, **kwargs):
        """Insertion-light wrapper so the test bodies stay assertion-focused.

        _finalize_import_results persists via reload()+save(); the surrounding
        EnhancedTestCase transaction is rolled back in tearDown and the import
        doc is force-deleted, so nothing leaks.
        """
        doc._finalize_import_results(
            kwargs["created_count"],
            kwargs["updated_count"],
            kwargs["skipped_count"],
            kwargs["error_log"],
            kwargs["created_members"],
            kwargs["updated_members"],
            kwargs["skipped_members"],
        )


class TestMijnroodAppendErrorLogTruncation(_BaseMijnroodPipelineTest):
    """_append_to_error_log() no-header truncation branch (pure, no DB)."""

    def test_truncates_without_header(self):
        """When the existing log has no '===' header and the size cap is hit, the
        log is replaced with a truncation notice + the new message (line ~1369)."""
        doc = self._new_unsaved_doc()
        doc.error_log = "x" * 200  # no '===' header line
        doc._append_to_error_log("brand new entry", max_size=50)
        self.assertIn("earlier entries truncated", doc.error_log)
        self.assertIn("brand new entry", doc.error_log)
        self.assertNotIn("xxxx", doc.error_log)

    def test_truncates_keeping_header(self):
        """An existing '===' header line is preserved across truncation."""
        doc = self._new_unsaved_doc()
        doc.error_log = "=== Import Errors ===\n" + ("y" * 200)
        doc._append_to_error_log("new entry", max_size=60)
        self.assertTrue(doc.error_log.startswith("=== Import Errors ==="))
        self.assertIn("new entry", doc.error_log)


class TestMijnroodItemizedTruncation(_BaseMijnroodPipelineTest):
    """_generate_itemized_member_list() truncation branches (pure, no DB)."""

    def test_updated_members_over_100_are_truncated(self):
        """More than 100 updated members -> '... and N more' (line ~1701)."""
        doc = self._new_unsaved_doc()
        updated = [f"MEM-U-{i:04d}" for i in range(130)]
        out = doc._generate_itemized_member_list(None, updated, None)
        self.assertIn("Updated Members (130)", out)
        self.assertIn("and 30 more", out)

    def test_skip_category_over_20_is_truncated(self):
        """More than 20 members in a single skip category -> '... and N more'
        within that category (line ~1713)."""
        doc = self._new_unsaved_doc()
        # 21 entries that all parse into the 'Duplicate Entry' bucket.
        skipped = [f"Lidnr {100 + i}: Dup Person{i} - duplicate entry found" for i in range(21)]
        out = doc._generate_itemized_member_list(None, None, skipped)
        self.assertIn("Duplicate Entry", out)
        self.assertIn("and 1 more", out)


class TestMijnroodUpdateTrackingAfterRetryFailure(_BaseMijnroodPipelineTest):
    """update_import_tracking_after_retry(): missing-document exception branch."""

    def test_missing_import_document_is_logged_not_raised(self):
        """A non-existent import name makes frappe.get_doc raise; the function
        swallows it, logging an Error Log instead of propagating (lines
        ~1928-1933)."""
        bogus = f"NONEXISTENT-IMPORT-{random.randint(1000000, 9999999)}"
        self.expectErrorLog(f"CSV Import Tracking Update After Retry Error: {bogus}")
        # Must not raise.
        update_import_tracking_after_retry(bogus)
