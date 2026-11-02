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
from unittest.mock import patch

import frappe

from verenigingen.api.membership_application_review import approve_application, reject_application
from verenigingen.services.member.identification.member_id_service import MemberIDService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase
from verenigingen.tests.setup import ensure_member_test_masters

SUBMISSION = "Membership Application Submission"


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
        # Seed ERPNext + Verenigingen base masters (Company, CoA, Territory,
        # Verenigingen Settings.company/creation_user). CI's before_tests seeds
        # these; a single-module run does not, so on a clean snapshot member
        # creation and the approval invoice path fail. Idempotent / cheap no-op.
        ensure_member_test_masters()
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


class TestApplicationApprovalConcurrency(ApprovalCase):
    """Test application approval/rejection under concurrent execution.

    Driven through the real flow (submit -> confirm -> approve_application / reject_application) on a
    Membership Application Submission; the member-keyed endpoints these tests used to race were removed
    in #1765. approve_application serialises on an advisory lock per application and refuses a second
    call once the application is no longer Pending Review, so the guarantee is "exactly one actor
    succeeds, the others are refused".
    """

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        # Seed base masters so the approval path (which creates a membership
        # invoice and reads Verenigingen Settings.company) works under an
        # isolated single-module run on a clean snapshot. Idempotent.
        ensure_member_test_masters()
        # Capture site name for threads
        self.site = frappe.local.site

    def tearDown(self):
        """Clean up test data: the Member a thread's approval created is on another connection."""
        for member_name in frappe.get_all("Member", {"email": self.email}, pluck="name"):
            try:
                frappe.delete_doc("Member", member_name, force=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _create_confirmed_application(self) -> str:
        """A Pending Review application, committed so the worker threads' own connections can see it."""
        name = self._stage_and_confirm()
        frappe.db.commit()
        return name

    def _run_in_threads(self, work, num_threads=5):
        """Run work(thread_id) on `num_threads` threads, each with its own Frappe context.

        Returns [{"thread", "response"} | {"thread", "error"}].
        """
        site = self.site
        results = []
        lock = threading.Lock()

        def run(thread_id):
            try:
                _create_thread_context(site)
                response = work(thread_id)
                with lock:
                    results.append({"thread": thread_id, "response": response})
            except Exception as e:
                with lock:
                    results.append({"thread": thread_id, "error": str(e)})
            finally:
                _cleanup_thread_context()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(run, i) for i in range(num_threads)]
            for future in as_completed(futures):
                pass
        return results

    def test_concurrent_approval_idempotent_no_duplicate_memberships(self):
        """Concurrent approvals of the same application must not create duplicate
        Memberships or Members, and exactly one of them wins."""
        name = self._create_confirmed_application()

        results = self._run_in_threads(lambda thread_id: approve_application(name, create_invoice=False))

        winners = [r for r in results if r.get("response", {}).get("success")]
        self.assertEqual(len(winners), 1, f"exactly one approval must win. Results: {results}")

        members = frappe.get_all("Member", {"email": self.email}, pluck="name")
        self.assertEqual(len(members), 1, f"one Member for the applicant. Results: {results}")
        memberships = frappe.get_all("Membership", filters={"member": members[0]})
        self.assertLessEqual(
            len(memberships),
            1,
            f"At most one Membership should exist for {members[0]}. Found {len(memberships)}. Results: {results}",
        )

        member = frappe.get_doc("Member", members[0])
        self.assertEqual(member.application_status, "Approved")
        self.assertEqual(member.status, "Active")
        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Approved")

    def test_concurrent_rejection_idempotent_no_duplicate_state(self):
        """Concurrent rejections of the same application must end in the Rejected state, one winning,
        and must not create a Member."""
        name = self._create_confirmed_application()

        with patch("frappe.sendmail"):  # Mock justified: External Service - SMTP delivery
            results = self._run_in_threads(
                lambda thread_id: reject_application(name, reason=f"Rejected by thread {thread_id}")
            )

        winners = [r for r in results if r.get("response", {}).get("success")]
        self.assertEqual(len(winners), 1, f"exactly one rejection must win. Results: {results}")
        self.assertEqual(
            frappe.db.get_value(SUBMISSION, name, "status"),
            "Rejected",
            f"Application should be Rejected after concurrent rejections. Results: {results}",
        )
        self.assertEqual(frappe.db.count("Member", {"email": self.email}), 0)

    def test_approve_then_reject_fails(self):
        """Approving then trying to reject must keep the application Approved and the Member Active."""
        name = self._create_confirmed_application()
        with patch("frappe.sendmail"):  # Mock justified: External Service - SMTP delivery
            approve_application(name, create_invoice=False)
        frappe.db.commit()

        # Try to reject - should fail (already approved).
        with self.assertRaises(Exception):
            reject_application(name, reason="Should fail")

        self.assertEqual(frappe.db.get_value(SUBMISSION, name, "status"), "Approved")
        member = frappe.get_doc("Member", {"email": self.email})
        self.assertEqual(member.application_status, "Approved")
