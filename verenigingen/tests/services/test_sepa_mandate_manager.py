"""
Unit Tests for SEPAMandateManager Service

Tests the consolidated SEPA mandate management service to ensure:
- Mandate retrieval works correctly
- Mandate validation catches errors appropriately
- Mandate creation follows business rules
- Reference generation is unique and consistent
- IBAN change deactivation works correctly

Author: Verenigingen Development Team
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.payment.sepa_mandate_manager import (
    MandateInfo,
    SEPAMandateManager,
    get_sepa_mandate_manager,
)
from verenigingen.services.payment.validation_service import ValidationResult
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSEPAMandateManager(EnhancedTestCase):
    """Test suite for SEPAMandateManager service"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.manager = get_sepa_mandate_manager()

        # Create test member
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            birth_date="1990-01-01",
            email=f"test.member.{frappe.generate_hash(length=8)}@example.com",
        )

        # Test IBAN data
        self.valid_iban = "NL91ABNA0417164300"
        self.valid_iban_formatted = "NL91 ABNA 0417 1643 00"
        # Generate valid RABO IBAN with correct checksum
        from verenigingen.utils.validation.iban_validator import generate_test_iban
        self.alternative_iban = generate_test_iban("RABO", "0123456789")

    def tearDown(self):
        """Clean up test data"""
        # Cleanup is handled by EnhancedTestCase rollback
        super().tearDown()

    # ========== Mandate Retrieval Tests ==========

    def test_get_active_mandates_empty(self):
        """Test getting active mandates when none exist"""
        mandates = self.manager.get_active_mandates(self.test_member.name)
        self.assertEqual(len(mandates), 0)
        self.assertIsInstance(mandates, list)

    def test_get_active_mandates_with_data(self):
        """Test getting active mandates returns correct data"""
        # Create a test mandate
        mandate = self._create_test_mandate(self.test_member.name, self.valid_iban, status="Active", is_active=1)

        mandates = self.manager.get_active_mandates(self.test_member.name)

        self.assertEqual(len(mandates), 1)
        self.assertIsInstance(mandates[0], MandateInfo)
        self.assertEqual(mandates[0].member, self.test_member.name)
        self.assertEqual(mandates[0].status, "Active")
        self.assertTrue(mandates[0].is_active)

    def test_get_active_mandates_filters_inactive(self):
        """Test that inactive mandates are not returned"""
        # Create active and inactive mandates
        active_mandate = self._create_test_mandate(
            self.test_member.name, self.valid_iban, status="Active", is_active=1
        )
        inactive_mandate = self._create_test_mandate(
            self.test_member.name, self.alternative_iban, status="Cancelled", is_active=0
        )

        mandates = self.manager.get_active_mandates(self.test_member.name)

        self.assertEqual(len(mandates), 1)
        self.assertEqual(mandates[0].name, active_mandate.name)

    def test_get_active_mandates_with_iban_filter(self):
        """Test filtering mandates by IBAN"""
        # Create mandates with different IBANs. Second forced Active -- see
        # _force_second_active_mandate; #584 blocks the ordinary route.
        mandate1 = self._create_test_mandate(self.test_member.name, self.valid_iban, status="Active", is_active=1)
        mandate2 = self._force_second_active_mandate(self.test_member.name, self.alternative_iban)

        # Filter by first IBAN
        mandates = self.manager.get_active_mandates(self.test_member.name, iban=self.valid_iban)

        self.assertEqual(len(mandates), 1)
        # IBANs are stored formatted with spaces in the database
        self.assertEqual(mandates[0].iban, self.valid_iban_formatted)

    def test_get_default_mandate(self):
        """The member's one Active mandate is the default.

        This used to create two Active mandates and assert the most recent won.
        Since #584 a member may hold only one, so "most recent" no longer selects
        anything -- the assertion that matters is that the Active mandate is
        returned and the Cancelled one is not.
        """
        # ACTIVE FIRST, deliberately. `get_active_mandates` orders `creation desc`,
        # so creating the Cancelled one first would let creation order alone satisfy
        # the assertion below: measured, the test then passed with the status filter
        # deleted entirely. This ordering makes the status filter load-bearing.
        active = self._create_test_mandate(
            self.test_member.name, self.valid_iban, status="Active", is_active=1
        )
        cancelled = self._create_test_mandate(
            self.test_member.name, self.alternative_iban, status="Cancelled", is_active=0
        )

        default_mandate = self.manager.get_default_mandate(self.test_member.name)

        self.assertIsNotNone(default_mandate)
        self.assertIsInstance(default_mandate, MandateInfo)
        self.assertEqual(default_mandate.name, active.name)
        self.assertNotEqual(default_mandate.name, cancelled.name)

    def test_get_default_mandate_none_when_no_active(self):
        """Test default mandate returns None when no active mandates"""
        default_mandate = self.manager.get_default_mandate(self.test_member.name)
        self.assertIsNone(default_mandate)

    def test_has_active_mandate_memberships(self):
        """Test checking for active membership mandate"""
        # Create mandate for memberships
        mandate = self._create_test_mandate(
            self.test_member.name,
            self.valid_iban,
            status="Active",
            is_active=1,
            used_for_memberships=1,
            used_for_donations=0,
        )

        self.assertTrue(self.manager.has_active_mandate(self.test_member.name, purpose="memberships"))
        self.assertFalse(self.manager.has_active_mandate(self.test_member.name, purpose="donations"))

    def test_has_active_mandate_donations(self):
        """Test checking for active donation mandate"""
        # Create mandate for donations
        mandate = self._create_test_mandate(
            self.test_member.name,
            self.valid_iban,
            status="Active",
            is_active=1,
            used_for_memberships=0,
            used_for_donations=1,
        )

        self.assertFalse(self.manager.has_active_mandate(self.test_member.name, purpose="memberships"))
        self.assertTrue(self.manager.has_active_mandate(self.test_member.name, purpose="donations"))

    # ========== Mandate Validation Tests ==========

    def test_validate_mandate_creation_success(self):
        """Test successful mandate creation validation"""
        mandate_id = self.manager.generate_mandate_reference(self.test_member.name)

        result = self.manager.validate_mandate_creation(self.test_member.name, self.valid_iban, mandate_id)

        self.assertTrue(result.valid)
        self.assertIn("iban", result.data)
        self.assertEqual(result.data["iban"], self.valid_iban_formatted)

    def test_validate_mandate_creation_invalid_member(self):
        """Test validation fails for non-existent member"""
        result = self.manager.validate_mandate_creation("Invalid-Member-999", self.valid_iban, "M-999-20251014-001")

        self.assertFalse(result.valid)
        self.assertIn("does not exist", result.message)

    def test_validate_mandate_creation_invalid_iban(self):
        """Test validation fails for invalid IBAN"""
        result = self.manager.validate_mandate_creation(self.test_member.name, "INVALID_IBAN", "M-001-20251014-001")

        self.assertFalse(result.valid)
        self.assertGreater(len(result.errors), 0)

    def test_validate_mandate_creation_duplicate_mandate_id(self):
        """Test validation fails for duplicate mandate ID"""
        # Create existing mandate
        existing_mandate = self._create_test_mandate(self.test_member.name, self.valid_iban)
        existing_id = existing_mandate.mandate_id

        result = self.manager.validate_mandate_creation(self.test_member.name, self.alternative_iban, existing_id)

        self.assertFalse(result.valid)
        self.assertIn("already exists", result.message)

    def test_validate_mandate_creation_duplicate_iban_blocked(self):
        """Test validation fails for duplicate IBAN by default"""
        # Create existing mandate with same IBAN
        existing_mandate = self._create_test_mandate(
            self.test_member.name, self.valid_iban, status="Active", is_active=1
        )

        new_mandate_id = self.manager.generate_mandate_reference(self.test_member.name)
        result = self.manager.validate_mandate_creation(self.test_member.name, self.valid_iban, new_mandate_id)

        self.assertFalse(result.valid)
        self.assertIn("already exists for this IBAN", result.message)

    def test_validate_mandate_creation_duplicate_iban_allowed(self):
        """Test validation succeeds when duplicate IBAN is explicitly allowed"""
        # Create existing mandate
        existing_mandate = self._create_test_mandate(
            self.test_member.name, self.valid_iban, status="Active", is_active=1
        )

        new_mandate_id = self.manager.generate_mandate_reference(self.test_member.name)
        result = self.manager.validate_mandate_creation(
            self.test_member.name, self.valid_iban, new_mandate_id, allow_duplicate_iban=True
        )

        self.assertTrue(result.valid)

    # ========== Mandate Reference Generation Tests ==========

    def test_generate_mandate_reference_format(self):
        """Test mandate reference follows correct format"""
        reference = self.manager.generate_mandate_reference(self.test_member.name, member_id="001")

        # Format: M-{member_id}-{YYYYMMDD}-{sequence}
        self.assertTrue(reference.startswith("M-001-"))
        parts = reference.split("-")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "M")
        self.assertEqual(parts[1], "001")
        self.assertEqual(len(parts[2]), 8)  # YYYYMMDD
        self.assertEqual(len(parts[3]), 3)  # 3-digit sequence

    def test_generate_mandate_reference_increments_sequence(self):
        """Test mandate reference sequence increments correctly"""
        member_id = self.test_member.member_id or "TEST001"

        # Generate first reference
        ref1 = self.manager.generate_mandate_reference(self.test_member.name, member_id=member_id)

        # Create mandate with that reference
        mandate1 = self._create_test_mandate(self.test_member.name, self.valid_iban, mandate_id=ref1)

        # Generate second reference
        ref2 = self.manager.generate_mandate_reference(self.test_member.name, member_id=member_id)

        # Should have incremented sequence
        self.assertNotEqual(ref1, ref2)
        # Same prefix, different sequence
        self.assertEqual(ref1[:-3], ref2[:-3])  # Same except last 3 digits
        self.assertEqual(int(ref2[-3:]), int(ref1[-3:]) + 1)

    def test_generate_mandate_reference_without_member_id(self):
        """Test reference generation when member_id is not provided"""
        # Should auto-retrieve or generate from member name
        reference = self.manager.generate_mandate_reference(self.test_member.name)

        self.assertTrue(reference.startswith("M-"))
        self.assertIsInstance(reference, str)
        self.assertGreater(len(reference), 10)

    # ========== Mandate Creation Tests ==========

    def test_create_mandate_success(self):
        """Test successful mandate creation"""
        result = self.manager.create_mandate(
            member=self.test_member.name,
            iban=self.valid_iban,
            account_holder_name="Test Member",
            used_for_memberships=True,
        )

        self.assertTrue(result.valid)
        self.assertIn("mandate_id", result.data)
        self.assertIn("mandate_name", result.data)

        # Verify mandate was created
        mandate_name = result.data["mandate_name"]
        self.assertTrue(frappe.db.exists("SEPA Mandate", mandate_name))

    def test_create_mandate_with_custom_mandate_id(self):
        """Test creating mandate with custom mandate ID"""
        # Use unique ID to avoid conflicts from test data leakage
        custom_id = f"CUSTOM-MANDATE-{frappe.generate_hash(length=8)}"

        result = self.manager.create_mandate(
            member=self.test_member.name, iban=self.valid_iban, mandate_id=custom_id
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.data["mandate_id"], custom_id)

    def test_create_mandate_auto_derives_bic(self):
        """Test mandate creation auto-derives BIC for Dutch IBAN"""
        result = self.manager.create_mandate(member=self.test_member.name, iban=self.valid_iban)

        self.assertTrue(result.valid)
        # BIC should be derived for Dutch IBAN
        self.assertIn("bic", result.data)
        self.assertIsNotNone(result.data["bic"])

    def test_create_mandate_uses_provided_bic(self):
        """Test mandate creation uses provided BIC"""
        custom_bic = "ABNANL2A"

        result = self.manager.create_mandate(member=self.test_member.name, iban=self.valid_iban, bic=custom_bic)

        self.assertTrue(result.valid)
        self.assertEqual(result.data["bic"], custom_bic)

    def test_create_mandate_uses_member_name_as_holder(self):
        """Test mandate uses member's full name when holder name not provided"""
        result = self.manager.create_mandate(member=self.test_member.name, iban=self.valid_iban)

        self.assertTrue(result.valid)

        # Verify mandate has member's name as account holder
        mandate = frappe.get_doc("SEPA Mandate", result.data["mandate_name"])
        self.assertEqual(mandate.account_holder_name, self.test_member.full_name)

    def test_create_mandate_fails_invalid_iban(self):
        """Test mandate creation fails with invalid IBAN"""
        result = self.manager.create_mandate(member=self.test_member.name, iban="INVALID_IBAN")

        self.assertFalse(result.valid)
        self.assertGreater(len(result.errors), 0)

    def test_create_mandate_links_to_member(self):
        """Test mandate is linked to member's sepa_mandates child table"""
        result = self.manager.create_mandate(member=self.test_member.name, iban=self.valid_iban)

        self.assertTrue(result.valid)

        # Reload member and check child table
        self.test_member.reload()
        mandate_links = [link for link in self.test_member.sepa_mandates if link.sepa_mandate == result.data["mandate_name"]]

        self.assertGreater(len(mandate_links), 0)
        self.assertEqual(mandate_links[0].mandate_reference, result.data["mandate_id"])

    # ========== IBAN Change Deactivation Tests ==========

    def test_deactivate_mandates_for_iban_change_success(self):
        """Test deactivating old mandates when IBAN changes"""
        # Create mandate with old IBAN
        old_mandate = self._create_test_mandate(
            self.test_member.name, self.valid_iban, status="Active", is_active=1
        )

        # Change to new IBAN
        result = self.manager.deactivate_mandates_for_iban_change(self.test_member.name, self.alternative_iban)

        self.assertTrue(result.valid)
        self.assertEqual(result.data["deactivated_count"], 1)
        self.assertEqual(len(result.data["deactivated_mandates"]), 1)

        # Verify mandate was deactivated
        old_mandate.reload()
        self.assertEqual(old_mandate.status, "Cancelled")
        self.assertEqual(old_mandate.is_active, 0)

    def test_deactivate_mandates_preserves_matching_iban(self):
        """Test that mandates with matching IBAN are not deactivated"""
        # Create mandate with same IBAN that we're "changing" to
        matching_mandate = self._create_test_mandate(
            self.test_member.name, self.valid_iban, status="Active", is_active=1
        )

        # "Change" to same IBAN (should not deactivate)
        result = self.manager.deactivate_mandates_for_iban_change(self.test_member.name, self.valid_iban)

        self.assertTrue(result.valid)
        self.assertEqual(result.data["deactivated_count"], 0)

        # Verify mandate still active
        matching_mandate.reload()
        self.assertEqual(matching_mandate.status, "Active")
        self.assertTrue(matching_mandate.is_active)

    def test_deactivate_mandates_handles_multiple(self):
        """Test deactivating multiple mandates with different IBANs"""
        # Create multiple mandates with old IBANs. The second must be forced Active:
        # #584 makes two Active mandates unreachable through save(), but NOT through
        # `frappe.db.set_value`, so the branch this test covers is still live.
        mandate1 = self._create_test_mandate(self.test_member.name, self.valid_iban, status="Active", is_active=1)
        mandate2 = self._force_second_active_mandate(self.test_member.name, self.alternative_iban)

        # Change to new IBAN with valid checksum
        from verenigingen.utils.validation.iban_validator import generate_test_iban
        new_iban = generate_test_iban("RABO", "0300065264")
        result = self.manager.deactivate_mandates_for_iban_change(self.test_member.name, new_iban)

        self.assertTrue(result.valid)
        self.assertEqual(result.data["deactivated_count"], 2)

        # Verify both deactivated
        mandate1.reload()
        mandate2.reload()
        self.assertEqual(mandate1.status, "Cancelled")
        self.assertEqual(mandate2.status, "Cancelled")

    def test_deactivate_mandates_normalizes_iban_format(self):
        """Test IBAN format normalization during deactivation check"""
        # Create mandate with unformatted IBAN
        mandate = self._create_test_mandate(
            self.test_member.name, self.valid_iban.replace(" ", ""), status="Active", is_active=1
        )

        # Try to deactivate with formatted IBAN (should not match after normalization)
        result = self.manager.deactivate_mandates_for_iban_change(self.test_member.name, self.valid_iban_formatted)

        # Should not deactivate (IBANs match after normalization)
        self.assertEqual(result.data["deactivated_count"], 0)

    # ========== Helper Methods ==========

    def _force_second_active_mandate(self, member, iban):
        """Create a second ACTIVE mandate by the one route the guard cannot see.

        `SEPAMandate.validate_single_active_mandate` (#584) rejects a second Active
        mandate, so this state is no longer reachable through insert()/save(). It IS
        still reachable through `frappe.db.set_value`, which writes the column without
        running `validate` -- which is precisely why the read side refuses rather than
        trusting the guard. Building the fixture this way keeps the multi-mandate
        branch under test AND documents the one route that still produces it.
        """
        mandate = self._create_test_mandate(member, iban, status="Draft", is_active=0)
        frappe.db.set_value(
            "SEPA Mandate", mandate.name, {"status": "Active", "is_active": 1}, update_modified=False
        )
        mandate.reload()
        return mandate

    def _create_test_mandate(
        self,
        member,
        iban,
        bic=None,
        mandate_id=None,
        status="Draft",
        is_active=0,
        used_for_memberships=1,
        used_for_donations=0,
    ):
        """
        Helper to create a test SEPA mandate using secure operations.

        Uses proper security validation instead of permission bypasses,
        following project security guidelines.

        Args:
            member: Member name
            iban: IBAN for the mandate
            bic: Optional BIC
            mandate_id: Optional custom mandate ID
            status: Mandate status
            is_active: Whether mandate is active
            used_for_memberships: Whether used for memberships
            used_for_donations: Whether used for donations

        Returns:
            Created SEPA Mandate document

        Raises:
            frappe.ValidationError: If mandate creation fails validation
        """
        from verenigingen.utils.secure_operations import secure_document_operation

        if not mandate_id:
            mandate_id = f"TEST-{frappe.generate_hash(length=8)}"

        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": member,
                "mandate_id": mandate_id,
                "iban": iban,
                "bic": bic or "ABNANL2A",
                "account_holder_name": "Test Holder",
                "sign_date": frappe.utils.today(),
                "status": status,
                "is_active": is_active,
                "used_for_memberships": used_for_memberships,
                "used_for_donations": used_for_donations,
                "mandate_type": "RCUR",
                # scheme is reqd=1; its DocType default ("SEPA") is not applied
                # to a dict-constructed doc before validation, so set it
                # explicitly to avoid "[SEPA Mandate]: scheme" MandatoryError.
                "scheme": "SEPA",
            }
        )

        # Use secure operations instead of ignore_permissions
        result = secure_document_operation(
            operation="insert",
            doc=mandate,
            justification=f"Test mandate creation for {member}",
            required_permissions=["SEPA Mandate:create"],
        )

        if not result.success:
            raise frappe.ValidationError(
                f"Test mandate creation failed: {'; '.join(result.errors)}"
            )

        # DO NOT commit - EnhancedTestCase handles transaction rollback
        # frappe.db.commit()  # ← REMOVED: breaks test isolation

        return mandate


# Run tests
def run_tests():
    """Run all SEPA mandate manager tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSEPAMandateManager)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    run_tests()
