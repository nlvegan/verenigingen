"""
Test Suite for Bulk Account Creation System

Tests bulk account creation queueing, tracker functionality, error handling,
and security controls using real database operations.
"""

import time
import unittest
from datetime import timedelta

import frappe
from frappe.utils import now_datetime, random_string

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.account_creation_manager import (
    queue_bulk_account_creation_for_members,
)
from verenigingen.verenigingen.doctype.bulk_operation_tracker.bulk_operation_tracker import (
    BulkOperationTracker,
)


class TestBulkAccountCreationScale(EnhancedTestCase):
    """Test bulk account creation at different scales."""

    def _create_members(self, count, prefix="BULK"):
        """Create test members using the factory for reliable creation."""
        members = []
        for i in range(count):
            member = self.create_test_member(
                first_name=f"{prefix}{i}",
                last_name=f"Scale",
            )
            members.append(member.name)
        frappe.db.commit()
        return members

    def test_01_small_scale(self):
        """Test bulk account creation with a small batch."""
        member_names = self._create_members(5, "SM")
        self.assertEqual(len(member_names), 5)

        start_time = time.time()
        result = queue_bulk_account_creation_for_members(
            member_names=member_names,
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Member",
            batch_size=50,
            priority="Normal",
        )
        queue_time = time.time() - start_time

        # @critical_api decorator converts OperationResult to dict via to_dict()
        self.assertTrue(result["success"], f"Bulk queue should succeed: {result}")
        self.assertEqual(result["data"]["requests_created"], 5)
        self.assertEqual(result["data"]["batch_count"], 1)
        self.assertLess(queue_time, 30)

        tracker_name = result["data"]["tracker_name"]
        self.assertIsNotNone(tracker_name)

        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        self.assertEqual(tracker.total_records, 5)
        self.assertEqual(tracker.total_batches, 1)
        self.assertEqual(tracker.batch_size, 50)

    def test_02_medium_scale(self):
        """Test bulk account creation with multiple batches."""
        member_names = self._create_members(10, "MD")
        self.assertEqual(len(member_names), 10)

        result = queue_bulk_account_creation_for_members(
            member_names=member_names,
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Member",
            batch_size=5,
            priority="Normal",
        )

        self.assertTrue(result["success"], f"Bulk queue should succeed: {result}")
        self.assertEqual(result["data"]["requests_created"], 10)
        # COR pattern queues only the first batch; total_batches is on the tracker
        self.assertEqual(result["data"]["batch_count"], 1)

        tracker = frappe.get_doc("Bulk Operation Tracker", result["data"]["tracker_name"])
        self.assertEqual(tracker.total_records, 10)
        self.assertEqual(tracker.total_batches, 2)

    @unittest.skipIf(
        frappe.conf.get("skip_large_tests", True),
        "Large scale test skipped by default. Set skip_large_tests=False to run.",
    )
    def test_03_large_scale(self):
        """Test bulk account creation at production-like scale."""
        member_names = self._create_members(100, "LG")
        self.assertEqual(len(member_names), 100)

        result = queue_bulk_account_creation_for_members(
            member_names=member_names,
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Member",
            batch_size=50,
            priority="Low",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["requests_created"], 100)
        self.assertEqual(result["data"]["batch_count"], 2)

    def test_04_edge_cases(self):
        """Test edge cases: 1, 3, 6 members (boundary around batch_size=5)."""
        for count in [1, 3, 6]:
            with self.subTest(count=count):
                member_names = self._create_members(count, f"E{count}")
                self.assertEqual(len(member_names), count)

                result = queue_bulk_account_creation_for_members(
                    member_names=member_names,
                    batch_size=5,
                )

                self.assertTrue(result["success"], f"Edge case {count} should succeed: {result}")
                self.assertEqual(result["data"]["requests_created"], count)
                # COR pattern queues only the first batch
                self.assertEqual(result["data"]["batch_count"], 1)
                # Verify total batches via tracker
                tracker = frappe.get_doc("Bulk Operation Tracker", result["data"]["tracker_name"])
                expected_batches = (count + 4) // 5
                self.assertEqual(tracker.total_batches, expected_batches)


