"""
Test suite for invoice eligibility validation behavior changes
Tests the separation of invoice generation from SEPA mandate validation
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.utils.base import VereningingenTestCase


class TestInvoiceEligibilityValidation(VereningingenTestCase):
    """
    Test invoice eligibility validation behavior after separating SEPA mandate 
    validation from invoice generation eligibility.
    
    Key behavior: Broken payment data should not prevent invoice generation,
    only Direct Debit batch inclusion.
    """

    def setUp(self):
        """Set up test data"""
        super().setUp()

    def test_member_with_sepa_direct_debit_no_mandate_gets_invoice(self):
        """
        WHAT THIS TEST DOES:
        Tests the core behavior change where members with SEPA Direct Debit payment method
        but no active SEPA mandate can still receive invoices. This validates that broken
        payment data doesn't block invoice generation, only DD batch inclusion.
        
        TEST SEQUENCE:
        1. Create member with SEPA Direct Debit payment method and proper bank details
        2. Create active membership for the member
        3. Create dues schedule for regular billing
        4. Verify no SEPA mandate exists (simulating broken payment setup)
        5. Test invoice generation eligibility - should PASS (new behavior)
        6. Generate actual invoice and verify it was created successfully
        7. Confirm invoice has correct properties and is submitted
        
        EXPECTED BEHAVIOR:
        - Member should be eligible for invoice generation despite missing mandate
        - Invoice should be created successfully and be payable via other methods
        - This represents the separation of invoice generation from SEPA validation
        """
        # Create member with SEPA Direct Debit payment method
        member = self.create_test_member(
            first_name="SEPANoMandate",
            last_name="TestMember",
            email=f"sepa.nomandate.{frappe.generate_hash(length=6)}@example.com",
            payment_method="SEPA Direct Debit",
            iban="NL13TEST0123456789",
            account_holder_name="SEPANoMandate TestMember"
        )

        # Create active membership
        membership = self.create_test_membership(
            member=member.name,
            membership_type="Test Membership",
            status="Active"
        )

        # Create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = f"Test Schedule {member.name}"
        dues_schedule.member = member.name
        dues_schedule.membership_type = "Test Membership"
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.dues_rate = 15.0
        dues_schedule.next_invoice_date = today()
        dues_schedule.status = "Active"
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)

        # Verify no SEPA mandate exists
        mandate_exists = frappe.db.exists(
            "SEPA Mandate",
            {"member": member.name, "status": "Active", "is_active": 1}
        )
        self.assertFalse(mandate_exists, "No SEPA mandate should exist for this test")

        # Test eligibility validation - should PASS (new behavior)
        is_eligible = dues_schedule.validate_member_eligibility_for_invoice()
        self.assertTrue(is_eligible, 
                       "Member with SEPA Direct Debit but no mandate should be eligible for invoicing")

        # Test invoice generation
        can_generate, reason = dues_schedule.can_generate_invoice()
        self.assertTrue(can_generate, f"Should be able to generate invoice: {reason}")

        # Generate invoice
        invoice_name = dues_schedule.create_sales_invoice()
        self.assertIsNotNone(invoice_name, "Invoice should be created despite missing SEPA mandate")
        self.track_doc("Sales Invoice", invoice_name)

        # Verify invoice was created successfully
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(invoice.customer, member.customer)
        self.assertEqual(invoice.grand_total, 15.0)
        self.assertEqual(invoice.docstatus, 1)  # Should be submitted

    def test_member_with_bank_transfer_no_special_validation(self):
        """
        WHAT THIS TEST DOES:
        Tests that members with Bank Transfer payment method work normally without
        any special validation requirements. This serves as a control test to verify
        that non-SEPA payment methods are unaffected by the SEPA validation changes.
        
        TEST SEQUENCE:
        1. Create member with Bank Transfer payment method (no bank details required)
        2. Create active membership
        3. Create dues schedule
        4. Test invoice generation eligibility - should PASS
        5. Generate invoice and verify success
        
        EXPECTED BEHAVIOR:
        - Member should be eligible for invoicing without any special validation
        - Invoice generation should work normally
        - No SEPA-related validation should occur
        """
        # Create member with Bank Transfer payment method
        member = self.create_test_member(
            first_name="BankTransfer",
            last_name="TestMember",
            email=f"bank.transfer.{frappe.generate_hash(length=6)}@example.com",
            payment_method="Bank Transfer"
        )

        # Create active membership
        membership = self.create_test_membership(
            member=member.name,
            membership_type="Test Membership",
            status="Active"
        )

        # Create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.membership_type = "Test Membership"
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.dues_rate = 20.0
        dues_schedule.next_invoice_date = today()
        dues_schedule.status = "Active"
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)

        # Test eligibility validation - should PASS
        is_eligible = dues_schedule.validate_member_eligibility_for_invoice()
        self.assertTrue(is_eligible, "Member with Bank Transfer should be eligible for invoicing")

        # Generate invoice
        invoice_name = dues_schedule.create_sales_invoice()
        self.assertIsNotNone(invoice_name, "Invoice should be created for Bank Transfer member")
        self.track_doc("Sales Invoice", invoice_name)

    def test_terminated_member_still_blocked_from_invoicing(self):
        """
        WHAT THIS TEST DOES:
        Tests that terminated members are still blocked from receiving invoices,
        ensuring that the SEPA validation changes didn't affect member status validation.
        This is a critical safety check to prevent billing terminated members.
        
        TEST SEQUENCE:
        1. Create member with Terminated status
        2. Create membership (inconsistent but for testing purposes)
        3. Create dues schedule
        4. Test invoice generation eligibility - should FAIL
        5. Verify invoice generation is blocked
        
        EXPECTED BEHAVIOR:
        - Terminated member should NOT be eligible for invoicing
        - Invoice generation should be blocked with appropriate error
        - Member status validation should still work as before
        """
        # Create terminated member
        member = self.create_test_member(
            first_name="Terminated",
            last_name="TestMember",
            email=f"terminated.{frappe.generate_hash(length=6)}@example.com",
            status="Terminated"
        )

        # Create membership (would be terminated but keep simple for test)
        membership = self.create_test_membership(
            member=member.name,
            membership_type="Test Membership",
            status="Active"  # This is inconsistent but we're testing member status priority
        )

        # Create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = f"Test Schedule {member.name}"
        dues_schedule.member = member.name
        dues_schedule.membership_type = "Test Membership"
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.dues_rate = 25.0
        dues_schedule.next_invoice_date = today()
        dues_schedule.status = "Active"
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)

        # Test eligibility validation - should FAIL
        is_eligible = dues_schedule.validate_member_eligibility_for_invoice()
        self.assertFalse(is_eligible, "Terminated member should NOT be eligible for invoicing")

        # Invoice generation should fail
        can_generate, reason = dues_schedule.can_generate_invoice()
        self.assertFalse(can_generate, "Should not be able to generate invoice for terminated member")

    def test_member_without_active_membership_blocked_from_invoicing(self):
        """
        WHAT THIS TEST DOES:
        Tests that members without active membership are blocked from invoicing.
        This ensures that membership status validation continues to work properly
        after the SEPA validation changes.
        
        TEST SEQUENCE:
        1. Create active member
        2. Create expired/inactive membership
        3. Create dues schedule
        4. Test invoice generation eligibility - should FAIL
        
        EXPECTED BEHAVIOR:
        - Member without active membership should NOT be eligible for invoicing
        - Membership status validation should still work
        - Only active memberships should allow billing
        """
        # Create active member
        member = self.create_test_member(
            first_name="NoMembership",
            last_name="TestMember",
            email=f"no.membership.{frappe.generate_hash(length=6)}@example.com",
            status="Active"
        )

        # Create inactive membership
        membership = self.create_test_membership(
            member=member.name,
            membership_type="Test Membership",
            status="Expired"  # Not active
        )

        # Create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = f"Test Schedule {member.name}"
        dues_schedule.member = member.name
        dues_schedule.membership_type = "Test Membership"
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.dues_rate = 25.0
        dues_schedule.next_invoice_date = today()
        dues_schedule.status = "Active"
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)

        # Test eligibility validation - should FAIL
        is_eligible = dues_schedule.validate_member_eligibility_for_invoice()
        self.assertFalse(is_eligible, "Member without active membership should NOT be eligible for invoicing")

    def test_member_with_active_sepa_mandate_works_normally(self):
        """
        WHAT THIS TEST DOES:
        Tests that members with proper SEPA setup (mandate + bank details) work normally.
        This serves as a positive control to verify that proper SEPA configurations
        are unaffected by the validation changes.
        
        TEST SEQUENCE:
        1. Create member with SEPA Direct Debit and complete bank details
        2. Create active membership
        3. Create active SEPA mandate
        4. Create dues schedule
        5. Test invoice generation eligibility - should PASS
        6. Generate invoice and verify success
        
        EXPECTED BEHAVIOR:
        - Member with proper SEPA setup should be eligible for invoicing
        - Invoice generation should work normally
        - These members should also be eligible for DD batch inclusion
        """
        # Create member with SEPA Direct Debit
        member = self.create_test_member(
            first_name="ValidSEPA",
            last_name="TestMember",
            email=f"valid.sepa.{frappe.generate_hash(length=6)}@example.com",
            payment_method="SEPA Direct Debit",
            iban="NL13TEST0123456789",
            account_holder_name="ValidSEPA TestMember"
        )

        # Create active membership
        membership = self.create_test_membership(
            member=member.name,
            membership_type="Test Membership",
            status="Active"
        )

        # Create active SEPA mandate
        mandate = self.create_test_sepa_mandate(
            member=member.name,
            iban="NL13TEST0123456789",
            status="Active",
            is_active=1
        )

        # Create dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = f"Test Schedule {member.name}"
        dues_schedule.member = member.name
        dues_schedule.membership_type = "Test Membership"
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.dues_rate = 30.0
        dues_schedule.next_invoice_date = today()
        dues_schedule.status = "Active"
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)

        # Test eligibility validation - should PASS
        is_eligible = dues_schedule.validate_member_eligibility_for_invoice()
        self.assertTrue(is_eligible, "Member with valid SEPA setup should be eligible for invoicing")

        # Generate invoice
        invoice_name = dues_schedule.create_sales_invoice()
        self.assertIsNotNone(invoice_name, "Invoice should be created for member with valid SEPA setup")
        self.track_doc("Sales Invoice", invoice_name)

        # This member should also be eligible for DD batch inclusion
        # (That would be tested in DD batch creation tests)

    def test_bulk_invoice_generation_excludes_ineligible_members(self):
        """
        WHAT THIS TEST DOES:
        Tests bulk invoice generation behavior with a mix of member types to ensure
        proper filtering. This validates that the system correctly includes members
        with broken payment data while excluding truly ineligible members.
        
        TEST SEQUENCE:
        1. Create three different member types:
           - Valid SEPA member with active mandate
           - SEPA member with missing mandate (broken payment data)
           - Terminated member (truly ineligible)
        2. Create dues schedules for all members
        3. Test individual eligibility validation
        4. Test invoice generation for eligible members
        5. Verify terminated member cannot generate invoices
        
        EXPECTED BEHAVIOR:
        - Valid SEPA member: eligible and gets invoice
        - Broken SEPA member: eligible and gets invoice (NEW BEHAVIOR)
        - Terminated member: not eligible, no invoice
        - System properly separates payment validation from member eligibility
        """
        # Create mix of members
        
        # 1. Valid member with SEPA
        valid_sepa_member = self.create_test_member(
            first_name="ValidSEPA",
            last_name="BulkTest",
            email=f"valid.sepa.bulk.{frappe.generate_hash(length=6)}@example.com",
            payment_method="SEPA Direct Debit",
            iban="NL13TEST0123456789",
            account_holder_name="ValidSEPA BulkTest"
        )
        self.create_test_membership(member=valid_sepa_member.name, membership_type="Test Membership")
        self.create_test_sepa_mandate(member=valid_sepa_member.name, status="Active", is_active=1)
        
        # 2. Member with SEPA but no mandate (should still get invoice)
        broken_sepa_member = self.create_test_member(
            first_name="BrokenSEPA",
            last_name="BulkTest",
            email=f"broken.sepa.bulk.{frappe.generate_hash(length=6)}@example.com",
            payment_method="SEPA Direct Debit",
            iban="NL13TEST0123456789",
            account_holder_name="BrokenSEPA BulkTest"
        )
        self.create_test_membership(member=broken_sepa_member.name, membership_type="Test Membership")
        # No SEPA mandate created
        
        # 3. Terminated member (should not get invoice)
        terminated_member = self.create_test_member(
            first_name="Terminated",
            last_name="BulkTest",
            email=f"terminated.bulk.{frappe.generate_hash(length=6)}@example.com",
            status="Terminated"
        )
        self.create_test_membership(member=terminated_member.name, membership_type="Test Membership")
        
        # Create dues schedules for all
        for member in [valid_sepa_member, broken_sepa_member, terminated_member]:
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.schedule_name = f"Test Schedule {member.name}"
            dues_schedule.member = member.name
            dues_schedule.membership_type = "Test Membership"
            dues_schedule.billing_frequency = "Monthly"
            dues_schedule.dues_rate = 25.0
            dues_schedule.next_invoice_date = today()
            dues_schedule.status = "Active"
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)

        # Test individual eligibility
        valid_schedule = frappe.get_doc("Membership Dues Schedule", {"member": valid_sepa_member.name})
        broken_schedule = frappe.get_doc("Membership Dues Schedule", {"member": broken_sepa_member.name})
        terminated_schedule = frappe.get_doc("Membership Dues Schedule", {"member": terminated_member.name})

        # Assertions
        self.assertTrue(valid_schedule.validate_member_eligibility_for_invoice(),
                       "Valid SEPA member should be eligible")
        self.assertTrue(broken_schedule.validate_member_eligibility_for_invoice(),
                       "Broken SEPA member should STILL be eligible (new behavior)")
        self.assertFalse(terminated_schedule.validate_member_eligibility_for_invoice(),
                        "Terminated member should NOT be eligible")

        # Test invoice generation
        valid_invoice = valid_schedule.create_sales_invoice()
        broken_invoice = broken_schedule.create_sales_invoice()
        
        self.assertIsNotNone(valid_invoice, "Valid SEPA member should get invoice")
        self.assertIsNotNone(broken_invoice, "Broken SEPA member should STILL get invoice")
        self.track_doc("Sales Invoice", valid_invoice)
        self.track_doc("Sales Invoice", broken_invoice)

        # Terminated member should not be able to generate invoice
        can_generate_terminated, reason = terminated_schedule.can_generate_invoice()
        self.assertFalse(can_generate_terminated, "Terminated member should not be able to generate invoice")


if __name__ == "__main__":
    # Allow running this test directly
    import unittest
    unittest.main()