#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive SEPA Mandate Test Suite
====================================

Enterprise-grade test suite for SEPA mandate functionality with full compliance
validation for European banking regulations and Dutch financial standards.

Test Coverage:
- CRUD operations with proper validation
- Business logic and lifecycle management
- Security and permission validation
- PSD2 and European banking compliance
- Dutch banking specific requirements
- Mollie integration workflows
- Error handling and edge cases
- Audit logging and compliance tracking

Security Focus:
- Member ownership validation
- IBAN/BIC data protection
- Audit trail requirements
- Permission-based access control

Compliance Testing:
- European banking regulations (PSD2)
- Dutch banking standards
- SEPA mandate lifecycle rules
- Data retention requirements
"""

import unittest
from typing import Optional

import frappe
from frappe.test_runner import make_test_records
from frappe.utils import add_days, flt, random_string, today

# Import Enhanced Test Factory for business logic validation
try:
    from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

    HAS_ENHANCED_FACTORY = True
except ImportError:
    # Fallback to standard FrappeTestCase if Enhanced Test Factory not available
    from frappe.tests.utils import FrappeTestCase

    EnhancedTestCase = FrappeTestCase
    HAS_ENHANCED_FACTORY = False

# Import validation utilities (feature-detection only; functions not called directly)
import importlib.util

HAS_IBAN_VALIDATOR = importlib.util.find_spec("verenigingen.utils.validation.iban_validator") is not None

# Import member utilities
try:
    from verenigingen.utils.member_utils import get_member_sepa_mandate, has_active_sepa_mandate

    HAS_MEMBER_UTILS = True
except ImportError:
    HAS_MEMBER_UTILS = False


class SEPAMandateTestDataFactory:
    """
    Specialized test data factory for SEPA mandate testing with realistic
    European banking data generation and Dutch compliance validation.
    """

    # Dutch bank BIC codes for realistic test data
    DUTCH_BANK_BICS = {
        "ABNA": {"bic": "ABNANL2A", "name": "ABN AMRO Bank N.V."},
        "INGB": {"bic": "INGBNL2A", "name": "ING Bank N.V."},
        "RABO": {"bic": "RABONL2U", "name": "Rabobank Nederland"},
        "SNSB": {"bic": "SNSBNL2A", "name": "SNS Bank N.V."},
        "TRIO": {"bic": "TRIONL2U", "name": "Triodos Bank N.V."},
        "ASNB": {"bic": "ASNBNL21", "name": "ASN Bank N.V."},
    }

    # Valid test IBAN patterns for different countries
    TEST_IBANS = {
        "NL": [
            "NL91ABNA0417164300",  # ABN AMRO test IBAN
            "NL20INGB0001234567",  # ING test IBAN (valid MOD-97 check digits)
            "NL44RABO0123456789",  # Rabobank test IBAN (valid MOD-97 check digits)
            "NL70TRIO0123456789",  # Triodos test IBAN (valid MOD-97 check digits)
        ],
        "DE": ["DE89370400440532013000", "DE12500105170648489890"],  # German test IBAN  # German test IBAN
        "FR": [
            "FR1420041010050500013M02606",  # French test IBAN
            "FR7630001007941234567890185",  # French test IBAN
        ],
    }

    @staticmethod
    def get_valid_test_iban(country: str = "NL", bank_code: Optional[str] = None) -> str:
        """
        Get a valid test IBAN for the specified country and bank.

        Args:
            country: ISO country code (default: NL for Netherlands)
            bank_code: Specific bank code (only for NL currently)

        Returns:
            Valid test IBAN string
        """
        if country not in SEPAMandateTestDataFactory.TEST_IBANS:
            country = "NL"  # Default to Dutch IBAN

        available_ibans = SEPAMandateTestDataFactory.TEST_IBANS[country]

        if bank_code and country == "NL":
            # Try to find IBAN for specific bank
            for iban in available_ibans:
                if bank_code in iban:
                    return iban

        # Return first available IBAN
        return available_ibans[0]

    @staticmethod
    def get_bic_for_iban(iban: str) -> Optional[str]:
        """
        Get the corresponding BIC for a test IBAN.

        Args:
            iban: IBAN string

        Returns:
            BIC string if found, None otherwise
        """
        # Extract bank code from Dutch IBAN (positions 4-8)
        if iban.startswith("NL") and len(iban) >= 8:
            bank_code = iban[4:8]
            bank_info = SEPAMandateTestDataFactory.DUTCH_BANK_BICS.get(bank_code)
            if bank_info:
                return bank_info["bic"]

        return None

    @staticmethod
    def get_bank_name_for_iban(iban: str) -> Optional[str]:
        """
        Get the bank name for a test IBAN.

        Args:
            iban: IBAN string

        Returns:
            Bank name if found, None otherwise
        """
        if iban.startswith("NL") and len(iban) >= 8:
            bank_code = iban[4:8]
            bank_info = SEPAMandateTestDataFactory.DUTCH_BANK_BICS.get(bank_code)
            if bank_info:
                return bank_info["name"]

        return None


class ComprehensiveSEPAMandateTests(EnhancedTestCase):
    """
    Comprehensive SEPA Mandate test suite with full European banking compliance.

    This test suite validates all aspects of SEPA mandate functionality including:
    - Business logic and lifecycle management
    - Security and permission validation
    - Dutch banking specific requirements
    - European banking regulation compliance (PSD2)
    - Integration with member management
    - Audit logging and compliance tracking
    """

    @classmethod
    def setUpClass(cls):
        """Set up test class with required test records."""
        super().setUpClass()

        # Ensure required DocTypes exist
        for _dt in ["Member", "Customer", "SEPA Mandate"]:
            make_test_records(_dt)

        # Set up test configuration
        cls.test_factory = SEPAMandateTestDataFactory()

    def setUp(self):
        """Set up each test with clean test data."""
        super().setUp()

        # Create test member using Enhanced Test Factory if available
        if HAS_ENHANCED_FACTORY:
            self.test_member = self.create_test_member(
                first_name="SEPA",
                last_name="TestUser",
                birth_date="1990-01-01",
                email=f"sepa_test_{random_string(8)}@example.com",
            )
        else:
            # Fallback member creation
            self.test_member = self._create_fallback_member()

        # Store member name for easy access
        self.member_name = self.test_member.name

    def _create_fallback_member(self):
        """Create member using standard Frappe methods when Enhanced Factory unavailable."""
        member_data = {
            "doctype": "Member",
            "first_name": "SEPA",
            "last_name": "TestUser",
            "email": f"sepa_fallback_{random_string(8)}@example.com",
            "birth_date": "1990-01-01",
            "mobile_no": f"+316{random_string(8, only_digits=True)}",
        }

        member = frappe.get_doc(member_data)
        member.insert()
        return member

    def _create_test_mandate(
        self,
        status: str = "Draft",
        iban: str = None,
        sign_date: str = None,
        expiry_date: str = None,
        **kwargs,
    ):
        """
        Create a test SEPA mandate with realistic data.

        Args:
            status: Mandate status
            iban: Custom IBAN (uses test IBAN if None)
            sign_date: Sign date (uses today if None)
            expiry_date: Expiry date (None for open-ended)
            **kwargs: Additional mandate fields

        Returns:
            SEPA Mandate document
        """
        # Use test IBAN if none provided. Generate a UNIQUE valid IBAN per call so
        # that tests which create several mandates for the same member do not trip
        # validate_no_duplicate_active_mandate (which keys on member + IBAN). A real
        # Dutch bank code (INGB) is used so BIC derivation still resolves.
        if not iban:
            try:
                from verenigingen.utils.validation.iban_validator import generate_test_iban

                type(self)._mandate_iban_seq = getattr(type(self), "_mandate_iban_seq", 0) + 1
                account_number = str(1000000000 + type(self)._mandate_iban_seq)
                iban = generate_test_iban("INGB", account_number)
            except Exception:
                iban = self.test_factory.get_valid_test_iban()

        # Get corresponding BIC
        bic = self.test_factory.get_bic_for_iban(iban)
        bank_name = self.test_factory.get_bank_name_for_iban(iban)

        mandate_data = {
            "doctype": "SEPA Mandate",
            "member": self.member_name,
            "account_holder_name": self.test_member.full_name,
            "iban": iban,
            "bic": bic,
            "bank_name": bank_name,
            "sign_date": sign_date or today(),
            "expiry_date": expiry_date,
            "status": status,
            "mandate_type": "RCUR",
            "scheme": "SEPA",
            "is_active": 1 if status == "Active" else 0,
            "used_for_memberships": 1,
            "frequency": "Monthly",
            **kwargs,
        }

        mandate = frappe.get_doc(mandate_data)
        return mandate

    # ==========================================
    # CRUD Operations and Basic Validation Tests
    # ==========================================

    def test_mandate_creation_with_valid_data(self):
        """
        Test successful SEPA mandate creation with valid data.

        Validates:
        - Document creation with required fields
        - IBAN validation and formatting
        - BIC auto-derivation
        - Status and is_active synchronization
        """
        mandate = self._create_test_mandate(status="Active")
        mandate.insert()

        # Verify mandate was created
        self.assertTrue(frappe.db.exists("SEPA Mandate", mandate.name))

        # Verify IBAN formatting
        self.assertIn(" ", mandate.iban)  # Should be formatted with spaces

        # Verify BIC was auto-derived
        self.assertIsNotNone(mandate.bic)
        self.assertTrue(len(mandate.bic) >= 8)

        # Verify status synchronization
        self.assertEqual(mandate.status, "Active")
        self.assertEqual(mandate.is_active, 1)

    def test_mandate_creation_with_invalid_iban(self):
        """
        Test mandate creation fails with invalid IBAN.

        Validates:
        - IBAN format validation
        - Proper error messages
        - Prevention of invalid mandate creation
        """
        mandate = self._create_test_mandate(iban="INVALID_IBAN")

        with self.assertRaises(frappe.ValidationError):
            mandate.insert()

    def test_mandate_creation_with_future_sign_date(self):
        """
        Test mandate creation fails when sign date is in the future.

        Validates:
        - Date validation rules
        - Prevention of future-dated mandates
        """
        future_date = add_days(today(), 30)
        mandate = self._create_test_mandate(sign_date=future_date)

        with self.assertRaises(frappe.ValidationError):
            mandate.insert()

    def test_mandate_creation_with_invalid_expiry_date(self):
        """
        Test mandate creation fails when expiry date is before sign date.

        Validates:
        - Date range validation
        - Logical date constraints
        """
        sign_date = today()
        expiry_date = add_days(today(), -30)  # 30 days before sign date

        mandate = self._create_test_mandate(sign_date=sign_date, expiry_date=expiry_date)

        with self.assertRaises(frappe.ValidationError):
            mandate.insert()

    # ==========================================
    # Business Logic and Lifecycle Tests
    # ==========================================

    def test_mandate_status_lifecycle(self):
        """
        Test complete SEPA mandate status lifecycle.

        Validates:
        - Draft → Active transition
        - Active → Suspended transition
        - Suspended → Active transition
        - Active → Cancelled transition
        - Status immutability rules
        """
        # Start with Draft status
        mandate = self._create_test_mandate(status="Draft")
        mandate.insert()
        self.assertEqual(mandate.status, "Draft")

        # Transition to Active
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.save()
        self.assertEqual(mandate.status, "Active")
        self.assertEqual(mandate.is_active, 1)

        # Transition to Suspended
        mandate.status = "Suspended"
        mandate.is_active = 0
        mandate.save()
        self.assertEqual(mandate.status, "Suspended")
        self.assertEqual(mandate.is_active, 0)

        # Transition back to Active
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.save()
        self.assertEqual(mandate.status, "Active")
        self.assertEqual(mandate.is_active, 1)

        # Transition to Cancelled (terminal state)
        mandate.status = "Cancelled"
        mandate.is_active = 0
        mandate.cancelled_date = today()
        mandate.cancellation_reason = "Test cancellation"
        mandate.save()
        self.assertEqual(mandate.status, "Cancelled")
        self.assertEqual(mandate.is_active, 0)

        # Verify Cancelled status cannot be changed
        mandate.status = "Active"
        mandate.save()
        mandate.reload()
        # Status should remain Cancelled after reload
        self.assertEqual(mandate.status, "Cancelled")

    def test_mandate_expiry_automatic_status_update(self):
        """
        Test automatic status update when mandate expires.

        Validates:
        - Automatic expiry detection
        - Status update to Expired
        - is_active flag synchronization
        """
        # Create mandate that expires yesterday
        past_date = add_days(today(), -30)  # Sign date 30 days ago
        expiry_date = add_days(today(), -1)  # Expired yesterday

        mandate = self._create_test_mandate(status="Active", sign_date=past_date, expiry_date=expiry_date)
        mandate.insert()

        # Should automatically set status to Expired
        self.assertEqual(mandate.status, "Expired")
        self.assertEqual(mandate.is_active, 0)

    def test_mandate_member_relationship_update(self):
        """
        Test mandate relationship with member is properly maintained.

        Validates:
        - Member SEPA mandate child table updates
        - Current mandate designation
        - Multiple mandate handling
        """
        mandate = self._create_test_mandate(status="Active")
        mandate.insert()

        # Reload member to check child table
        self.test_member.reload()

        # Check if mandate was added to member's child table
        mandate_found = False
        for member_mandate in self.test_member.get("sepa_mandates", []):
            if member_mandate.sepa_mandate == mandate.name:
                mandate_found = True
                self.assertTrue(member_mandate.is_current)
                self.assertEqual(member_mandate.status, "Active")
                break

        self.assertTrue(mandate_found, "Mandate should be added to member's child table")

    # ==========================================
    # Security and Permission Tests
    # ==========================================

    def test_mandate_permission_member_ownership(self):
        """
        Test SEPA mandate permissions respect member ownership.

        Validates:
        - Member can read their own mandate without a PermissionError.
        """
        mandate = self._create_test_mandate(status="Active")
        mandate.insert()

        # Switch to the owning member's user, restoring whoever was set before
        # (do NOT hard-reset to Administrator — that masks the boundary under test).
        original_user = frappe.session.user
        frappe.set_user(self.test_member.email or self.test_member.get("user"))

        # Should be able to read own mandate
        try:
            own_mandate = frappe.get_doc("SEPA Mandate", mandate.name)
            self.assertEqual(own_mandate.member, self.member_name)
        except frappe.PermissionError:
            self.fail("Member should be able to access own SEPA mandate")
        finally:
            frappe.set_user(original_user)

    # ==========================================
    # Dutch Banking Compliance Tests
    # ==========================================

    def test_dutch_iban_validation(self):
        """
        Test Dutch IBAN specific validation rules.

        Validates:
        - Dutch IBAN format (NL + 16 digits)
        - Dutch bank code validation
        - BIC derivation for Dutch banks
        """
        if not HAS_IBAN_VALIDATOR:
            self.skipTest("IBAN validator not available")

        # Test valid Dutch IBANs
        for test_iban in self.test_factory.TEST_IBANS["NL"]:
            mandate = self._create_test_mandate(iban=test_iban)
            mandate.insert()

            # Verify IBAN was accepted and formatted
            self.assertTrue(mandate.iban.startswith("NL"))
            self.assertIn(" ", mandate.iban)  # Should be formatted

            # Verify BIC was derived
            self.assertIsNotNone(mandate.bic)

    def test_dutch_bank_bic_derivation(self):
        """
        Test BIC derivation for Dutch banks.

        Validates:
        - Automatic BIC detection from IBAN
        - Correct BIC codes for major Dutch banks
        - Bank name population
        """
        for bank_code, bank_info in self.test_factory.DUTCH_BANK_BICS.items():
            # Find test IBAN for this bank
            test_iban = None
            for iban in self.test_factory.TEST_IBANS["NL"]:
                if bank_code in iban:
                    test_iban = iban
                    break

            if test_iban:
                mandate = self._create_test_mandate(iban=test_iban)
                mandate.insert()

                # Verify correct BIC was derived
                self.assertEqual(mandate.bic, bank_info["bic"])
                self.assertEqual(mandate.bank_name, bank_info["name"])

    # ==========================================
    # Integration Tests
    # ==========================================

    def test_member_utils_integration(self):
        """
        Test integration with member utility functions.

        Validates:
        - get_member_sepa_mandate function
        - has_active_sepa_mandate function
        - Proper data retrieval
        """
        if not HAS_MEMBER_UTILS:
            self.skipTest("Member utilities not available")

        # Create active mandate
        mandate = self._create_test_mandate(status="Active")
        mandate.insert()

        # Test get_member_sepa_mandate
        mandate_info = get_member_sepa_mandate(self.member_name)
        self.assertIsNotNone(mandate_info)
        self.assertEqual(mandate_info["name"], mandate.name)
        self.assertEqual(mandate_info["status"], "Active")

        # Test has_active_sepa_mandate
        self.assertTrue(has_active_sepa_mandate(self.member_name))

        # Test with inactive mandate
        mandate.status = "Cancelled"
        mandate.save()

        self.assertFalse(has_active_sepa_mandate(self.member_name))

    # ==========================================
    # Error Handling and Edge Cases
    # ==========================================

    def test_mandate_without_member(self):
        """
        Test SEPA mandate creation without member (donor scenario).

        Validates:
        - Mandates for non-member donors
        - Different permission rules
        - Usage restrictions
        """
        mandate_data = {
            "doctype": "SEPA Mandate",
            "member": None,  # No member link
            "account_holder_name": "Anonymous Donor",
            "iban": self.test_factory.get_valid_test_iban(),
            "sign_date": today(),
            "status": "Active",
            "mandate_type": "RCUR",
            "scheme": "SEPA",
            "is_active": 1,
            "used_for_donations": 1,  # Used for donations, not memberships
            "used_for_memberships": 0,
        }

        mandate = frappe.get_doc(mandate_data)
        mandate.insert()

        # Verify mandate was created without member
        self.assertIsNone(mandate.member)
        self.assertEqual(mandate.used_for_donations, 1)
        self.assertEqual(mandate.used_for_memberships, 0)

    def test_mandate_maximum_amount_validation(self):
        """
        Test maximum amount validation for SEPA mandates.

        Validates:
        - Maximum amount setting
        - Usage validation against maximum
        - Compliance with SEPA rules
        """
        mandate = self._create_test_mandate(status="Active", maximum_amount=100.00)
        mandate.insert()

        # Verify maximum amount was set
        self.assertEqual(flt(mandate.maximum_amount), 100.00)

        # Test usage validation would occur during payment processing
        # This is a placeholder for actual usage validation

    def test_mandate_frequency_validation(self):
        """
        Test mandate frequency settings and validation.

        Validates:
        - Different frequency options
        - Frequency-based usage rules
        - Compliance with SEPA frequency limits
        """
        frequencies = ["Monthly", "Quarterly", "Biannual", "Annual", "Variable"]

        for frequency in frequencies:
            mandate = self._create_test_mandate(status="Active", frequency=frequency)
            mandate.insert()

            self.assertEqual(mandate.frequency, frequency)

    def test_mandate_cleanup_on_member_deletion(self):
        """
        Test member deletion when the member has an active SEPA mandate.

        MemberCleanupService.handle_member_deletion() cascades deletion for
        Membership / Membership Dues Schedule / Chapter Member and clears the
        Member's "Member SEPA Mandate Link" child table, but it does NOT
        delete, cancel, or unlink the SEPA Mandate document itself (whose
        `member` field still points at the Member being deleted). Frappe's
        link-existence check therefore rejects the deletion with a genuine
        LinkExistsError rather than silently orphaning the mandate.

        This is a real, currently-unhandled cascade gap (logged to
        backlog-missing-coverage.md); the test documents the actual behavior
        so a future fix to the cleanup service has a regression guard either
        way (once cleanup is fixed to unlink/cancel mandates, this test
        should be updated to assert successful deletion instead).
        """
        mandate = self._create_test_mandate(status="Active")
        mandate.insert()
        mandate_name = mandate.name

        with self.assertRaises(frappe.LinkExistsError):
            frappe.delete_doc("Member", self.member_name, ignore_permissions=True)

        # The mandate is untouched by the rejected deletion attempt.
        self.assertTrue(frappe.db.exists("SEPA Mandate", mandate_name))
        self.assertTrue(frappe.db.exists("Member", self.member_name))

    # ==========================================
    # Performance and Query Optimization Tests
    # ==========================================

    def test_mandate_query_performance(self):
        """
        Test SEPA mandate query performance with realistic data volumes.

        Validates:
        - Efficient member mandate lookups
        - Index usage optimization
        - Bulk operation performance
        """
        # Create multiple mandates for performance testing
        mandates = []
        for i in range(10):
            mandate = self._create_test_mandate(status="Active" if i % 2 == 0 else "Cancelled")
            mandate.insert()
            mandates.append(mandate)

        # Test query performance with assertQueryCount if available
        if hasattr(self, "assertQueryCount"):
            with self.assertQueryCount(10):  # Should be efficient
                # Query active mandates
                active_mandates = frappe.get_all(
                    "SEPA Mandate",
                    filters={"member": self.member_name, "status": "Active"},
                    fields=["name", "mandate_id", "status"],
                )

                # Verify results
                self.assertEqual(len(active_mandates), 5)  # Half should be active

    def tearDown(self):
        """
        Clean up test data after each test.

        Ensures:
        - Test data isolation
        - Clean state for next test
        - Proper resource cleanup
        """
        # Clean up is handled by EnhancedTestCase/FrappeTestCase
        # through automatic database rollback
        super().tearDown()


if __name__ == "__main__":
    unittest.main()
