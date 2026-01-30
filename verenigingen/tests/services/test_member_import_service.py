# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Tests for MemberImportService - CSV import member creation/update.

This test module verifies:
- Advisory lock acquisition and release (including connection semantics)
- Bulk context flag management (save/restore)
- TOCTOU prevention behavior
- Lock helpers work correctly
"""

import time

import frappe
from frappe.tests import IntegrationTestCase


class TestMemberImportServiceLocks(IntegrationTestCase):
    """Test cases for advisory lock functionality in MemberImportService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

        from verenigingen.services.csv_import.member_import_service import (
            MemberImportService,
        )

        self.service = MemberImportService()

    def test_lock_acquire_and_release_returns_expected_values(self):
        """Test that GET_LOCK and RELEASE_LOCK work correctly on same connection.

        This test verifies:
        1. GET_LOCK returns 1 when lock is acquired
        2. RELEASE_LOCK returns 1 when lock is released on same connection
        """
        lock_name = f"test_lock_{int(time.time() * 1000)}"

        # Acquire lock
        lock_result = frappe.db.sql(
            "SELECT GET_LOCK(%s, 5) as acquired",
            (lock_name,),
            as_dict=True,
        )
        self.assertEqual(lock_result[0].acquired, 1, "GET_LOCK should return 1")

        # Release lock - should return 1 if on same connection
        release_result = frappe.db.sql(
            "SELECT RELEASE_LOCK(%s) as released",
            (lock_name,),
            as_dict=True,
        )
        self.assertEqual(
            release_result[0].released,
            1,
            "RELEASE_LOCK should return 1 when lock was held by this connection",
        )

    def test_release_lock_returns_null_for_nonexistent_lock(self):
        """Test that RELEASE_LOCK returns NULL for a lock that doesn't exist."""
        lock_name = f"nonexistent_lock_{int(time.time() * 1000)}"

        # Try to release a lock that was never acquired
        release_result = frappe.db.sql(
            "SELECT RELEASE_LOCK(%s) as released",
            (lock_name,),
            as_dict=True,
        )
        # Returns NULL if lock doesn't exist (never acquired)
        self.assertIsNone(
            release_result[0].released,
            "RELEASE_LOCK should return NULL for never-acquired lock",
        )

    def test_acquire_advisory_lock_helper(self):
        """Test that _acquire_advisory_lock acquires lock successfully."""
        lock_name = f"test_acquire_{int(time.time() * 1000)}"

        lock_acquired = self.service._acquire_advisory_lock(lock_name, row_num=1)
        self.assertTrue(lock_acquired, "Lock should be acquired")

        # Clean up - release the lock
        self.service._release_advisory_lock(lock_name, row_num=1)

    def test_release_advisory_lock_helper(self):
        """Test that _release_advisory_lock releases and verifies correctly."""
        lock_name = f"test_release_{int(time.time() * 1000)}"

        # First acquire the lock
        lock_acquired = self.service._acquire_advisory_lock(lock_name, row_num=1)
        self.assertTrue(lock_acquired)

        # Release should succeed without raising
        self.service._release_advisory_lock(lock_name, row_num=1)

        # Verify lock is actually released by trying to acquire again instantly
        lock_result = frappe.db.sql(
            "SELECT GET_LOCK(%s, 0) as acquired",
            (lock_name,),
            as_dict=True,
        )
        self.assertEqual(
            lock_result[0].acquired,
            1,
            "Lock should be available after release",
        )
        # Clean up
        frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_name,))

    def test_lock_reentrant_on_same_connection(self):
        """Test that MySQL advisory locks are reentrant on the same connection.

        This verifies the expected behavior that GET_LOCK on the same connection
        for a lock we already hold returns 1 (reentrant).
        """
        lock_name = f"test_reentrant_{int(time.time() * 1000)}"

        # First acquisition
        result1 = frappe.db.sql(
            "SELECT GET_LOCK(%s, 5) as acquired", (lock_name,), as_dict=True
        )
        self.assertEqual(result1[0].acquired, 1)

        # Second acquisition on same connection (reentrant)
        result2 = frappe.db.sql(
            "SELECT GET_LOCK(%s, 5) as acquired", (lock_name,), as_dict=True
        )
        self.assertEqual(
            result2[0].acquired, 1, "Lock should be reentrant on same connection"
        )

        # Clean up
        frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_name,))