class TestBulkAccountCreationErrorHandling(EnhancedTestCase):
    """Test error handling and retry mechanisms in bulk account creation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The bulk-account-creation queue path depends on
        # Verenigingen Settings.creation_user (the system user used for
        # privileged Account Creation Request inserts). `run-tests --module`
        # does not reliably run before_tests on a fresh/snapshot site, so seed
        # the member-domain masters here; otherwise the queue call fails with
        # "Unable to queue bulk account creation. Please contact support".
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()

    def test_validation_errors(self):
        """Test handling of validation errors (missing emails, non-existent members)."""
        members_with_issues = []

        # Member without email — should cause validation error
        member_no_email = self.create_test_member(
            first_name="NoEmail",
            last_name="Test",
        )
        # Clear the email after creation to simulate a member without email
        frappe.db.set_value("Member", member_no_email.name, "email", "")
        members_with_issues.append(member_no_email.name)

        # Valid member
        valid_member = self.create_test_member(
            first_name="Valid",
            last_name="Test",
        )
        members_with_issues.append(valid_member.name)

        # Non-existent member
        members_with_issues.append("NON-EXISTENT-MEMBER-12345")

        frappe.db.commit()

        result = queue_bulk_account_creation_for_members(
            member_names=members_with_issues,
        )

        # @critical_api converts OperationResult to dict
        self.assertTrue(result["success"], f"Should succeed with partial errors: {result}")
        self.assertEqual(result["data"]["validation_errors_count"], 2)
        self.assertEqual(result["data"]["requests_created"], 1)

    def test_batch_failure_isolation(self):
        """Test that tracker correctly records partial batch failures."""
        members = []
        for i in range(10):
            member = self.create_test_member(
                first_name=f"Batch{i}",
                last_name="Isolation",
            )
            members.append(member.name)
        frappe.db.commit()

        result = queue_bulk_account_creation_for_members(
            member_names=members,
            batch_size=5,
        )

        self.assertTrue(result["success"], f"Queue should succeed: {result}")
        # COR pattern queues only the first batch
        self.assertEqual(result["data"]["batch_count"], 1)

        tracker_name = result["data"]["tracker_name"]
        request_names = result["data"]["request_names"]

        # Simulate processing batch 1 with one failure
        batch_1_results = {
            "completed": 4,
            "failed": 1,
            "errors": [f"{request_names[0]}: Simulated failure"],
            "failed_requests": [request_names[0]],
        }

        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        tracker.update_progress(1, batch_1_results)

        self.assertEqual(tracker.successful_records, 4)
        self.assertEqual(tracker.failed_records, 1)
        self.assertEqual(tracker.processed_records, 5)

    def test_retry_queue_functionality(self):
        """Test that failed requests are properly queued for retry."""
        members = []
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Retry{i}",
                last_name="Queue",
            )
            members.append(member.name)
        frappe.db.commit()

        result = queue_bulk_account_creation_for_members(
            member_names=members,
            batch_size=5,
        )

        self.assertTrue(result["success"], f"Queue should succeed: {result}")

        tracker_name = result["data"]["tracker_name"]
        request_names = result["data"]["request_names"]
        self.assertTrue(len(request_names) >= 3, "Need at least 3 requests for retry test")

        # Simulate batch with 2 failures
        batch_results = {
            "completed": len(request_names) - 2,
            "failed": 2,
            "errors": [
                f"{request_names[0]}: Connection timeout",
                f"{request_names[1]}: Database lock",
            ],
            "failed_requests": request_names[:2],
        }

        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        tracker.update_progress(1, batch_results)

        # Retry list is derived from ACR status (#172): mark the two failed
        # requests as Failed so they surface in the derived retry list.
        for req in request_names[:2]:
            frappe.db.set_value("Account Creation Request", req, "status", "Failed", update_modified=False)

        retry_queue = tracker.get_retry_requests()
        self.assertEqual(len(retry_queue), 2)
        self.assertIn(request_names[0], retry_queue)
        self.assertIn(request_names[1], retry_queue)


class TestBulkOperationTrackerFunctionality(EnhancedTestCase):
    """Test the BulkOperationTracker DocType functionality."""

    def test_tracker_creation_and_updates(self):
        """Test tracker creation and progress updates."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation",
            total_records=100,
            batch_size=25,
            priority="Normal",
        )

        self.assertIsNotNone(tracker)
        self.assertEqual(tracker.total_records, 100)
        self.assertEqual(tracker.total_batches, 4)
        self.assertEqual(tracker.status, "Queued")

        # start_operation() sets status to Processing and records start time
        tracker.reload()
        tracker.start_operation()

        self.assertEqual(tracker.status, "Processing")
        self.assertIsNotNone(tracker.started_at)

        # Update progress for batch 1
        tracker.update_progress(1, {"completed": 25, "failed": 0, "errors": []})

        self.assertEqual(tracker.successful_records, 25)
        self.assertEqual(tracker.failed_records, 0)
        self.assertEqual(tracker.processed_records, 25)
        self.assertEqual(tracker.current_batch, 1)

        progress = tracker.get_progress_percentage()
        self.assertEqual(progress, 25.0)

        # Complete remaining batches
        for batch_num in range(2, 5):
            tracker.update_progress(batch_num, {"completed": 25, "failed": 0, "errors": []})

        self.assertEqual(tracker.status, "Completed")
        self.assertIsNotNone(tracker.completed_at)
        self.assertEqual(tracker.processed_records, 100)

    def test_progress_rate_calculation(self):
        """Test processing rate and estimated completion calculations."""
        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation",
            total_records=1000,
            batch_size=50,
        )

        # Set up state for rate calculation — use Frappe datetime strings
        ten_minutes_ago = now_datetime() - timedelta(minutes=10)
        tracker.started_at = ten_minutes_ago.strftime("%Y-%m-%d %H:%M:%S")
        tracker.processed_records = 200
        tracker.status = "Processing"

        # Rate/ETA are derived at read-time now (#172) — pure getters, no mutation.
        rate = tracker.get_processing_rate()
        self.assertAlmostEqual(rate, 20.0, delta=2.0)
        self.assertIsNotNone(tracker.get_estimated_completion())

    # test_error_summary_management removed (#172): the old _update_error_summary
    # truncation is gone; error summary now derives from linked ACR failure_reason
    # and is covered by test_bulk_operation_tracker.test_get_retry_requests_derives_from_failed_acrs
    # (which asserts get_error_summary surfaces the ACR failure reason).


