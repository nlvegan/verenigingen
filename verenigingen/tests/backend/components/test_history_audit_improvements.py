"""
Test Suite for History Audit Improvements

Tests the improvements implemented based on the code audit findings:
1. Error codes in OperationResult pattern
2. Donor-member reconciliation with duplicate handling
3. Volunteer assignment query caching

Related audit items:
- P0.2: Error codes and monitoring
- P1.3: Donor-member mapping hardening
- P2.5: Request-level caching
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestOperationResultErrorCodes(FrappeTestCase):
    """Test error codes in OperationResult pattern"""

    def test_operation_result_fail_with_error_code(self):
        """Verify OperationResult.fail() accepts and stores error_code"""
        from verenigingen.utils.operation_result import OperationResult

        result = OperationResult.fail(
            "Test error message",
            errors=["Detail 1", "Detail 2"],
            error_code="HIST_001",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Test error message")
        self.assertEqual(result.error_code, "HIST_001")
        self.assertEqual(len(result.errors), 2)

    def test_operation_result_to_dict_includes_error_code(self):
        """Verify to_dict() includes error_code when present"""
        from verenigingen.utils.operation_result import OperationResult

        result = OperationResult.fail(
            "Test error",
            error_code="CLEANUP_001",
        )

        # Legacy flat schema exposes error_code at top level; the default
        # nested schema places it under error["code"]. Verify both contracts.
        flat_dict = result.to_dict(nested=False)
        self.assertIn("error_code", flat_dict)
        self.assertEqual(flat_dict["error_code"], "CLEANUP_001")

        nested_dict = result.to_dict()
        self.assertEqual(nested_dict["error"]["code"], "CLEANUP_001")

    def test_operation_result_chain_preserves_error_code(self):
        """Verify chain() preserves error_code from original result"""
        from verenigingen.utils.operation_result import OperationResult

        original = OperationResult.fail(
            "Original error",
            error_code="HIST_002",
        )

        chained = original.chain("Wrapped error with context")

        self.assertEqual(chained.error_code, "HIST_002")
        self.assertEqual(chained.error_message, "Wrapped error with context")

    def test_operation_result_ok_has_no_error_code(self):
        """Verify successful results have None error_code"""
        from verenigingen.utils.operation_result import OperationResult

        result = OperationResult.ok({"data": "value"})

        self.assertTrue(result.success)
        self.assertIsNone(result.error_code)


class TestErrorCodeRegistry(FrappeTestCase):
    """Test error code registry and utilities"""

    def test_all_error_codes_have_descriptions(self):
        """Verify all registered error codes have descriptions"""
        from verenigingen.utils.error_codes import ALL_ERROR_CODES

        # All codes should have non-empty descriptions
        for code, description in ALL_ERROR_CODES.items():
            self.assertTrue(len(description) > 0, f"Code {code} has empty description")

    def test_get_error_description_known_code(self):
        """Verify get_error_description returns correct description"""
        from verenigingen.utils.error_codes import get_error_description

        description = get_error_description("HIST_001")
        self.assertEqual(description, "Donation history sync failed")

    def test_get_error_description_unknown_code(self):
        """Verify get_error_description handles unknown codes"""
        from verenigingen.utils.error_codes import get_error_description

        description = get_error_description("UNKNOWN_999")
        self.assertIn("Unknown error code", description)

    def test_history_error_codes_defined(self):
        """Verify all expected history error codes exist"""
        from verenigingen.utils.error_codes import HISTORY_ERROR_CODES

        expected_codes = [
            "HIST_001",  # Donation history sync
            "HIST_002",  # Payment reference prefetch
            "HIST_003",  # Dues payment history
            "HIST_004",  # Invoice payment history
            "HIST_005",  # Volunteer expense history
            "HIST_006",  # Fee change history refresh
            "HIST_007",  # Member document save
            "HIST_008",  # Volunteer expense cleanup
        ]

        for code in expected_codes:
            self.assertIn(code, HISTORY_ERROR_CODES, f"Missing code: {code}")


class TestDonorMemberReconciliation(FrappeTestCase):
    """Test donor-member reconciliation with duplicate handling"""

    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.test_email = f"test.donor.{frappe.generate_hash(length=8)}@example.com"

    def tearDown(self):
        """Clean up test data"""
        # Clean up any test donors created
        frappe.db.delete("Donor", {"donor_email": self.test_email})
        frappe.db.commit()
        super().tearDown()

    def test_get_donor_for_member_no_donor(self):
        """Verify returns None when no donor exists"""
        from verenigingen.utils.donor_member_reconciliation import get_donor_for_member

        # Create a mock member object
        class MockMember:
            name = "TEST-MEM-001"
            email = self.test_email
            donor = None

        result = get_donor_for_member(MockMember())
        self.assertIsNone(result)

    def test_get_donor_for_member_single_donor(self):
        """Verify returns donor when single match exists"""
        from verenigingen.utils.donor_member_reconciliation import get_donor_for_member

        # Create test donor
        donor = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": "Test Donor Single",
                "donor_email": self.test_email,
                "donor_type": "Individual",
            }
        ).insert()

        class MockMember:
            name = "TEST-MEM-002"
            email = self.test_email
            donor = None

        result = get_donor_for_member(MockMember())
        self.assertEqual(result, donor.name)

    def test_get_donor_for_member_multiple_donors_returns_most_recent(self):
        """Verify returns most recent donor when multiple exist"""
        from verenigingen.utils.donor_member_reconciliation import get_donor_for_member

        # Create multiple donors with same email
        donor1 = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": "Test Donor First",
                "donor_email": self.test_email,
                "donor_type": "Individual",
            }
        ).insert()

        donor2 = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": "Test Donor Second",
                "donor_email": self.test_email,
                "donor_type": "Individual",
            }
        ).insert()

        class MockMember:
            name = "TEST-MEM-003"
            email = self.test_email
            donor = None

        result = get_donor_for_member(MockMember())

        # Should return the most recently created donor
        self.assertEqual(result, donor2.name)

    def test_get_all_donors_for_email_with_donation_counts(self):
        """Verify get_all_donors_for_email includes donation counts"""
        from verenigingen.utils.donor_member_reconciliation import get_all_donors_for_email

        # Create donor
        donor = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": "Test Donor Counts",
                "donor_email": self.test_email,
                "donor_type": "Individual",
            }
        ).insert()

        donors = get_all_donors_for_email(self.test_email)

        self.assertEqual(len(donors), 1)
        self.assertIn("donation_count", donors[0])
        self.assertEqual(donors[0]["donation_count"], 0)

    def test_check_donor_member_consistency(self):
        """Verify consistency check detects multiple donors"""
        from verenigingen.utils.donor_member_reconciliation import (
            check_donor_member_consistency,
            get_all_donors_for_email,
        )

        # Create multiple donors
        frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": "Consistency Test 1",
                "donor_email": self.test_email,
                "donor_type": "Individual",
            }
        ).insert()

        frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": "Consistency Test 2",
                "donor_email": self.test_email,
                "donor_type": "Individual",
            }
        ).insert()

        # Create a real member for testing
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Consistency",
                "last_name": "Test",
                "email": self.test_email,
            }
        ).insert()

        try:
            result = check_donor_member_consistency(member.name)

            self.assertFalse(result["consistent"])
            self.assertTrue(len(result["issues"]) > 0)
            self.assertTrue(any("Multiple donors" in issue for issue in result["issues"]))
        finally:
            frappe.delete_doc("Member", member.name, force=True)


class TestVolunteerAssignmentCaching(FrappeTestCase):
    """Test request-level caching for volunteer assignment queries"""

    def setUp(self):
        """Set up test data"""
        super().setUp()
        # Clear any existing cache
        if hasattr(frappe.local, "_volunteer_assignment_cache"):
            delattr(frappe.local, "_volunteer_assignment_cache")

    def tearDown(self):
        """Clean up"""
        if hasattr(frappe.local, "_volunteer_assignment_cache"):
            delattr(frappe.local, "_volunteer_assignment_cache")
        super().tearDown()

    def test_cache_is_created_on_first_query(self):
        """Verify cache is created when first query is made"""
        from verenigingen.services.volunteer.assignment_query_builder import (
            AssignmentQueryBuilder,
        )

        # Query for a non-existent volunteer (safe, won't fail)
        builder = AssignmentQueryBuilder("NON_EXISTENT_VOLUNTEER")

        # This will query but find nothing
        result = builder.get_all_active_assignments()

        # Cache should now exist
        self.assertTrue(hasattr(frappe.local, "_volunteer_assignment_cache"))

    def test_second_query_uses_cache(self):
        """Verify second query returns cached result"""
        from verenigingen.services.volunteer.assignment_query_builder import (
            AssignmentQueryBuilder,
        )

        builder = AssignmentQueryBuilder("TEST_CACHE_VOLUNTEER")

        # First query
        result1 = builder.get_all_active_assignments()

        # Modify cache to verify it's being used
        cache = frappe.local._volunteer_assignment_cache
        cache_key = "TEST_CACHE_VOLUNTEER:active_assignments"
        cache[cache_key] = [{"test": "cached_value"}]

        # Second query should return modified cache
        result2 = builder.get_all_active_assignments()

        self.assertEqual(result2, [{"test": "cached_value"}])

    def test_invalidate_cache_specific_volunteer(self):
        """Verify cache invalidation for specific volunteer"""
        from verenigingen.services.volunteer.assignment_query_builder import (
            AssignmentQueryBuilder,
            invalidate_volunteer_assignment_cache,
        )

        # Set up cache with multiple volunteers
        builder1 = AssignmentQueryBuilder("VOLUNTEER_1")
        builder2 = AssignmentQueryBuilder("VOLUNTEER_2")

        builder1.get_all_active_assignments()
        builder2.get_all_active_assignments()

        cache = frappe.local._volunteer_assignment_cache
        self.assertTrue(any("VOLUNTEER_1:" in k for k in cache.keys()))
        self.assertTrue(any("VOLUNTEER_2:" in k for k in cache.keys()))

        # Invalidate only VOLUNTEER_1
        invalidate_volunteer_assignment_cache("VOLUNTEER_1")

        # VOLUNTEER_1 should be gone, VOLUNTEER_2 should remain
        self.assertFalse(any("VOLUNTEER_1:" in k for k in cache.keys()))
        self.assertTrue(any("VOLUNTEER_2:" in k for k in cache.keys()))

    def test_invalidate_cache_all_volunteers(self):
        """Verify cache invalidation for all volunteers"""
        from verenigingen.services.volunteer.assignment_query_builder import (
            AssignmentQueryBuilder,
            invalidate_volunteer_assignment_cache,
        )

        # Set up cache
        builder = AssignmentQueryBuilder("VOLUNTEER_ALL")
        builder.get_all_active_assignments()

        # Invalidate all
        invalidate_volunteer_assignment_cache()

        cache = frappe.local._volunteer_assignment_cache
        self.assertEqual(len(cache), 0)

    def test_check_has_active_uses_cache(self):
        """Verify check_has_active_assignments uses cache"""
        from verenigingen.services.volunteer.assignment_query_builder import (
            AssignmentQueryBuilder,
        )

        builder = AssignmentQueryBuilder("TEST_HAS_ACTIVE")

        # First call
        result1 = builder.check_has_active_assignments()

        # Modify cache
        cache = frappe.local._volunteer_assignment_cache
        cache["TEST_HAS_ACTIVE:has_active"] = True

        # Second call should use cache
        result2 = builder.check_has_active_assignments()

        self.assertTrue(result2)
