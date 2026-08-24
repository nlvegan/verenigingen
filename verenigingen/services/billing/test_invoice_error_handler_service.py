# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for verenigingen/services/billing/invoice_error_handler_service.py

Covers the error-classification and recovery decision logic against a REAL
Membership Dues Schedule document (so secure_document_operation saves and the
controller callbacks _advance_schedule_dates / _trigger_health_reconstruction run
for real — no mocking of business logic):

    - _deduplicate_error_message: collapses repeated "Invoice generation failed:" prefixes
    - _is_deadlock_error: detects 1213 / lock wait timeout / deadlock keywords
    - handle_invoice_generation_failure:
        * real (non-deadlock) error increments custom_invoice_retry_count and persists it
        * deadlock does NOT increment retry_count but increments custom_deadlock_count
        * after 3 real failures, a recoverable error -> "date_advanced" (next_invoice_date moves)
        * after 3 real failures, a critical (permission) error -> "skipped" + manual-review flag
    - should_auto_advance_schedule:
        * deadlock -> False
        * critical patterns (permission denied / currency mismatch) -> False
        * legacy manual-review patterns (customer record) -> False
        * reconstruction patterns (membership_type) -> True (and reconstruction attempted)
        * generic validation error -> True
"""

import frappe
from frappe.utils import today

from verenigingen.services.billing.invoice_error_handler_service import (
    InvoiceErrorHandlerService,
    get_invoice_error_handler_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestInvoiceErrorHandlerService(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_invoice_error_handler_service()
        self.member = self.create_test_member(
            first_name="ErrHandler", last_name="Test", birth_date="1975-09-09"
        )
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name="Regular Member"
        )
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        # Ensure a deterministic next_invoice_date for advancement assertions.
        self.schedule.next_invoice_date = today()
        self.schedule.save()

    # ------------------------------------------------------------------
    # _deduplicate_error_message
    # ------------------------------------------------------------------
    def test_deduplicate_collapses_repeated_prefix(self):
        msg = "Invoice generation failed: Invoice generation failed: Amount too low"
        cleaned = self.service._deduplicate_error_message(msg)
        self.assertEqual(cleaned, "Invoice generation failed: Amount too low")

    def test_deduplicate_empty_returns_empty(self):
        self.assertEqual(self.service._deduplicate_error_message(""), "")

    def test_deduplicate_single_prefix_unchanged(self):
        msg = "Invoice generation failed: Amount too low"
        self.assertEqual(self.service._deduplicate_error_message(msg), msg)

    # ------------------------------------------------------------------
    # _is_deadlock_error
    # ------------------------------------------------------------------
    def test_is_deadlock_true_for_1213(self):
        self.assertTrue(self.service._is_deadlock_error("Error 1213: Deadlock found"))

    def test_is_deadlock_true_for_lock_wait_code(self):
        # DEADLOCK_PATTERNS keys on the numeric error code 1205, not the prose.
        self.assertTrue(
            self.service._is_deadlock_error("Error 1205: Lock wait timeout exceeded; try restarting")
        )

    def test_is_deadlock_false_for_validation(self):
        self.assertFalse(self.service._is_deadlock_error("Validation failed: amount below minimum"))

    def test_is_deadlock_false_for_empty(self):
        self.assertFalse(self.service._is_deadlock_error(""))

    # ------------------------------------------------------------------
    # handle_invoice_generation_failure - retry accounting
    # ------------------------------------------------------------------
    def test_real_error_increments_retry_count_and_persists(self):
        self.schedule.custom_invoice_retry_count = 0
        result = self.service.handle_invoice_generation_failure(
            self.schedule, "Some validation error: amount too low"
        )
        self.assertEqual(result["action_taken"], "retry_tracked")
        self.assertEqual(result["retry_count"], 1)
        # Persisted to DB by secure_document_operation save.
        persisted = frappe.db.get_value(
            "Membership Dues Schedule", self.schedule.name, "custom_invoice_retry_count"
        )
        self.assertEqual(persisted, 1)
        # Error message stored (deduplicated, truncated).
        stored_err = frappe.db.get_value(
            "Membership Dues Schedule", self.schedule.name, "custom_last_invoice_error"
        )
        self.assertIn("amount too low", stored_err)

    def test_deadlock_does_not_increment_retry_but_tracks_deadlock(self):
        self.schedule.custom_invoice_retry_count = 0
        self.schedule.custom_deadlock_count = 0
        result = self.service.handle_invoice_generation_failure(
            self.schedule, "Error 1213: Deadlock found when trying to get lock"
        )
        # Deadlock is transient: retry_count stays 0.
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["action_taken"], "retry_tracked")
        deadlocks = frappe.db.get_value(
            "Membership Dues Schedule", self.schedule.name, "custom_deadlock_count"
        )
        self.assertEqual(deadlocks, 1)

    def test_third_recoverable_failure_advances_dates(self):
        """At retry_count 2 -> 3, a recoverable (membership_type) error auto-advances
        the schedule dates instead of looping forever."""
        self.schedule.custom_invoice_retry_count = 2
        old_next = self.schedule.next_invoice_date
        # Health reconstruction + date advancement legitimately write Error Log rows.
        self.expectErrorLog("Health Reconstruction Trigger", "Schedule Date Advancement")
        result = self.service.handle_invoice_generation_failure(
            self.schedule, "membership_type not found for schedule"
        )
        self.assertEqual(result["retry_count"], 3)
        self.assertEqual(result["action_taken"], "date_advanced")
        # next_invoice_date must have moved forward.
        self.assertNotEqual(self.schedule.next_invoice_date, old_next)

    def test_third_critical_failure_flags_manual_review(self):
        """At retry_count 2 -> 3, a critical (permission) error is NOT auto-advanced;
        the schedule is flagged for manual review (action 'skipped')."""
        self.schedule.custom_invoice_retry_count = 2
        result = self.service.handle_invoice_generation_failure(
            self.schedule, "permission denied: cannot create Sales Invoice"
        )
        self.assertEqual(result["retry_count"], 3)
        self.assertEqual(result["action_taken"], "skipped")
        flagged = frappe.db.get_value(
            "Membership Dues Schedule", self.schedule.name, "custom_requires_manual_review"
        )
        self.assertEqual(flagged, 1)

    def test_a_manual_review_flag_that_could_not_be_saved_is_reported(self):
        """If the escalation write fails, somebody has to be told.

        That write IS the escalation. Its result was discarded, so a failure left
        the schedule returned as "skipped" but carrying no flag -- it re-enters the
        retry loop indefinitely and never reaches the manual-review queue, which is
        the one outcome this branch exists to prevent.

        Nothing else would have noticed: `secure_document_operation` returns
        `success=False` rather than raising, so there is no exception for a handler
        to catch.
        """
        # The service imports secure_document_operation inside the function, so the
        # name resolves from its source module at call time -- patch it there.
        import verenigingen.utils.secure_operations as mod
        from verenigingen.utils.secure_operations import SecureOperationResult

        self.schedule.custom_invoice_retry_count = 2

        failed = SecureOperationResult(success=False, operation_id="test-flag-fail")
        failed.add_error("Simulated schedule save failure")
        real = mod.secure_document_operation
        calls = {"n": 0}

        def only_fail_the_flag_write(**kwargs):
            # The retry-tracking save earlier in this function must still succeed --
            # otherwise the test would not reach the branch it is about.
            calls["n"] += 1
            return failed if "manual review" in kwargs.get("justification", "") else real(**kwargs)

        mod.secure_document_operation = only_fail_the_flag_write
        self.addCleanup(lambda: setattr(mod, "secure_document_operation", real))

        before = frappe.db.count("Error Log", {"error": ["like", "%could NOT be flagged%"]})
        result = self.service.handle_invoice_generation_failure(
            self.schedule, "permission denied: cannot create Sales Invoice"
        )
        after = frappe.db.count("Error Log", {"error": ["like", "%could NOT be flagged%"]})

        self.assertEqual(result["action_taken"], "skipped")
        self.assertGreater(
            after,
            before,
            "the schedule was never flagged for manual review and nothing recorded it, so it "
            "will retry forever with no human in the loop",
        )

    # ------------------------------------------------------------------
    # should_auto_advance_schedule - pattern classification
    # ------------------------------------------------------------------
    def test_should_advance_false_for_deadlock(self):
        self.assertFalse(
            self.service.should_auto_advance_schedule(self.schedule, "Error 1213: Deadlock found")
        )

    def test_should_advance_false_for_critical_permission(self):
        self.assertFalse(
            self.service.should_auto_advance_schedule(self.schedule, "permission denied for user")
        )

    def test_should_advance_false_for_critical_currency_mismatch(self):
        self.assertFalse(
            self.service.should_auto_advance_schedule(
                self.schedule, "currency mismatch between party and document"
            )
        )

    def test_should_advance_false_for_legacy_customer_record(self):
        self.assertFalse(
            self.service.should_auto_advance_schedule(self.schedule, "Member has no customer record")
        )

    def test_should_advance_true_for_reconstruction_pattern(self):
        """A reconstruction-eligible error (membership_type) triggers health
        reconstruction and auto-advances."""
        self.expectErrorLog("Health Reconstruction Trigger")
        self.assertTrue(
            self.service.should_auto_advance_schedule(self.schedule, "membership_type missing for member")
        )

    def test_should_advance_true_for_generic_validation(self):
        self.assertTrue(
            self.service.should_auto_advance_schedule(
                self.schedule, "Some generic transient validation hiccup"
            )
        )

    def test_get_service_returns_instance(self):
        self.assertIsInstance(get_invoice_error_handler_service(), InvoiceErrorHandlerService)
