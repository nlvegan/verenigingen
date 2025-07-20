#!/usr/bin/env python3
"""
Simple test for the new Customer-Member direct linking system
"""

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase


class TestCustomerMemberLinkSimple(VereningingenTestCase):
    
    def test_customer_member_direct_link_simple(self):
        """Test the new Customer.member field works correctly"""
        # Create a test member
        member = self.create_test_member(
            first_name="Simple",
            last_name="LinkTest", 
            email="simple.linktest@example.com"
        )
        
        # Create customer with direct link
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.member = member.name  # NEW: Direct link to member
        customer.save()
        self.track_doc("Customer", customer.name)
        
        # Update member with customer link (bidirectional)
        member.customer = customer.name
        member.save()
        
        # Test 1: Verify direct customer.member field is set
        customer_member_field = frappe.db.get_value("Customer", customer.name, "member")
        self.assertEqual(customer_member_field, member.name, "Customer.member field should link to member")
        
        # Test 2: Verify the API function works with new field
        from verenigingen.api.customer_member_link import get_member_from_customer
        api_result = get_member_from_customer(customer.name)
        self.assertIsNotNone(api_result, "API should find member from customer")
        self.assertEqual(api_result["name"], member.name, "API should return correct member")
        
        # Test 3: Verify both lookup methods work (for cleanup)
        customers_via_member = frappe.db.get_value("Member", member.name, "customer")
        customers_via_customer = frappe.db.get_value("Customer", {"member": member.name}, "name")
        
        self.assertEqual(customers_via_member, customer.name, "Member.customer should link to customer")
        self.assertEqual(customers_via_customer, customer.name, "Customer lookup by member should work")
        
    def test_application_payments_utility(self):
        """Test the updated create_customer_for_member function"""
        from verenigingen.utils.application_payments import create_customer_for_member
        
        # Create member
        member = self.create_test_member(
            first_name="Utility",
            last_name="Test",
            email="utility.test@example.com"
        )
        
        # Create customer using updated utility function
        customer = create_customer_for_member(member)
        self.track_doc("Customer", customer.name)
        
        # Update member with customer link
        member.customer = customer.name
        member.save()
        
        # Verify the customer.member field was set during creation
        customer_member_field = frappe.db.get_value("Customer", customer.name, "member") 
        self.assertEqual(customer_member_field, member.name, "create_customer_for_member should set customer.member field")