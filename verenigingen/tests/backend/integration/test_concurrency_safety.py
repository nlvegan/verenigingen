# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Concurrency Safety Tests

Tests to verify that critical operations are safe under concurrent execution:
- Member ID assignment doesn't produce duplicates
- Application approve/reject is atomic (only one actor succeeds)

These tests use threading to simulate concurrent access.

Note: frappe.init() and frappe.connect() calls in thread workers are required because
Frappe's database connection and session context are thread-local. This is test
infrastructure, not permission bypass.

test-quality-enforcer: exempt-thread-context-setup
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import frappe

from verenigingen.services.member.core.member_lifecycle_service import MemberLifecycleService
from verenigingen.services.member.identification.member_id_service import MemberIDService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _create_thread_context(site: str):
    """Factory method to set up Frappe context for a worker thread.

    Frappe's session is thread-local, so each worker thread needs its own
    database connection and user context. This is test infrastructure,
    not permission bypass.

    Args:
        site: The Frappe site name to initialize
    """
    # Initialize Frappe for this thread with a new database connection
    frappe.init(site=site, force=True)
    frappe.connect()
    frappe.set_user("Administrator")


def _cleanup_thread_context():
    """Clean up Frappe context after thread work is done."""
    try:
        frappe.db.commit()
    except Exception:
        pass
    try:
        frappe.destroy()
    except Exception:
        pass


class TestMemberIDConcurrency(EnhancedTestCase):
    """Test member ID assignment under concurrent execution."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.uid = str(int(time.time() * 1000))[-6:]
        self.created_members = []
        # Capture site name for threads
        self.site = frappe.local.site

    def tearDown(self):
        """Clean up test data."""
        for member_name in self.created_members:
            try:
                if frappe.db.exists("Member", member_name):
                    frappe.delete_doc("Member", member_name, force=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _create_member_without_id(self, suffix: str) -> str:
        """Create a test member without a member_id.

        Note: The before_save hook automatically assigns member_id during insert(),
        so we clear it afterwards using db_set to create the test condition.
        """
        member = frappe.new_doc("Member")
        member.first_name = f"ConcurrencyTest{self.uid}"
        member.last_name = f"Member{suffix}"
        member.email = f"concurrency.test.{self.uid}.{suffix}@test.invalid"
        member.status = "Active"  # Eligible for member ID
        member.application_status = "Approved"
        member.insert(ignore_permissions=True)
        self.created_members.append(member.name)
        # Clear the auto-assigned member_id to create the test condition
        frappe.db.set_value("Member", member.name, "member_id", None, update_modified=False)
        frappe.db.commit()
        return member.name

    def test_concurrent_member_id_assignment_no_duplicates(self):
        """Test that concurrent ID assignment doesn't produce duplicate IDs."""
        # Create multiple members without IDs
        num_members = 5
        member_names = [self._create_member_without_id(str(i)) for i in range(num_members)]
        site = self.site  # Capture for closure

        assigned_ids = []
        errors = []
        lock = threading.Lock()

        def assign_id(member_name):
            """Assign member ID in a thread."""
            try:
                _create_thread_context(site)
                service = MemberIDService()
                result = service.assign_member_id(member_name)
                if result.success:
                    with lock:
                        assigned_ids.append(result.data)
                else:
                    with lock:
                        errors.append(f"{member_name}: {result.error_message}")
            except Exception as e:
                with lock:
                    errors.append(f"{member_name}: {str(e)}")
            finally:
                _cleanup_thread_context()

        # Execute assignments concurrently
        with ThreadPoolExecutor(max_workers=num_members) as executor:
            futures = [executor.submit(assign_id, name) for name in member_names]
            for future in as_completed(futures):
                pass  # Wait for all to complete

        # Verify no duplicate IDs
        self.assertEqual(
            len(assigned_ids),
            len(set(assigned_ids)),
            f"Duplicate IDs found: {assigned_ids}",
        )

        # All members should have been assigned (or have valid errors)
        total_processed = len(assigned_ids) + len(errors)
        self.assertEqual(total_processed, num_members, f"Not all members processed. Errors: {errors}")

    def test_bulk_assignment_lock_prevents_concurrent_runs(self):
        """Test that advisory lock prevents concurrent bulk assignments.

        This test verifies that the advisory lock mechanism works correctly.
        Due to timing, different scenarios can occur:
        1. Thread 1 gets lock, assigns IDs, others wait and get lock (no contention)
        2. Thread 1 gets lock, Thread 2/3 timeout waiting for lock (contention)
        3. Thread 1 assigns all IDs, Thread 2/3 find no work to do

        All these are valid outcomes. The key invariant is that no errors occur
        except for expected ones (lock timeout or no members to process).
        """
        # Create members for bulk assignment
        for i in range(3):
            self._create_member_without_id(f"bulk{i}")

        site = self.site  # Capture for closure
        results = []
        errors = []
        lock = threading.Lock()

        def run_bulk_assignment(thread_id):
            """Run bulk assignment in a thread."""
            try:
                _create_thread_context(site)
                service = MemberIDService()
                result = service.assign_missing_member_ids()
                with lock:
                    results.append({
                        "thread": thread_id,
                        "success": result.success,
                        "error_code": result.error_code,
                        "data": result.data if result.success else None,
                    })
            except Exception as e:
                with lock:
                    errors.append(f"Thread {thread_id}: {str(e)}")
            finally:
                _cleanup_thread_context()

        # Execute bulk assignments concurrently
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_bulk_assignment, i) for i in range(3)]
            for future in as_completed(futures):
                pass

        # All threads should complete without unexpected exceptions
        self.assertEqual(len(errors), 0, f"Unexpected exceptions: {errors}")
        self.assertEqual(len(results), 3, f"Not all threads returned results: {results}")

        # At least one should succeed with actual assignments
        successful_with_assignments = [
            r for r in results
            if r["success"] and r.get("data", {}).get("assigned", 0) > 0
        ]
        self.assertGreaterEqual(
            len(successful_with_assignments), 1,
            f"At least one thread should have assigned IDs. Results: {results}"
        )

        # Valid outcomes for other threads:
        # - success=True with assigned=0 (no members left to process)
        # - success=False with error_code="MEMBER_ID_LOCK_FAILED" (lock timeout)
        # - success=False with no error_code (no eligible members found)
        lock_failures = [r for r in results if r.get("error_code") == "MEMBER_ID_LOCK_FAILED"]

        # Total assigned across all threads should equal the number of members created
        total_assigned = sum(
            r.get("data", {}).get("assigned", 0)
            for r in results if r.get("data")
        )
        self.assertEqual(total_assigned, 3, f"Expected 3 total assignments. Results: {results}")


