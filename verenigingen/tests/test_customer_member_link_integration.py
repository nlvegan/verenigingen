#!/usr/bin/env python3
"""
Integration test for the new Customer-Member direct linking system
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCustomerMemberLinkIntegration(EnhancedTestCase):
    
    def test_customer_member_direct_link(self):
        """Test the new Customer.member field works correctly"""
        # Create a test member
        member = self.create_test_member(
            first_name="Link",
            last_name="Test",
            email="linktest@example.com"
        )

        # Check if customer already exists for this member
        existing_customer = frappe.db.get_value("Customer", {"member": member.name}, "name")
        if existing_customer:
            customer = frappe.get_doc("Customer", existing_customer)
        else:
            # Create customer using the updated factory method
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member.first_name} {member.last_name}"
            customer.customer_type = "Individual"
            customer.member = member.name  # Direct link
            customer.save()

        # Track for cleanup if method exists
        if hasattr(self, '_track_record'):
            self._track_record("Customer", customer.name)

        # Update member with customer link
        member.reload()  # Prevent TimestampMismatchError from hooks
        member.customer = customer.name
        member.save()
        
        # Test 1: Verify direct customer.member field is set
        customer_member_field = frappe.db.get_value("Customer", customer.name, "member")
        self.assertEqual(customer_member_field, member.name)
        
        # Test 2: Verify the API function works with new field
        from verenigingen.api.customer_member_link import get_member_from_customer
        api_result = get_member_from_customer(customer.name)
        self.assertTrue(api_result.success)
        self.assertIsNotNone(api_result.data)
        self.assertEqual(api_result.data["name"], member.name)
        
        # Test 3: Verify cleanup will find customer via both methods
        customers_via_member = frappe.db.get_value("Member", member.name, "customer")
        customers_via_customer = frappe.db.get_value("Customer", {"member": member.name}, "name")
        
        self.assertEqual(customers_via_member, customer.name)
        self.assertEqual(customers_via_customer, customer.name)

    def test_membership_application_flow(self):
        """Test customer creation for approved member"""
        # Mock the approval process by using the utility function directly
        from verenigingen.utils.application_payments import create_customer_for_member

        # Create member (simulating approved application)
        member = self.create_test_member(
            first_name="App",
            last_name="Test",
            email="apptest@example.com"
        )

        # Create customer using the updated function
        customer = create_customer_for_member(member)

        # Track for cleanup if method exists
        if hasattr(self, '_track_record'):
            self._track_record("Customer", customer.name)

        # Update member with customer link
        member.reload()  # Prevent TimestampMismatchError from hooks
        member.customer = customer.name
        member.save()

        # Verify the customer.member field was set during creation
        customer_member_field = frappe.db.get_value("Customer", customer.name, "member")
        self.assertEqual(customer_member_field, member.name)

    def test_sepa_mandate_creation(self):
        """Test SEPA mandate creation with new customer-member linking"""
        # Create test member
        member = self.create_test_member(
            first_name="SEPA",
            last_name="Test",
            email="sepatest@example.com"
        )

        # Create SEPA mandate using factory method with valid test IBAN
        mandate = self.create_test_sepa_mandate(
            member_name=member.name,
            iban="NL91ABNA0417164300"  # Valid test IBAN
        )

        # Verify customer was created and linked properly
        member.reload()
        customer_name = member.customer
        self.assertIsNotNone(customer_name)

        # Check customer.member field is set
        customer_member_field = frappe.db.get_value("Customer", customer_name, "member")
        self.assertEqual(customer_member_field, member.name)