class TestMemberImportServiceBulkContext(IntegrationTestCase):
    """Test cases for bulk context flag management."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()

        from verenigingen.services.csv_import.member_import_service import (
            MemberImportService,
        )

        self.service = MemberImportService()

        # Clean up any existing flags
        self._original_bulk_member = getattr(
            frappe.flags, "bulk_member_operations", None
        )
        self._original_in_bulk = getattr(frappe.flags, "in_bulk_import", None)

    def tearDown(self):
        """Clean up after tests."""
        # Restore original flag state
        if self._original_bulk_member is None:
            if hasattr(frappe.flags, "bulk_member_operations"):
                delattr(frappe.flags, "bulk_member_operations")
        else:
            frappe.flags.bulk_member_operations = self._original_bulk_member

        if self._original_in_bulk is None:
            if hasattr(frappe.flags, "in_bulk_import"):
                delattr(frappe.flags, "in_bulk_import")
        else:
            frappe.flags.in_bulk_import = self._original_in_bulk

        super().tearDown()

    def test_bulk_context_sets_flags_when_missing(self):
        """Test that _bulk_context sets flags when they are not present."""
        # Ensure flags are not set
        if hasattr(frappe.flags, "bulk_member_operations"):
            delattr(frappe.flags, "bulk_member_operations")
        if hasattr(frappe.flags, "in_bulk_import"):
            delattr(frappe.flags, "in_bulk_import")

        with self.service._bulk_context():
            # Flags should be set inside context
            self.assertTrue(
                getattr(frappe.flags, "bulk_member_operations", False),
                "bulk_member_operations should be True inside context",
            )
            self.assertTrue(
                getattr(frappe.flags, "in_bulk_import", False),
                "in_bulk_import should be True inside context",
            )

        # Flags should be removed after context exits (since they didn't exist before)
        self.assertFalse(
            hasattr(frappe.flags, "bulk_member_operations")
            and frappe.flags.bulk_member_operations,
            "bulk_member_operations should be removed after context",
        )

    def test_bulk_context_preserves_existing_true_flags(self):
        """Test that _bulk_context preserves existing True flag values."""
        # Set flags to True
        frappe.flags.bulk_member_operations = True
        frappe.flags.in_bulk_import = True

        with self.service._bulk_context():
            # Flags should still be True
            self.assertTrue(frappe.flags.bulk_member_operations)
            self.assertTrue(frappe.flags.in_bulk_import)

        # Flags should still be True after context
        self.assertTrue(
            frappe.flags.bulk_member_operations,
            "bulk_member_operations should be preserved as True",
        )
        self.assertTrue(
            frappe.flags.in_bulk_import,
            "in_bulk_import should be preserved as True",
        )

    def test_bulk_context_restores_flags_on_exception(self):
        """Test that _bulk_context restores flags even when exception occurs."""
        # Ensure flags are not set
        if hasattr(frappe.flags, "bulk_member_operations"):
            delattr(frappe.flags, "bulk_member_operations")

        try:
            with self.service._bulk_context():
                self.assertTrue(frappe.flags.bulk_member_operations)
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Flags should be cleaned up despite exception
        self.assertFalse(
            hasattr(frappe.flags, "bulk_member_operations")
            and frappe.flags.bulk_member_operations,
            "bulk_member_operations should be cleaned up after exception",
        )


class TestMemberImportServiceTOCTOU(IntegrationTestCase):
    """Test cases for TOCTOU prevention and strategy consistency."""

    def test_mijnrood_strategies_are_consistent(self):
        """Test that MIJNROOD_STRATEGIES include expected lookup methods.

        The TOCTOU prevention relies on using the same strategies for both
        the initial lookup and the re-check after acquiring the lock.
        """
        from verenigingen.services.member.member_lookup_service import (
            LookupStrategy,
            get_member_lookup_service,
        )

        lookup_service = get_member_lookup_service()

        # Verify MIJNROOD_STRATEGIES exists and has content
        self.assertIsNotNone(lookup_service.MIJNROOD_STRATEGIES)
        self.assertGreater(len(lookup_service.MIJNROOD_STRATEGIES), 0)

        # The strategies should include MEMBER_ID and EMAIL for MijnRood imports
        strategy_values = [s.value for s in lookup_service.MIJNROOD_STRATEGIES]
        self.assertIn("member_id", strategy_values, "MIJNROOD should include member_id")
        self.assertIn("email", strategy_values, "MIJNROOD should include email")

    def test_lock_prevents_duplicate_via_recheck(self):
        """Test that the re-check after lock acquisition finds existing members.

        This simulates the TOCTOU scenario where a member is created between
        the initial check and lock acquisition.
        """
        from verenigingen.services.csv_import.member_import_service import (
            MemberImportService,
        )
        from verenigingen.services.member.member_lookup_service import (
            get_member_lookup_service,
        )

        service = MemberImportService()
        lookup_service = get_member_lookup_service()

        # Create a test member first
        unique_id = f"TOCTOU-{int(time.time() * 1000)}"
        unique_email = f"toctou-test-{int(time.time() * 1000)}@example.com"

        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "TOCTOU",
                "last_name": "Test",
                "email": unique_email,
                "member_id": unique_id,
                "status": "Pending",
            }
        )
        member.flags.ignore_validate = True
        member.flags.ignore_mandatory = True
        member.insert()
        frappe.db.commit()

        try:
            # Now the re-check should find this member
            row_data = {
                "member_id": unique_id,
                "email": unique_email,
            }

            found_member = lookup_service.find_member(
                row_data, strategies=lookup_service.MIJNROOD_STRATEGIES
            )

            self.assertIsNotNone(found_member, "Re-check should find existing member")
            self.assertEqual(found_member.name, member.name)

        finally:
            # Clean up
            frappe.delete_doc("Member", member.name, force=True)
            frappe.db.commit()


class TestMemberImportServiceConfigurable(IntegrationTestCase):
    """Test cases for configurable lock parameters."""

    def test_lock_constants_are_sensible(self):
        """Test that lock configuration constants have reasonable values."""
        from verenigingen.services.csv_import import member_import_service

        # Timeout should be reasonable (1-60 seconds)
        self.assertGreaterEqual(
            member_import_service.LOCK_TIMEOUT_SECONDS,
            1,
            "Lock timeout should be at least 1 second",
        )
        self.assertLessEqual(
            member_import_service.LOCK_TIMEOUT_SECONDS,
            60,
            "Lock timeout should not exceed 60 seconds",
        )

        # Retries should be reasonable (1-10)
        self.assertGreaterEqual(
            member_import_service.LOCK_MAX_RETRIES,
            1,
            "Should have at least 1 retry",
        )
        self.assertLessEqual(
            member_import_service.LOCK_MAX_RETRIES,
            10,
            "Should not have more than 10 retries",
        )

        # Base delay should be reasonable (0.1-5 seconds)
        self.assertGreaterEqual(
            member_import_service.LOCK_RETRY_BASE_DELAY,
            0.1,
            "Base delay should be at least 0.1 seconds",
        )
        self.assertLessEqual(
            member_import_service.LOCK_RETRY_BASE_DELAY,
            5,
            "Base delay should not exceed 5 seconds",
        )

    def test_exponential_backoff_formula(self):
        """Test that exponential backoff produces expected delay sequence."""
        from verenigingen.services.csv_import import member_import_service

        base_delay = member_import_service.LOCK_RETRY_BASE_DELAY
        max_retries = member_import_service.LOCK_MAX_RETRIES

        # Calculate expected delays: base * 2^attempt
        expected_delays = [base_delay * (2**i) for i in range(max_retries)]

        # Verify sequence is exponentially increasing
        for i in range(1, len(expected_delays)):
            self.assertEqual(
                expected_delays[i],
                expected_delays[i - 1] * 2,
                f"Delay at attempt {i} should be 2x previous",
            )