class TestDutchBusinessLogicValidation(EnhancedTestCase):
    """Test Dutch business logic in bulk processing."""

    def test_dutch_name_handling(self):
        """Test proper handling of Dutch names with tussenvoegsel."""
        members = []
        test_names = [
            ("Jan", "van der", "Berg"),
            ("Marie", "de", "Vries"),
            ("Pieter", None, "Bakker"),
            ("Anna", "van", "Dijk"),
            ("Willem", "van den", "Broek"),
        ]

        for first, tussenvoegsel, last in test_names:
            member = self.create_test_member(
                first_name=first,
                last_name=last,
                middle_name=tussenvoegsel or "",
            )
            members.append(member.name)

        frappe.db.commit()

        result = queue_bulk_account_creation_for_members(member_names=[m for m in members])

        self.assertTrue(result["success"], f"Dutch names queue should succeed: {result}")
        self.assertEqual(result["data"]["requests_created"], 5)

        # Verify account creation requests have names
        for request_name in result["data"].get("request_names", []):
            request = frappe.get_doc("Account Creation Request", request_name)
            self.assertIsNotNone(request.full_name)

    def test_age_requirements_for_volunteers(self):
        """Test that adult members can be queued for volunteer account creation."""
        # Use ages that pass the factory's minimum age validation (>= 16)
        young_adult_member = self.create_test_member(
            first_name="YoungAdult",
            last_name="Volunteer",
            birth_date=(now_datetime() - timedelta(days=365 * 18)).strftime("%Y-%m-%d"),
        )
        adult_member = self.create_test_member(
            first_name="Adult",
            last_name="Volunteer",
            birth_date=(now_datetime() - timedelta(days=365 * 25)).strftime("%Y-%m-%d"),
        )

        frappe.db.commit()

        result = queue_bulk_account_creation_for_members(
            member_names=[young_adult_member.name, adult_member.name],
            roles=["Verenigingen Member", "Verenigingen Volunteer"],
            role_profile="Verenigingen Volunteer",
        )

        self.assertTrue(result["success"], f"Age test should succeed: {result}")
        self.assertEqual(result["data"]["requests_created"], 2)


class TestBulkAccountCreationSecurity(EnhancedTestCase):
    """Test security aspects of bulk account creation."""

    def test_permission_requirements(self):
        """Test that proper permissions are required for bulk operations."""
        members = []
        for i in range(3):
            member = self.create_test_member(
                first_name="Security",
                last_name=f"Perm{i}",
            )
            members.append(member.name)

        member_names = [m for m in members]

        # Create a user without User creation permission
        test_user = self.create_test_user(
            f"security.perm.{random_string(5)}@example.com",
            roles=["Verenigingen Member"],
        )

        # @critical_api decorator raises VPermissionError for unauthorized users
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        with self.as_user(test_user.name):
            with self.assertRaises((frappe.PermissionError, VPermissionError)):
                queue_bulk_account_creation_for_members(member_names=member_names)

    def test_no_permission_bypasses(self):
        """Verify that no permission bypasses are used in business logic."""
        import inspect

        from verenigingen.utils import account_creation_manager

        business_functions = [
            "queue_bulk_account_creation_for_members",
            "process_bulk_account_creation_batch",
        ]

        for func_name in business_functions:
            func = getattr(account_creation_manager, func_name, None)
            if func:
                func_source = inspect.getsource(func)
                bypass_pattern = "ignore_permissions=" + "True"
                self.assertNotIn(
                    bypass_pattern,
                    func_source,
                    f"Function {func_name} should not bypass permissions",
                )

    def test_audit_trail_completeness(self):
        """Test that all operations create proper audit trails."""
        members = []
        for i in range(3):
            member = self.create_test_member(
                first_name="Audit",
                last_name=f"Trail{i}",
            )
            members.append(member.name)

        result = queue_bulk_account_creation_for_members(
            member_names=[m for m in members],
        )

        self.assertTrue(result["success"], f"Audit trail test should succeed: {result}")
        self.assertEqual(result["data"]["requests_created"], 3)

        for request_name in result["data"].get("request_names", []):
            request = frappe.get_doc("Account Creation Request", request_name)
            self.assertIsNotNone(request.creation)
            self.assertIsNotNone(request.owner)
            self.assertEqual(request.status, "Requested")
            self.assertIsNotNone(request.business_justification)

        tracker = frappe.get_doc("Bulk Operation Tracker", result["data"]["tracker_name"])
        self.assertIsNotNone(tracker.started_at)
        self.assertEqual(tracker.operation_type, "Account Creation")
