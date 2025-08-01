#!/usr/bin/env python3
"""
Test script for incremental history table update system
Tests with specific member Assoc-Member-2025-07-0030
"""

import frappe
from frappe.utils import now_datetime, add_days, today


def test_member_incremental_update():
    """Test the incremental update functionality with the specific member"""
    try:
        member_name = "Assoc-Member-2025-07-0030"
        print(f"Testing incremental update for member: {member_name}")
        
        # Get the member document
        member_doc = frappe.get_doc("Member", member_name)
        print(f"Member found: {member_doc.name}")
        print(f"Member employee: {getattr(member_doc, 'employee', 'None')}")
        print(f"Member donor: {getattr(member_doc, 'donor', 'None')}")
        
        # Check current volunteer expenses
        current_expenses = getattr(member_doc, 'volunteer_expenses', [])
        print(f"Current volunteer expense entries: {len(current_expenses)}")
        for idx, expense in enumerate(current_expenses):
            print(f"  {idx+1}. {expense.expense_claim} - {expense.status} - {expense.total_sanctioned_amount}")
        
        # Check if member has employee and what expense claims exist
        if hasattr(member_doc, 'employee') and member_doc.employee:
            print(f"\nChecking expense claims for employee: {member_doc.employee}")
            
            # Get expense claims from database
            expense_claims = frappe.get_all(
                "Expense Claim",
                filters={"employee": member_doc.employee},
                fields=["name", "posting_date", "total_claimed_amount", "total_sanctioned_amount", 
                       "status", "approval_status", "docstatus"],
                order_by="posting_date desc",
                limit=25
            )
            
            print(f"Found {len(expense_claims)} expense claims in database:")
            for claim in expense_claims:
                print(f"  - {claim.name}: {claim.status} (docstatus: {claim.docstatus}) - {claim.total_sanctioned_amount}")
        
        # Test the incremental update method
        print(f"\nTesting incremental_update_history_tables method...")
        
        # Check if method exists
        if hasattr(member_doc, 'incremental_update_history_tables'):
            print("Method exists on member document")
            
            # Call the method
            result = member_doc.incremental_update_history_tables()
            print(f"Method result: {result}")
            
            # Check the updated expenses after the call
            member_doc.reload()
            updated_expenses = getattr(member_doc, 'volunteer_expenses', [])
            print(f"Volunteer expense entries after update: {len(updated_expenses)}")
            for idx, expense in enumerate(updated_expenses):
                print(f"  {idx+1}. {expense.expense_claim} - {expense.status} - {expense.total_sanctioned_amount}")
            
        else:
            print("ERROR: incremental_update_history_tables method not found on member document")
            
        return True
        
    except Exception as e:
        print(f"Error in test: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_expense_mixin_build_method():
    """Test the _build_expense_history_entry method"""
    try:
        member_name = "Assoc-Member-2025-07-0030"
        member_doc = frappe.get_doc("Member", member_name)
        
        if hasattr(member_doc, 'employee') and member_doc.employee:
            # Get an expense claim to test with
            expense_claims = frappe.get_all(
                "Expense Claim",
                filters={"employee": member_doc.employee},
                fields=["name"],
                limit=1
            )
            
            if expense_claims:
                expense_name = expense_claims[0].name
                print(f"Testing _build_expense_history_entry with: {expense_name}")
                
                expense_doc = frappe.get_doc("Expense Claim", expense_name)
                print(f"Expense claim details:")
                print(f"  Name: {expense_doc.name}")
                print(f"  Employee: {expense_doc.employee}")
                print(f"  Posting Date: {expense_doc.posting_date}")
                print(f"  Total Claimed: {expense_doc.total_claimed_amount}")
                print(f"  Total Sanctioned: {expense_doc.total_sanctioned_amount}")
                print(f"  Status: {expense_doc.status}")
                print(f"  DocStatus: {expense_doc.docstatus}")
                
                # Test the build method
                if hasattr(member_doc, '_build_expense_history_entry'):
                    entry = member_doc._build_expense_history_entry(expense_doc)
                    print(f"Built entry: {entry}")
                else:
                    print("ERROR: _build_expense_history_entry method not found")
            else:
                print("No expense claims found for this employee")
        else:
            print(f"Member {member_name} has no employee linked")
            
    except Exception as e:
        print(f"Error testing build method: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_member_incremental_update()
    print("\n" + "="*50 + "\n")
    test_expense_mixin_build_method()