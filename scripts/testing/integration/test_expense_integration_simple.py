#!/usr/bin/env python3
"""
Simple test to verify expense integration is working
"""

import os
import sys

# Add the apps path to Python path so we can import modules
sys.path.insert(0, "/home/frappe/frappe-bench/apps")


def test_expense_integration():
    """Test the expense integration"""

    print("🧪 Testing ERPNext Expense Integration")
    print("=" * 50)

    # Test data
    expense_data = {
        "expense_date": "2025-01-14",
        "description": "Test integration expense",
        "amount": 35.75,
        "expense_type": "Travel",
        "notes": "Testing after account setup",
    }

    volunteer_name = "Foppe de  Haan"  # Use existing volunteer

    print(f"📝 Test expense data:")
    print(f"   Volunteer: {volunteer_name}")
    print(f"   Amount: €{expense_data['amount']}")
    print(f"   Description: {expense_data['description']}")

    try:
        # Import necessary modules
        import frappe

        # Initialize Frappe
        frappe.init(site="dev.veganisme.net")
        frappe.connect()
        frappe.set_user("foppe@veganisme.org")  # Foppe's email

        # Import the expense submission function
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        print("\n💰 Submitting expense...")

        # Submit the expense
        result = submit_expense(volunteer_name, expense_data)

        if result.get("success"):
            print("✅ Expense submission successful!")
            print(f"   Volunteer Expense ID: {result.get('volunteer_expense_id')}")
            print(f"   ERPNext Expense Claim ID: {result.get('erpnext_expense_claim_id')}")

            # Verify the records were created
            if result.get("volunteer_expense_id"):
                vol_expense = frappe.get_doc("Volunteer Expense", result["volunteer_expense_id"])
                print(f"   ✅ Volunteer Expense created: €{vol_expense.amount}")

            if result.get("erpnext_expense_claim_id"):
                erp_claim = frappe.get_doc("Expense Claim", result["erpnext_expense_claim_id"])
                print(f"   ✅ ERPNext Expense Claim created: {erp_claim.name}")
                print(f"   📊 Total claimed: €{erp_claim.total_claimed_amount}")

            print("\n🎉 ERPNext Expense Claims integration is working correctly!")
            return True

        else:
            print(f"❌ Expense submission failed: {result.get('message')}")
            print("ℹ️  This might indicate a configuration issue")
            return False

    except ImportError as e:
        print(f"❌ Import error: {str(e)}")
        print("ℹ️  Make sure all required modules are available")
        return False
    except Exception as e:
        print(f"❌ Error during testing: {str(e)}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        try:
            frappe.destroy()
        except:
            pass


if __name__ == "__main__":
    try:
        success = test_expense_integration()
        if success:
            print("\n✅ Integration test completed successfully!")
            sys.exit(0)
        else:
            print("\n⚠️  Integration test completed with issues")
            sys.exit(1)
    except Exception as e:
        print(f"\n💥 Fatal error: {str(e)}")
        sys.exit(1)
