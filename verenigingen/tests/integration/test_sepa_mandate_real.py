# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Real Integration Test for SEPA Mandate Workflow
===============================================

This test validates the complete SEPA mandate creation and management workflow
without mocking critical business logic. Tests real IBAN validation, mandate
lifecycle management, and Dutch banking compliance.

Key Testing Principles:
- Uses real database operations with transaction isolation  
- Tests actual SEPA validation logic without bypasses
- Validates Dutch banking format compliance (IBAN, account names)
- Mocks only external banking APIs
- Tests mandate status transitions and business rules

This addresses the SEPA testing gaps identified in the mock audit where
financial validation was completely mocked, missing real format errors.
"""

import frappe
from frappe.utils import today, add_days, now_datetime, get_datetime
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestSEPAMandateRealIntegration(EnhancedTestCase):
    """
    Real integration test for SEPA mandate workflow
    
    Tests mandate creation, validation, activation, and revocation with
    real database operations and Dutch banking compliance validation.
    """

    def setUp(self):
        """Set up test environment for SEPA mandate testing"""
        super().setUp()
        
        # Create test member for SEPA mandate
        self.member = self.create_test_member(
            first_name="SEPA",
            last_name="TestMember",
            email="sepa.test@example.com",
            status="Active",
            birth_date=add_days(today(), -365 * 30)  # 30 years old
        )
        
        # Create test admin for mandate management
        self.admin_user = self.create_test_user_with_roles(
            "sepa.admin@example.com",
            roles=["System Manager", "Verenigingen Administrator"]
        )

    def test_sepa_mandate_creation_with_real_iban_validation(self):
        """Test SEPA mandate creation with real IBAN format validation"""
        
        # Test with valid Dutch IBAN
        valid_iban = "NL91ABNA0417164300"
        account_holder = "SEPA Test Member"
        
        # Create SEPA mandate with real validation
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "scheme": "SEPA",
            "sign_date": today(),
            "member": self.member.name,
            "iban": valid_iban,  # Will be validated and formatted
            "account_holder_name": account_holder,
            "mandate_type": "RCUR",  # Recurring mandate
            "sequence_type": "FRST",  # First collection
            "status": "Draft"
        })
        
        # Insert should trigger real IBAN validation
        mandate.insert()
        self.track_test_record("SEPA Mandate", mandate.name)
        
        # Validate real IBAN formatting occurred
        mandate.reload()
        self.assertEqual(mandate.iban, "NL91 ABNA 0417 1643 00")  # Formatted with spaces
        self.assertEqual(mandate.status, "Draft")
        self.assertEqual(mandate.member, self.member.name)
        
        # Validate mandate id generation. The field is mandate_id (auto-generated
        # via the identity service with the default "MANDATE-.YY.-.MM.-.####"
        # pattern); there is no mandate_reference field.
        self.assertIsNotNone(mandate.mandate_id)
        self.assertTrue(mandate.mandate_id.startswith("MAND"))

    def test_sepa_mandate_iban_validation_errors(self):
        """Test that invalid IBANs are properly rejected"""
        
        invalid_ibans = [
            "NL91ABNA04171643",     # Too short
            "NL91ABNA041716430000", # Too long  
            "DE91ABNA0417164300",   # Wrong country code
            "NL00ABNA0417164300",   # Invalid check digits
            "INVALID_IBAN",         # Completely invalid format
            "",                     # Empty
            None                    # Null
        ]
        
        for invalid_iban in invalid_ibans:
            with self.subTest(iban=invalid_iban):
                mandate = frappe.get_doc({
                    "doctype": "SEPA Mandate",
                    "scheme": "SEPA",
                    "sign_date": today(),
                    "member": self.member.name,
                    "iban": invalid_iban,
                    "account_holder_name": "Test Member",
                    "mandate_type": "RCUR",
                    "sequence_type": "FRST",
                    "status": "Draft"
                })
                
                # Should raise validation error for invalid IBAN
                with self.assertRaises(frappe.ValidationError):
                    mandate.insert()

    def test_sepa_mandate_lifecycle_management(self):
        """Test complete SEPA mandate lifecycle with real status transitions"""
        
        # Stage 1: Create mandate in Draft status
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "scheme": "SEPA",
            "sign_date": today(),
            "member": self.member.name,
            "iban": "NL55INGB0000000000",  # Test IBAN for ING Bank
            "account_holder_name": "Lifecycle Test Member",
            "mandate_type": "RCUR",
            "sequence_type": "FRST",
            "status": "Draft"
        })
        mandate.insert()
        self.track_test_record("SEPA Mandate", mandate.name)
        
        # Stage 2: Activate mandate (real status transition)
        with self.as_user(self.admin_user.email):
            mandate.status = "Active"
            mandate.signed_date = today()
            mandate.save()
        
        mandate.reload()
        self.assertEqual(mandate.status, "Active")
        self.assertIsNotNone(mandate.signed_date)
        
        # Stage 3: Test mandate is properly linked to member
        self.member.reload()
        member_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": self.member.name, "status": "Active"},
            fields=["name", "iban", "status"]
        )
        
        self.assertEqual(len(member_mandates), 1)
        self.assertEqual(member_mandates[0]["name"], mandate.name)
        
        # Stage 4: Test mandate revocation
        with self.as_user(self.admin_user.email):
            mandate.status = "Revoked"
            mandate.revocation_date = today()
            mandate.revocation_reason = "Integration test revocation"
            mandate.save()
        
        mandate.reload()
        self.assertEqual(mandate.status, "Revoked")
        self.assertIsNotNone(mandate.revocation_date)
        
        # Validate no active mandates remain
        active_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": self.member.name, "status": "Active"}
        )
        self.assertEqual(len(active_mandates), 0)

    def test_sepa_mandate_business_rule_validation(self):
        """Test SEPA mandate business rules with real validation"""

        # Business rule: a member may not have two ACTIVE mandates that share the
        # same IBAN (a genuine duplicate). A different IBAN is a legitimate bank
        # switch and is allowed, so the duplicate must reuse the same IBAN.
        shared_iban = "NL28INGB0000000001"
        mandate1 = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "scheme": "SEPA",
            "sign_date": today(),
            "member": self.member.name,
            "iban": shared_iban,
            "account_holder_name": "First Mandate",
            "mandate_type": "RCUR",
            "sequence_type": "FRST",
            "status": "Active",
            "signed_date": today()
        })
        mandate1.insert()
        self.track_test_record("SEPA Mandate", mandate1.name)

        # Attempting to create a second active mandate with the SAME IBAN fails
        mandate2 = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "scheme": "SEPA",
            "sign_date": today(),
            "member": self.member.name,
            "iban": shared_iban,
            "account_holder_name": "Second Mandate",
            "mandate_type": "RCUR",
            "sequence_type": "FRST",
            "status": "Active",
            "signed_date": today()
        })

        # Should raise validation error for duplicate active mandate
        with self.assertRaises(frappe.ValidationError) as context:
            mandate2.insert()

        self.assertIn("already has an active", str(context.exception).lower())

    def test_sepa_mandate_dutch_banking_compliance(self):
        """Test compliance with Dutch banking standards and formats"""
        
        # Test Dutch bank IBANs and validation
        dutch_bank_ibans = [
            ("NL91ABNA0417164300", "ABN AMRO"),    # ABN AMRO
            ("NL55INGB0000000000", "ING Bank"),    # ING Bank  
            ("NL03RABO0000000001", "Rabobank"),    # Rabobank
            ("NL02TRIO0000000002", "Triodos Bank") # Triodos Bank
        ]
        
        for iban, bank_name in dutch_bank_ibans:
            with self.subTest(iban=iban, bank=bank_name):
                mandate = frappe.get_doc({
                    "doctype": "SEPA Mandate",
                    "scheme": "SEPA",
                    "sign_date": today(),
                    "member": self.member.name,
                    "iban": iban,
                    "account_holder_name": f"Test Member {bank_name}",
                    "mandate_type": "RCUR",
                    "sequence_type": "FRST", 
                    "status": "Draft"
                })
                
                # Should successfully validate Dutch bank IBANs
                mandate.insert()
                self.track_test_record("SEPA Mandate", mandate.name)
                
                # Verify IBAN formatting
                mandate.reload()
                self.assertTrue(mandate.iban.startswith("NL"))
                self.assertEqual(len(mandate.iban.replace(" ", "")), 18)  # Dutch IBAN length
                
                # Clean up for next iteration
                frappe.delete_doc("SEPA Mandate", mandate.name, force=True)

    def test_sepa_mandate_member_integration(self):
        """Test integration between SEPA mandates and member records"""
        
        # Create active SEPA mandate
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "scheme": "SEPA",
            "sign_date": today(),
            "member": self.member.name,
            "iban": "NL02ABNA0123456789",
            "account_holder_name": f"{self.member.first_name} {self.member.last_name}",
            "mandate_type": "RCUR",
            "sequence_type": "FRST",
            "status": "Active",
            "signed_date": today()
        })
        mandate.insert()
        self.track_test_record("SEPA Mandate", mandate.name)
        
        # Test member payment method integration
        self.member.reload()
        
        # Member should reflect SEPA payment capability
        mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": self.member.name, "status": "Active"},
            fields=["iban", "account_holder_name", "mandate_id"]
        )
        
        self.assertEqual(len(mandates), 1)
        active_mandate = mandates[0]
        self.assertEqual(active_mandate["iban"], "NL02 ABNA 0123 4567 89")  # Formatted
        
        # Test that member can be used for SEPA payments
        # (Integration with payment processing would be tested in payment workflow tests)
        self.assertEqual(active_mandate["account_holder_name"], 
                        f"{self.member.first_name} {self.member.last_name}")

    def test_sepa_mandate_sequence_type_transitions(self):
        """Test SEPA sequence type transitions for recurring payments"""
        
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "scheme": "SEPA",
            "sign_date": today(),
            "member": self.member.name,
            "iban": "NL72TRIO0000000003",
            "account_holder_name": "Sequence Test Member",
            "mandate_type": "RCUR",
            "sequence_type": "FRST",  # First collection
            "status": "Active",
            "signed_date": today()
        })
        mandate.insert()
        self.track_test_record("SEPA Mandate", mandate.name)
        
        # Test first collection
        self.assertEqual(mandate.sequence_type, "FRST")
        
        # After first successful collection, should allow RCUR
        # (This would typically be updated by payment processing)
        mandate.sequence_type = "RCUR"  # Recurring
        mandate.save()
        
        mandate.reload()
        self.assertEqual(mandate.sequence_type, "RCUR")
        
        # Test final collection
        mandate.sequence_type = "FNAL"  # Final collection
        mandate.save()
        
        mandate.reload()
        self.assertEqual(mandate.sequence_type, "FNAL")

    def test_sepa_mandate_error_handling_and_recovery(self):
        """Test SEPA mandate error scenarios and recovery"""
        
        # Test mandate creation with member that doesn't exist
        with self.assertRaises((frappe.DoesNotExistError, frappe.ValidationError)):
            mandate = frappe.get_doc({
                "doctype": "SEPA Mandate",
                "scheme": "SEPA",
                "sign_date": today(),
                "member": "NON-EXISTENT-MEMBER",
                "iban": "NL91ABNA0417164300",
                "account_holder_name": "Non Existent Member",
                "mandate_type": "RCUR",
                "sequence_type": "FRST",
                "status": "Draft"
            })
            mandate.insert()
        
        # Test mandate with missing required fields
        incomplete_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "scheme": "SEPA",
            "sign_date": today(),
            "member": self.member.name,
            # Missing iban
            "account_holder_name": "Incomplete Mandate",
            "mandate_type": "RCUR",
            "status": "Draft"
        })
        
        with self.assertRaises(frappe.ValidationError):
            incomplete_mandate.insert()

    def test_sepa_mandate_audit_trail(self):
        """Test SEPA mandate changes create proper audit trail"""
        
        mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "scheme": "SEPA",
            "sign_date": today(),
            "member": self.member.name,
            "iban": "NL44INGB0000000004",
            "account_holder_name": "Audit Trail Test",
            "mandate_type": "RCUR",
            "sequence_type": "FRST",
            "status": "Draft"
        })
        mandate.insert()
        self.track_test_record("SEPA Mandate", mandate.name)
        
        original_modified = get_datetime(mandate.modified)

        # Make status change. EnhancedTestCase.setUp sets frappe.flags.in_import
        # = True (to bypass user-creation throttling), which also suppresses
        # Version (audit trail) creation. Temporarily clear it so the status
        # change is recorded in the version history asserted below.
        original_in_import = frappe.flags.in_import
        frappe.flags.in_import = False
        try:
            with self.as_user(self.admin_user.email):
                mandate.status = "Active"
                mandate.signed_date = today()
                # In test mode Frappe defaults flags.ignore_version to
                # frappe.in_test (True), which skips Version creation. Pass
                # ignore_version=False so the status change is recorded in the
                # audit trail asserted below.
                mandate.save(ignore_version=False)
        finally:
            frappe.flags.in_import = original_in_import

        mandate.reload()

        # Verify audit trail information. Normalise both sides with get_datetime:
        # mandate.modified may be a str after reload and a datetime in memory.
        self.assertGreater(get_datetime(mandate.modified), original_modified)
        self.assertEqual(mandate.modified_by, self.admin_user.email)
        self.assertEqual(mandate.status, "Active")
        
        # Check version history exists
        versions = frappe.get_all(
            "Version",
            filters={"ref_doctype": "SEPA Mandate", "docname": mandate.name},
            fields=["name", "data"]
        )
        
        # Should have version history for status change
        self.assertGreater(len(versions), 0)


if __name__ == '__main__':
    import unittest
    unittest.main()