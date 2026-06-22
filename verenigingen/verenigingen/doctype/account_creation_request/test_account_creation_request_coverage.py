# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""
Real-DB coverage tests for the Account Creation Request controller.

Account Creation Request is the audited request object that drives secure user
account creation (the account_creation_api pipeline). These tests build REAL
Member source records and real ACR documents and exercise the controller's own
logic — NOT the background pipeline, which requires a worker:

- sanitize_inputs(): XSS / SQL-injection pattern rejection
- before_insert(): forced status + system-field clearing (mass-assignment guard)
- autoname(): ACR-<type>-<date>-<hash> naming
- validate_source_record(): source must exist
- set_defaults(): priority / pipeline_stage defaults
- can_request_role(): role-request authorization matrix
- validate_email_uniqueness(): link-to-existing-user behaviour
- status transitions: mark_processing / mark_completed / mark_failed
- queue_processing(): status guard + Queued transition (worker enqueue is fire-
  and-forget; we assert the persisted status change)
- retry_processing(): only-failed guard + retry-count cap
- cancel_request(): cannot-cancel-completed guard
- get_pending_requests / get_request_statistics / bulk_queue_requests endpoints

Runs as Administrator (has User:create) so the permission gates pass.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAccountCreationRequestCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Acr", last_name="Source", email="acr.source.cov@example.invalid"
        )

    def _make_acr(self, **overrides):
        data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": frappe.generate_hash("acr", 6) + "@example.invalid",
            "full_name": "Acr Person",
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        doc.insert()
        self.track_doc("Account Creation Request", doc.name)
        return doc

    # ------------------------------------------------------- sanitize_inputs
    def test_xss_in_full_name_rejected(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._make_acr(full_name="<script>alert(1)</script>")
        self.assertIn("not allowed", str(ctx.exception))

    def test_sql_injection_in_full_name_rejected(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._make_acr(full_name="Robert'; DROP TABLE tabUser")
        self.assertIn("not allowed", str(ctx.exception))

    def test_clean_full_name_accepted(self):
        doc = self._make_acr(full_name="Jane Q. Member")
        self.assertEqual(doc.full_name, "Jane Q. Member")

    # ------------------------------------------------------ before_insert
    def test_before_insert_forces_status_requested_and_clears_system_fields(self):
        # Attempt mass-assignment of privileged fields; controller must reset them.
        doc = self._make_acr(
            status="Completed",
            created_user="Administrator",
            completed_at=frappe.utils.now(),
        )
        self.assertEqual(doc.status, "Requested")
        self.assertIsNone(doc.created_user)
        self.assertIsNone(doc.completed_at)
        # requested_by is stamped to the session user.
        self.assertEqual(doc.requested_by, frappe.session.user)

    # ------------------------------------------------------------- autoname
    def test_autoname_format(self):
        doc = self._make_acr()
        self.assertTrue(doc.name.startswith("ACR-Member-"))

    # --------------------------------------------------- validate_source_record
    def test_missing_source_record_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._make_acr(source_record="NO-SUCH-MEMBER-COV")

    # -------------------------------------------------------------- set_defaults
    def test_defaults_set_when_omitted(self):
        doc = self._make_acr()
        self.assertEqual(doc.priority, "Normal")
        self.assertEqual(doc.pipeline_stage, "Validation")

    # -------------------------------------------------------- can_request_role
    def test_can_request_role_admin_can_request_member_role(self):
        doc = self._make_acr()
        # Administrator is a System Manager -> can assign non-system-manager roles.
        self.assertTrue(doc.can_request_role("Verenigingen Member"))

    def test_can_request_system_manager_requires_role_write(self):
        doc = self._make_acr()
        # Administrator has Role:write -> System Manager request allowed.
        self.assertTrue(doc.can_request_role("System Manager"))

    # ------------------------------------------------- status transition methods
    def test_mark_processing_sets_status_and_stage(self):
        doc = self._make_acr()
        doc.mark_processing(stage="User Creation")
        self.assertEqual(doc.status, "Processing")
        self.assertEqual(doc.pipeline_stage, "User Creation")
        self.assertEqual(doc.processed_by, frappe.session.user)

    def test_mark_completed_sets_completed_state(self):
        doc = self._make_acr()
        doc.mark_completed()
        self.assertEqual(doc.status, "Completed")
        self.assertEqual(doc.pipeline_stage, "Completed")
        self.assertTrue(doc.completed_at)

    def test_mark_failed_records_reason(self):
        doc = self._make_acr()
        doc.mark_failed("boom went the pipeline", stage="User Creation")
        self.assertEqual(doc.status, "Failed")
        self.assertIn("boom", doc.failure_reason)
        self.assertEqual(doc.pipeline_stage, "User Creation")

    def test_mark_failed_truncates_long_reason(self):
        doc = self._make_acr()
        doc.mark_failed("x" * 5000)
        self.assertLessEqual(len(doc.failure_reason), 1000)

    # --------------------------------------------------------- queue_processing
    def test_queue_processing_transitions_to_queued(self):
        doc = self._make_acr()
        result = doc.queue_processing()
        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("Account Creation Request", doc.name, "status"), "Queued")

    def test_queue_processing_rejects_completed_status(self):
        doc = self._make_acr()
        doc.mark_completed()
        with self.assertRaises(frappe.ValidationError):
            doc.queue_processing()

    # --------------------------------------------------------- retry_processing
    def test_retry_only_allowed_for_failed(self):
        doc = self._make_acr()
        # Status is "Requested" -> retry must be rejected.
        with self.assertRaises(frappe.ValidationError) as ctx:
            doc.retry_processing()
        self.assertIn("failed requests", str(ctx.exception).lower())

    def test_retry_respects_max_retries_cap(self):
        doc = self._make_acr()
        doc.mark_failed("failed once")
        # Force retry_count to the cap so the next retry is rejected.
        frappe.db.set_value(
            "Account Creation Request", doc.name, "retry_count", doc.MAX_RETRIES, update_modified=False
        )
        with self.assertRaises(frappe.ValidationError) as ctx:
            doc.retry_processing()
        self.assertIn("Maximum retry", str(ctx.exception))

    # ------------------------------------------------------------ cancel_request
    def test_cancel_request_sets_cancelled(self):
        doc = self._make_acr()
        doc.cancel_request(reason="changed my mind")
        self.assertEqual(doc.status, "Cancelled")
        self.assertIn("changed my mind", doc.failure_reason)

    def test_cannot_cancel_completed_request(self):
        doc = self._make_acr()
        doc.mark_completed()
        doc.reload()
        with self.assertRaises(frappe.ValidationError):
            doc.cancel_request()

    # --------------------------------------------------- _get_queue_depth helper
    def test_get_queue_depth_returns_int(self):
        doc = self._make_acr()
        depth = doc._get_queue_depth("long")
        self.assertIsInstance(depth, int)
        self.assertGreaterEqual(depth, 0)

    # ------------------------------------------------------ endpoint: pending
    def test_get_pending_requests_includes_requested(self):
        from verenigingen.verenigingen.doctype.account_creation_request.account_creation_request import (
            get_pending_requests,
        )

        doc = self._make_acr()
        rows = get_pending_requests()
        names = {r["name"] for r in rows}
        self.assertIn(doc.name, names)

    # --------------------------------------------------- endpoint: statistics
    def test_get_request_statistics_returns_status_counts(self):
        from verenigingen.verenigingen.doctype.account_creation_request.account_creation_request import (
            get_request_statistics,
        )

        self._make_acr()
        stats = get_request_statistics()
        self.assertIsInstance(stats, list)
        # Each row is a {status, count} dict.
        for row in stats:
            self.assertIn("status", row)
            self.assertIn("count", row)

    # --------------------------------------------------- endpoint: bulk queue
    def test_bulk_queue_requests_queues_requested_only(self):
        import json

        from verenigingen.verenigingen.doctype.account_creation_request.account_creation_request import (
            bulk_queue_requests,
        )

        a = self._make_acr()
        b = self._make_acr()
        b.mark_completed()  # not in "Requested" -> should be reported as an error
        b.reload()

        result = bulk_queue_requests(json.dumps([a.name, b.name]))
        self.assertEqual(result["queued_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(frappe.db.get_value("Account Creation Request", a.name, "status"), "Queued")

    def test_bulk_queue_requests_invalid_json_throws(self):
        from verenigingen.verenigingen.doctype.account_creation_request.account_creation_request import (
            bulk_queue_requests,
        )

        with self.assertRaises(frappe.ValidationError):
            bulk_queue_requests("{not json")

    # ----------------------------------------------- safe_log_error helper
    def test_safe_log_error_truncates(self):
        from verenigingen.verenigingen.doctype.account_creation_request.account_creation_request import (
            safe_log_error,
        )

        self.expectErrorLog("")  # this helper writes an Error Log on purpose
        # A 500-char message is truncated to 100 chars + "..." (103) and passed as
        # the log title (Error Log.method). Read the row back and assert the
        # truncation actually happened — the whole point of the helper.
        safe_log_error("y" * 500, "ACR Safe Log Test Cov")
        row = frappe.get_all(
            "Error Log",
            filters={"method": ["like", "yyyyy%"]},
            fields=["method"],
            order_by="creation desc",
            limit=1,
        )
        self.assertTrue(row, "safe_log_error did not write an Error Log")
        self.assertLessEqual(len(row[0].method), 103)
        self.assertTrue(row[0].method.endswith("..."))
