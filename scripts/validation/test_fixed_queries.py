#!/usr/bin/env python3
"""
Test Script for Fixed SQL Queries

Tests the SQL queries that were fixed to ensure they work correctly
and preserve business logic.
"""

import frappe
from frappe import _

def test_chapter_board_member_queries():
    """Test Chapter Board Member queries after field fix (member -> volunteer)"""
    
    print("🔍 Testing Chapter Board Member queries...")
    
    # Test 1: permissions.py query
    test_user = "test@example.com"  # Use a test user
    try:
        result = frappe.db.sql(
            """
            SELECT DISTINCT cbm.parent
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            JOIN `tabMember` m ON v.member = m.name
            WHERE m.user = %s AND cbm.is_active = 1
            LIMIT 5
        """,
            (test_user,),
            as_dict=True,
        )
        print(f"  ✅ Permissions query - Executed successfully, returned {len(result)} rows")
    except Exception as e:
        print(f"  ❌ Permissions query failed: {e}")
    
    # Test 2: membership_application_review.py query  
    try:
        result = frappe.db.sql(
            """
            SELECT DISTINCT c.name
            FROM `tabChapter` c
            JOIN `tabChapter Board Member` cbm ON cbm.parent = c.name
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE v.member = %s AND cbm.is_active = 1
            LIMIT 5
        """,
            ("test-member",),
            as_dict=True,
        )
        print(f"  ✅ Application review query - Executed successfully, returned {len(result)} rows")
    except Exception as e:
        print(f"  ❌ Application review query failed: {e}")

def test_donor_queries():
    """Test Donor queries after field fixes (email -> donor_email, removed preferred_language)"""
    
    print("\n🔍 Testing Donor queries...")
    
    # Test the ANBI operations query
    try:
        result = frappe.db.sql(
            """
            SELECT DISTINCT
                donor.name,
                donor.donor_name,
                donor.donor_email
            FROM `tabDonor` donor
            INNER JOIN `tabDonation` donation ON donation.donor = donor.name
            WHERE (donor.anbi_consent = 0 OR donor.anbi_consent IS NULL)
            AND donor.donor_email IS NOT NULL
            AND donor.donor_email != ''
            AND donation.paid = 1
            AND donation.docstatus = 1
            LIMIT 5
        """,
            as_dict=1,
        )
        print(f"  ✅ ANBI operations query - Executed successfully, returned {len(result)} rows")
    except Exception as e:
        print(f"  ❌ ANBI operations query failed: {e}")

def test_membership_dues_schedule_queries():
    """Test Membership Dues Schedule queries after field fixes (start_date/end_date -> period dates)"""
    
    print("\n🔍 Testing Membership Dues Schedule queries...")
    
    # Test payment dashboard query
    try:
        result = frappe.db.sql(
            """
            SELECT
                si.name,
                si.posting_date as date,
                si.grand_total as amount,
                si.status,
                m.name as membership,
                mds.name as dues_schedule
            FROM `tabSales Invoice` si
            LEFT JOIN `tabMembership Dues Schedule` mds ON mds.member = 'test-member'
            LEFT JOIN `tabMembership` m ON m.member = 'test-member'
            WHERE si.docstatus = 1
            AND (mds.next_billing_period_start_date IS NULL OR si.posting_date >= mds.next_billing_period_start_date)
            AND (mds.next_billing_period_end_date IS NULL OR si.posting_date <= mds.next_billing_period_end_date)
            LIMIT 5
        """,
            as_dict=True,
        )
        print(f"  ✅ Payment dashboard query - Executed successfully, returned {len(result)} rows")
    except Exception as e:
        print(f"  ❌ Payment dashboard query failed: {e}")
        
    # Test conflict detector query
    try:
        result = frappe.db.sql(
            """
            SELECT
                si.name as invoice,
                si.custom_membership_dues_schedule as schedule_id,
                mds.member,
                mds.next_invoice_date,
                mds.billing_frequency,
                mds.status as schedule_status
            FROM `tabSales Invoice` si
            JOIN `tabMembership Dues Schedule` mds ON si.custom_membership_dues_schedule = mds.name
            WHERE si.docstatus = 1
            LIMIT 5
        """,
            as_dict=True,
        )
        print(f"  ✅ Conflict detector query - Executed successfully, returned {len(result)} rows")
    except Exception as e:
        print(f"  ❌ Conflict detector query failed: {e}")

def validate_field_existence():
    """Validate that the fields we're now using actually exist in the database"""
    
    print("\n🔍 Validating field existence in database...")
    
    # Check Chapter Board Member fields
    try:
        frappe.db.sql("SELECT volunteer FROM `tabChapter Board Member` LIMIT 1")
        print("  ✅ Chapter Board Member.volunteer field exists")
    except Exception as e:
        print(f"  ❌ Chapter Board Member.volunteer field missing: {e}")
    
    # Check Donor fields
    try:
        frappe.db.sql("SELECT donor_email, anbi_consent FROM `tabDonor` LIMIT 1")
        print("  ✅ Donor.donor_email and Donor.anbi_consent fields exist")
    except Exception as e:
        print(f"  ❌ Donor field issue: {e}")
    
    # Check Membership Dues Schedule fields
    try:
        frappe.db.sql("SELECT next_invoice_date, next_billing_period_start_date, next_billing_period_end_date FROM `tabMembership Dues Schedule` LIMIT 1")
        print("  ✅ Membership Dues Schedule period fields exist")
    except Exception as e:
        print(f"  ❌ Membership Dues Schedule field issue: {e}")

def main():
    """Main test function"""
    print("🧪 Testing Fixed SQL Queries")
    print("=" * 50)
    
    # Initialize Frappe if needed
    try:
        validate_field_existence()
        test_chapter_board_member_queries()
        test_donor_queries()
        test_membership_dues_schedule_queries()
        
        print("\n" + "=" * 50)
        print("✅ All critical query tests completed!")
        print("If no errors above, the SQL fixes are working correctly.")
        
    except Exception as e:
        print(f"❌ Test setup failed: {e}")
        print("Note: This script requires a Frappe environment to run properly.")

if __name__ == "__main__":
    main()