class TestApplicationApprovalConcurrency(EnhancedTestCase):
    """Test application approval/rejection under concurrent execution."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.uid = str(int(time.time() * 1000))[-6:]
        self.created_members = []
        self.lifecycle_service = MemberLifecycleService()
        # Capture site name for threads
        self.site = frappe.local.site

    def tearDown(self):
        """Clean up test data."""
        for member_name in self.created_members:
            try:
                if frappe.db.exists("Member", member_name):
                    frappe.delete_doc("Member", member_name, force=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _create_pending_application(self, suffix: str) -> str:
        """Create a pending application member."""
        member = frappe.new_doc("Member")
        member.first_name = f"ApprovalTest{self.uid}"
        member.last_name = f"Member{suffix}"
        member.email = f"approval.test.{self.uid}.{suffix}@test.invalid"
        member.status = "Pending"
        member.application_status = "Pending"
        member.application_id = f"APP-{self.uid}-{suffix}"
        member.insert(ignore_permissions=True)
        self.created_members.append(member.name)
        frappe.db.commit()
        return member.name

    def test_concurrent_approval_only_one_succeeds(self):
        """Test that concurrent approval of same member only allows one to succeed."""
        # Create a single pending member
        member_name = self._create_pending_application("concurrent")
        site = self.site  # Capture for closure

        results = []
        lock = threading.Lock()

        def try_approve(thread_id):
            """Try to approve the member in a thread."""
            try:
                _create_thread_context(site)
                service = MemberLifecycleService()
                member = frappe.get_doc("Member", member_name)
                result = service.approve_application(member)
                with lock:
                    results.append({
                        "thread": thread_id,
                        "success": result.success,
                        "error_code": result.error_code,
                        "member_id": result.data if result.success else None,
                    })
            except Exception as e:
                with lock:
                    results.append({"thread": thread_id, "success": False, "error": str(e)})
            finally:
                _cleanup_thread_context()

        # Execute approvals concurrently
        num_threads = 5
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(try_approve, i) for i in range(num_threads)]
            for future in as_completed(futures):
                pass

        # Exactly one should succeed
        successful = [r for r in results if r["success"]]
        already_approved = [r for r in results if r.get("error_code") == "ALREADY_APPROVED"]

        self.assertEqual(len(successful), 1, f"Exactly one approval should succeed. Results: {results}")
        self.assertEqual(
            len(already_approved),
            num_threads - 1,
            f"Others should get ALREADY_APPROVED. Results: {results}",
        )

        # Verify the member is actually approved
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.status, "Active")
        self.assertIsNotNone(member.member_id)

    def test_concurrent_rejection_only_one_succeeds(self):
        """Test that concurrent rejection of same member only allows one to succeed."""
        # Create a single pending member
        member_name = self._create_pending_application("reject")
        site = self.site  # Capture for closure

        results = []
        lock = threading.Lock()

        def try_reject(thread_id):
            """Try to reject the member in a thread."""
            try:
                _create_thread_context(site)
                service = MemberLifecycleService()
                member = frappe.get_doc("Member", member_name)
                result = service.reject_application(member, f"Rejected by thread {thread_id}")
                with lock:
                    results.append({
                        "thread": thread_id,
                        "success": result.success,
                        "error_code": result.error_code,
                    })
            except Exception as e:
                with lock:
                    results.append({"thread": thread_id, "success": False, "error": str(e)})
            finally:
                _cleanup_thread_context()

        # Execute rejections concurrently
        num_threads = 5
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(try_reject, i) for i in range(num_threads)]
            for future in as_completed(futures):
                pass

        # Exactly one should succeed
        successful = [r for r in results if r["success"]]
        already_processed = [r for r in results if r.get("error_code") == "ALREADY_PROCESSED"]

        self.assertEqual(len(successful), 1, f"Exactly one rejection should succeed. Results: {results}")
        self.assertEqual(
            len(already_processed),
            num_threads - 1,
            f"Others should get ALREADY_PROCESSED. Results: {results}",
        )

        # Verify the member is actually rejected
        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Rejected")
        self.assertEqual(member.status, "Rejected")

    def test_approve_then_reject_fails(self):
        """Test that rejecting an already approved member fails."""
        # Create and approve a member
        member_name = self._create_pending_application("approve_first")
        member = frappe.get_doc("Member", member_name)

        # Approve first
        approve_result = self.lifecycle_service.approve_application(member)
        self.assertTrue(approve_result.success)
        frappe.db.commit()

        # Try to reject
        member.reload()
        reject_result = self.lifecycle_service.reject_application(member, "Should fail")

        self.assertFalse(reject_result.success)
        self.assertEqual(reject_result.error_code, "ALREADY_PROCESSED")
