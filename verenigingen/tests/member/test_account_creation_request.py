"""
Real-integration tests for the ``Account Creation Request`` (ACR) DocType
controller at
``verenigingen/verenigingen/doctype/account_creation_request/account_creation_request.py``.

The controller owns secure account-provisioning requests: status lifecycle
(mark_processing / mark_completed / mark_failed / retry / cancel), permission
gating (can_request_role), the completion side-effects (board-role assignment +
approval email), and the whitelisted admin/reporting endpoints
(get_pending_requests, bulk_queue_requests, get_request_statistics). It was
~53% covered.

No business-logic mocking: real Members, Volunteers, Chapters, Users, Chapter
Board Members and ACRs are created via the factory / ``frappe.get_doc().insert()``.
Tests run as Administrator (so the @critical_api/@high_security_api tiers pass);
a non-admin path is exercised with a real low-privilege user.

Things deliberately NOT processed end-to-end:
* queue_processing()/retry_processing() enqueue the real pipeline; under
  ``frappe.flags.in_test`` enqueue runs inline against ONLY the member we create.
  We assert status transitions and track any User the pipeline makes.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.constants import Roles
from verenigingen.verenigingen.doctype.account_creation_request import (
    account_creation_request as acr_module,
)


class TestAccountCreationRequest(VereningingenTestCase):
    """Exercise the Account Creation Request controller end to end."""

    def setUp(self):
        super().setUp()
        self.uid = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="AcrCtl",
            last_name=f"Member{self.uid}",
            email=f"acrctl.{self.uid}@test.invalid",
            status="Active",
        )

    # ------------------------------------------------------------------ helpers

    def _track_user(self, email):
        if email and frappe.db.exists("User", email):
            self.track_doc("User", email)

    def _insert_acr(self, **overrides):
        """Insert a real Account Creation Request for self.member (tracked)."""
        data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,
            "full_name": self.member.full_name,
            "priority": "Normal",
            "role_profile": "Verenigingen Member",
            "business_justification": "test",
            "requested_roles": [{"role": "Verenigingen Member"}],
        }
        data.update(overrides)
        request = frappe.get_doc(data)
        request.insert()
        self.track_doc("Account Creation Request", request.name)
        return request

    # =================================================================
    # before_insert / set_defaults
    # =================================================================

    def test_before_insert_forces_requested_status_and_audit(self):
        # Even if a caller tries to set status/completed_at, before_insert resets
        # them (anti mass-assignment).
        request = self._insert_acr(status="Completed", completed_at=frappe.utils.now())
        self.assertEqual(request.status, "Requested")
        self.assertIsNone(request.created_user)
        self.assertIsNone(request.completed_at)
        self.assertEqual(request.requested_by, frappe.session.user)
        # set_defaults fills priority + pipeline_stage.
        self.assertEqual(request.priority, "Normal")
        self.assertEqual(request.pipeline_stage, "Validation")

    def test_validate_source_record_nonexistent_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._insert_acr(source_record="NONEXISTENT-MEMBER-ZZZ")

    def test_sanitize_inputs_blocks_xss(self):
        with self.assertRaises(frappe.ValidationError):
            self._insert_acr(full_name="<script>alert(1)</script>")

    # =================================================================
    # can_request_role
    # =================================================================

    def test_can_request_role_system_manager_admin(self):
        # Administrator holds System Manager + Role write, so even the System
        # Manager role is grantable.
        request = self._insert_acr()
        self.assertTrue(request.can_request_role(Roles.SYSTEM_MANAGER))

    def test_can_request_role_verenigingen_role_for_admin(self):
        request = self._insert_acr()
        self.assertTrue(request.can_request_role("Verenigingen Volunteer"))

    def test_can_request_role_denied_for_plain_member(self):
        # A low-privilege user can neither request System Manager nor arbitrary roles.
        request = self._insert_acr()
        email = f"acrctl.plain.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        with self.as_user(user.name):
            # System Manager request must raise PermissionError.
            with self.assertRaises(frappe.PermissionError):
                request.can_request_role(Roles.SYSTEM_MANAGER)
            # A normal verenigingen role: default-deny (returns False).
            self.assertFalse(request.can_request_role("Verenigingen Volunteer"))

    # =================================================================
    # mark_processing / mark_completed / mark_failed
    # =================================================================

    def test_mark_processing_sets_status_and_stage(self):
        request = self._insert_acr()
        request.mark_processing(stage="Account Creation")
        self.assertEqual(request.status, "Processing")
        self.assertEqual(request.pipeline_stage, "Account Creation")
        self.assertEqual(request.processed_by, frappe.session.user)
        self.assertIsNotNone(request.processing_started_at)

    def test_mark_completed_sets_completion_fields(self):
        request = self._insert_acr()
        request.mark_completed(user=None, employee=None)
        self.assertEqual(request.status, "Completed")
        self.assertEqual(request.pipeline_stage, "Completed")
        self.assertIsNotNone(request.completed_at)
        # Persisted to DB (mark_completed commits).
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "status"),
            "Completed",
        )

    def test_mark_completed_records_created_user(self):
        request = self._insert_acr()
        email = f"acrctl.created.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        request.mark_completed(user=user.name)
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "created_user"),
            user.name,
        )

    def test_mark_failed_records_reason(self):
        request = self._insert_acr()
        request.mark_failed("explosion in stage 2", stage="Account Creation")
        self.assertEqual(request.status, "Failed")
        self.assertEqual(request.pipeline_stage, "Account Creation")
        self.assertIn("explosion", request.failure_reason)

    def test_mark_failed_truncates_long_reason(self):
        request = self._insert_acr()
        request.mark_failed("x" * 5000)
        # failure_reason is truncated to 1000 chars by the controller.
        self.assertLessEqual(len(request.failure_reason), 1000)

    # =================================================================
    # cancel_request (@whitelist)
    # =================================================================

    def test_cancel_request_sets_cancelled(self):
        request = self._insert_acr()
        request.cancel_request(reason="no longer needed")
        self.assertEqual(request.status, "Cancelled")
        self.assertIn("no longer needed", request.failure_reason)

    def test_cancel_request_completed_rejected(self):
        request = self._insert_acr()
        request.mark_completed()
        request.reload()
        with self.assertRaises(frappe.ValidationError):
            request.cancel_request()

    # =================================================================
    # retry_processing (@whitelist) - guard paths
    # =================================================================

    def test_retry_non_failed_rejected(self):
        request = self._insert_acr()  # status Requested
        with self.assertRaises(frappe.ValidationError):
            request.retry_processing()

    def test_retry_exceeds_max_retries_rejected(self):
        request = self._insert_acr()
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "retry_count": request.MAX_RETRIES},
        )
        request.reload()
        with self.assertRaises(frappe.ValidationError):
            request.retry_processing()

    def test_retry_failed_requeues_and_increments(self):
        # A Failed request under the retry cap requeues (enqueue runs inline in
        # tests) and bumps retry_count.
        request = self._insert_acr()
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "boom", "retry_count": 0},
        )
        request.reload()
        result = request.retry_processing()
        self._track_user(self.member.email)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(
            frappe.db.get_value("Account Creation Request", request.name, "retry_count"),
            1,
        )

    # =================================================================
    # queue_processing (@whitelist) - status guard
    # =================================================================

    def test_queue_processing_invalid_status_rejected(self):
        request = self._insert_acr()
        frappe.db.set_value("Account Creation Request", request.name, "status", "Completed")
        request.reload()
        with self.assertRaises(frappe.ValidationError):
            request.queue_processing()

    def test_queue_processing_happy_path(self):
        request = self._insert_acr()
        result = request.queue_processing()
        self._track_user(self.member.email)
        self.assertTrue(result["success"])
        # Inline enqueue in tests drives the pipeline; the request must not be
        # left in the initial Requested state.
        status = frappe.db.get_value("Account Creation Request", request.name, "status")
        self.assertIn(status, ("Queued", "Processing", "Completed"))

    # =================================================================
    # _get_acr_age_in_hours
    # =================================================================

    def test_acr_age_in_hours_recent(self):
        request = self._insert_acr()
        age = request._get_acr_age_in_hours()
        self.assertGreaterEqual(age, 0)
        self.assertLess(age, 1)  # just created

    # =================================================================
    # handle_completion / _assign_pending_board_member_roles
    # =================================================================

    def test_handle_completion_assigns_pending_board_role(self):
        # A volunteer added to a chapter board BEFORE their user existed gets the
        # board role retroactively when the ACR completes.
        email = f"acrctl.board.{frappe.generate_hash(length=6)}@test.invalid"
        member = self.create_test_member(
            first_name="AcrBoard",
            last_name=f"M{frappe.generate_hash(length=5)}",
            email=email,
            status="Active",
        )
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", member.name, "user", user.name)

        volunteer = self.create_test_volunteer(member=member.name)
        if not frappe.db.exists("Chapter Role", "Bestuurslid"):
            frappe.get_doc(
                {"doctype": "Chapter Role", "role_name": "Bestuurslid", "is_active": 1}
            ).insert()
            self.track_doc("Chapter Role", "Bestuurslid")
        chapter = self.create_test_chapter()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": "Bestuurslid",
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()

        request = self._insert_acr(source_record=member.name, email=email)
        # Call the private helper directly (the public path is on_update->handle_completion).
        request._assign_pending_board_member_roles(member.name)

        has_role = frappe.db.exists(
            "Has Role", {"parent": user.name, "role": "Verenigingen Chapter Board Member"}
        )
        self.assertTrue(has_role)

    def test_assign_pending_board_role_no_volunteer_noop(self):
        # No volunteer for the member -> graceful no-op (must not raise).
        request = self._insert_acr()
        request._assign_pending_board_member_roles(self.member.name)  # no exception

    def test_handle_completion_skips_email_for_csv_member(self):
        # A member with no application_id (CSV import) must not trigger an approval
        # email; handle_completion returns early without raising.
        frappe.db.set_value("Member", self.member.name, "application_id", "")
        request = self._insert_acr()
        request.db_set("status", "Completed")
        # has_value_changed needs a prior load; call handle_completion directly.
        request.handle_completion()  # no exception, no email path entered

    # =================================================================
    # get_application_invoice / send_member_approval_email
    # =================================================================

    def test_get_application_invoice_no_history_returns_none(self):
        request = self._insert_acr()
        member = frappe.get_doc("Member", self.member.name)
        self.assertIsNone(request.get_application_invoice(member))

    def test_send_member_approval_email_without_invoice_does_not_raise(self):
        # With no application invoice resolvable, the method logs a warning and
        # returns without raising (the email is simply skipped).
        request = self._insert_acr()
        member = frappe.get_doc("Member", self.member.name)
        request.send_member_approval_email(member)  # no exception

    # =================================================================
    # get_pending_requests (@whitelist)
    # =================================================================

    def test_get_pending_requests_lists_requested(self):
        request = self._insert_acr()
        pending = acr_module.get_pending_requests()
        names = [r["name"] for r in pending]
        self.assertIn(request.name, names)

    def test_get_pending_requests_includes_failed_excludes_completed(self):
        failed = self._insert_acr()
        frappe.db.set_value("Account Creation Request", failed.name, "status", "Failed")
        completed = self._insert_acr(email=f"acrctl.done.{self.uid}@test.invalid")
        frappe.db.set_value("Account Creation Request", completed.name, "status", "Completed")
        names = [r["name"] for r in acr_module.get_pending_requests()]
        self.assertIn(failed.name, names)
        self.assertNotIn(completed.name, names)

    def test_get_pending_requests_permission_denied_for_plain_user(self):
        # @high_security_api(ADMIN) rejects a low-tier user before the body runs.
        from verenigingen.utils.error_handling import PermissionError as FwPermissionError

        email = f"acrctl.nopem.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        with self.as_user(user.name):
            with self.assertRaises(FwPermissionError):
                acr_module.get_pending_requests()

    # =================================================================
    # bulk_queue_requests (@whitelist)
    # =================================================================

    def test_bulk_queue_requests_queues_requested(self):
        request = self._insert_acr()
        result = acr_module.bulk_queue_requests([request.name])
        self._track_user(self.member.email)
        self.assertTrue(result["success"])
        self.assertEqual(result["queued_count"], 1)
        self.assertEqual(result["error_count"], 0)

    def test_bulk_queue_requests_json_string_arg(self):
        # frappe.call serializes list args to JSON strings; the endpoint must
        # parse them back.
        request = self._insert_acr()
        import json

        result = acr_module.bulk_queue_requests(json.dumps([request.name]))
        self._track_user(self.member.email)
        self.assertTrue(result["success"])
        self.assertEqual(result["queued_count"], 1)

    def test_bulk_queue_requests_non_requested_reports_error(self):
        # A request not in "Requested" status is skipped with an error entry.
        request = self._insert_acr()
        frappe.db.set_value("Account Creation Request", request.name, "status", "Completed")
        result = acr_module.bulk_queue_requests([request.name])
        self.assertFalse(result["success"])
        self.assertEqual(result["queued_count"], 0)
        self.assertEqual(result["error_count"], 1)

    def test_bulk_queue_requests_invalid_format_throws(self):
        with self.assertRaises(frappe.ValidationError):
            acr_module.bulk_queue_requests("{not valid json")

    # =================================================================
    # get_request_statistics (@whitelist)
    # =================================================================

    def test_get_request_statistics_shape_and_counts(self):
        # Insert one Requested ACR and assert it shows up in the grouped counts.
        self._insert_acr()
        stats = acr_module.get_request_statistics()
        self.assertIsInstance(stats, list)
        by_status = {row["status"]: row["count"] for row in stats}
        self.assertIn("Requested", by_status)
        self.assertGreaterEqual(by_status["Requested"], 1)
