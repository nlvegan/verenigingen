#!/usr/bin/env python3
"""
Integration test for the new Customer-Member direct linking system
"""

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase


class TestCustomerMemberLinkIntegration(VereningingenTestCase):
    
    def test_customer_member_direct_link(self):
        """Test the new Customer.member field works correctly"""
        # Create a test member
        member = self.create_test_member(
            first_name="Link",
            last_name="Test", 
            email="linktest@example.com"
        )
        
        # Create customer using the updated factory method
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.member = member.name  # Direct link
        customer.save()
        self.track_doc("Customer", customer.name)
        
        # Update member with customer link
        member.customer = customer.name
        member.save()
        
        # Test 1: Verify direct customer.member field is set
        customer_member_field = frappe.db.get_value("Customer", customer.name, "member")
        self.assertEqual(customer_member_field, member.name)
        
        # Test 2: Verify the API function works with new field
        from verenigingen.api.customer_member_link import get_member_from_customer
        api_result = get_member_from_customer(customer.name)
        self.assertIsNotNone(api_result)
        self.assertEqual(api_result["name"], member.name)
        
        # Test 3: Verify cleanup will find customer via both methods
        customers_via_member = frappe.db.get_value("Member", member.name, "customer")
        customers_via_customer = frappe.db.get_value("Customer", {"member": member.name}, "name")
        
        self.assertEqual(customers_via_member, customer.name)
        self.assertEqual(customers_via_customer, customer.name)

    def test_membership_application_flow(self):
        """Test customer creation during membership application approval"""
        # Create a membership application using factory
        application = self.create_test_membership_application(
            first_name="App",
            last_name="Test",
            email="apptest@example.com"
        )
        
        # Mock the approval process by using the utility function directly
        from verenigingen.utils.application_payments import create_customer_for_member
        
        # Create member first (normally done by application)
        member = self.create_test_member(
            first_name=application.first_name,
            last_name=application.last_name,
            email=application.email
        )
        
        # Create customer using the updated function
        customer = create_customer_for_member(member)
        self.track_doc("Customer", customer.name)
        
        # Update member with customer link
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
        
        # Create SEPA mandate using factory method (which should create customer)
        mandate = self.create_test_sepa_mandate(member=member.name)
        
        # Verify customer was created and linked properly
        member.reload()
        customer_name = member.customer
        self.assertIsNotNone(customer_name)
        
        # Check customer.member field is set
        customer_member_field = frappe.db.get_value("Customer", customer_name, "member")
        self.assertEqual(customer_member_field, member.name)