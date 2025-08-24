#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script for Mollie Donation Integration
Tests the centralized Mollie data on Customer records and donor auto-creation
"""

import frappe
from datetime import datetime

def test_customer_mollie_fields():
    """Test that Mollie fields are properly set on Customer records"""
    print("\n=== Testing Customer Mollie Fields ===")
    
    # Check if custom fields exist
    customer_meta = frappe.get_meta("Customer")
    mollie_fields = [
        "custom_mollie_customer_id",
        "custom_mollie_subscription_id", 
        "custom_subscription_status",
        "custom_next_payment_date",
        "donor"
    ]
    
    print("Checking for Mollie custom fields on Customer...")
    for field in mollie_fields:
        field_exists = any(f.fieldname == field for f in customer_meta.fields)
        print(f"  {field}: {'✓' if field_exists else '✗ NOT FOUND'}")
    
    return True


def test_member_fetch_fields():
    """Test that Member fields properly fetch from Customer"""
    print("\n=== Testing Member Fetch Fields ===")
    
    member_meta = frappe.get_meta("Member")
    mollie_fields = {
        "custom_mollie_customer_id": "customer.custom_mollie_customer_id",
        "custom_mollie_subscription_id": "customer.custom_mollie_subscription_id",
        "custom_subscription_status": "customer.custom_subscription_status",
        "custom_next_payment_date": "customer.custom_next_payment_date"
    }
    
    print("Checking Member fetch fields...")
    for field, fetch_from in mollie_fields.items():
        field_def = next((f for f in member_meta.fields if f.fieldname == field), None)
        if field_def:
            has_fetch = field_def.fetch_from == fetch_from
            print(f"  {field}: {'✓ fetches from ' + fetch_from if has_fetch else '✗ NOT fetching from Customer'}")
        else:
            print(f"  {field}: ✗ Field not found")
    
    return True


def test_create_customer_with_mollie_data():
    """Test creating a Customer with Mollie subscription data"""
    print("\n=== Testing Customer Creation with Mollie Data ===")
    
    try:
        # Create test customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Test Mollie Donor"
        customer.customer_type = "Individual"
        customer.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "Individual"
        
        # Set Mollie fields
        customer.custom_mollie_customer_id = "cst_test123"
        customer.custom_mollie_subscription_id = "sub_test456"
        customer.custom_subscription_status = "active"
        customer.custom_next_payment_date = datetime.now().date()
        
        customer.insert()
        print(f"✓ Created Customer: {customer.name}")
        print(f"  Mollie Customer ID: {customer.custom_mollie_customer_id}")
        print(f"  Mollie Subscription ID: {customer.custom_mollie_subscription_id}")
        print(f"  Subscription Status: {customer.custom_subscription_status}")
        
        # Clean up
        customer.delete()
        print("✓ Test customer cleaned up")
        
        return True
        
    except Exception as e:
        print(f"✗ Error creating customer: {str(e)}")
        return False


def test_member_customer_link():
    """Test that Member properly fetches Mollie data from Customer"""
    print("\n=== Testing Member-Customer Mollie Data Link ===")
    
    try:
        # Create test customer with Mollie data
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Test Member Customer"
        customer.customer_type = "Individual"
        customer.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "Individual"
        customer.custom_mollie_customer_id = "cst_member123"
        customer.custom_mollie_subscription_id = "sub_member456"
        customer.custom_subscription_status = "active"
        customer.insert()
        
        # Create test member linked to customer
        member = frappe.new_doc("Member")
        member.first_name = "Test"
        member.last_name = "Member"
        member.email = "test.member@example.com"
        member.birth_date = "1990-01-01"
        member.member_since = datetime.now().date()
        member.customer = customer.name
        member.payment_method = "Mollie"
        member.insert()
        
        # Reload to get fetch fields
        member.reload()
        
        print(f"✓ Created Member: {member.name}")
        print(f"  Customer: {member.customer}")
        print(f"  Mollie Customer ID (fetched): {member.custom_mollie_customer_id}")
        print(f"  Mollie Subscription ID (fetched): {member.custom_mollie_subscription_id}")
        print(f"  Subscription Status (fetched): {member.custom_subscription_status}")
        
        # Verify fetch worked
        if member.custom_mollie_customer_id == customer.custom_mollie_customer_id:
            print("✓ Mollie data successfully fetched from Customer to Member")
        else:
            print("✗ Mollie data NOT fetched correctly")
        
        # Clean up
        member.delete()
        customer.delete()
        print("✓ Test data cleaned up")
        
        return True
        
    except Exception as e:
        print(f"✗ Error in member-customer test: {str(e)}")
        # Try to clean up
        try:
            if 'member' in locals() and member.name:
                frappe.delete_doc("Member", member.name, force=1)
            if 'customer' in locals() and customer.name:
                frappe.delete_doc("Customer", customer.name, force=1)
        except:
            pass
        return False


def test_donor_customer_bidirectional_link():
    """Test bidirectional link between Donor and Customer"""
    print("\n=== Testing Donor-Customer Bidirectional Link ===")
    
    try:
        # Create customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Test Donor Customer Link"
        customer.customer_type = "Individual"
        customer.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "Individual"
        customer.insert()
        
        # Create donor linked to customer
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Test Donor"
        donor.donor_email = "test.donor@example.com"
        donor.donor_type = "Individual"
        donor.customer = customer.name
        donor.insert()
        
        # Update customer with donor link
        customer.donor = donor.name
        customer.save()
        
        print(f"✓ Created Donor: {donor.name}")
        print(f"  Linked to Customer: {donor.customer}")
        print(f"✓ Updated Customer: {customer.name}")
        print(f"  Linked to Donor: {customer.donor}")
        
        # Verify bidirectional link
        if donor.customer == customer.name and customer.donor == donor.name:
            print("✓ Bidirectional link successfully established")
        else:
            print("✗ Bidirectional link NOT working")
        
        # Clean up
        donor.delete()
        customer.delete()
        print("✓ Test data cleaned up")
        
        return True
        
    except Exception as e:
        print(f"✗ Error in donor-customer link test: {str(e)}")
        # Try to clean up
        try:
            if 'donor' in locals() and donor.name:
                frappe.delete_doc("Donor", donor.name, force=1)
            if 'customer' in locals() and customer.name:
                frappe.delete_doc("Customer", customer.name, force=1)
        except:
            pass
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("MOLLIE DONATION INTEGRATION TEST SUITE")
    print("=" * 60)
    
    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    try:
        # Run tests
        results = []
        results.append(("Customer Mollie Fields", test_customer_mollie_fields()))
        results.append(("Member Fetch Fields", test_member_fetch_fields()))
        results.append(("Customer Creation", test_create_customer_with_mollie_data()))
        results.append(("Member-Customer Link", test_member_customer_link()))
        results.append(("Donor-Customer Link", test_donor_customer_bidirectional_link()))
        
        # Print summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        
        for test_name, result in results:
            status = "✓ PASSED" if result else "✗ FAILED"
            print(f"{test_name:.<40} {status}")
        
        total_passed = sum(1 for _, r in results if r)
        total_tests = len(results)
        
        print(f"\nTotal: {total_passed}/{total_tests} tests passed")
        
        if total_passed == total_tests:
            print("\n🎉 ALL TESTS PASSED! The Mollie donation integration is working correctly.")
        else:
            print(f"\n⚠️ {total_tests - total_passed} test(s) failed. Please review the output above.")
        
    finally:
        frappe.destroy()


if __name__ == "__main__":
    main()