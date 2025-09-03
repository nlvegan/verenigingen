#!/usr/bin/env python3
"""
Test script for consolidated MemberFinancialHistoryManager

This validates that the new consolidated approach works correctly
and doesn't clear payment history like the old system did.
"""

import frappe

frappe.init(site="dev.veganisme.net")
frappe.connect()


def test_payment_history_consolidation():
    """Test that payment history updates work with the new consolidated manager"""
    print("=== Testing Payment History Consolidation ===")

    try:
        # Get a test member
        member = frappe.get_doc("Member", "Assoc-Member-2025-07-0030")
        print(f"Testing member: {member.name}")
        print(f"Customer: {member.customer}")

        # Check current payment history count
        initial_count = len(member.payment_history) if member.payment_history else 0
        print(f"Initial payment history entries: {initial_count}")

        # Get an existing invoice for this customer
        if member.customer:
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "docstatus": 1},
                fields=["name"],
                limit=1,
            )

            if invoices:
                test_invoice = invoices[0].name
                print(f"Testing with invoice: {test_invoice}")

                # Test atomic update (should not clear all history)
                print("Testing atomic update...")
                member.add_invoice_to_payment_history(test_invoice)

                # Reload to check results
                member.reload()
                new_count = len(member.payment_history) if member.payment_history else 0
                print(f"Payment history entries after update: {new_count}")

                # Should have same or more entries (never fewer)
                if new_count >= initial_count:
                    print("✅ SUCCESS: Payment history was not cleared!")

                    # Show recent entries
                    print("\nMost recent entries:")
                    for i, entry in enumerate(member.payment_history[:5]):
                        print(f"  {i+1}. Invoice: {entry.invoice}, Status: {entry.payment_status}")

                else:
                    print("❌ FAILURE: Payment history count decreased!")

            else:
                print("No invoices found for testing")
        else:
            print("Member has no customer record")

    except Exception as e:
        print(f"❌ ERROR: {e}")


def test_expense_history_consolidation():
    """Test that expense history uses the same consolidated approach"""
    print("\n=== Testing Expense History Consolidation ===")

    try:
        # Find a member with volunteer expenses
        members_with_expenses = frappe.db.sql(
            """
            SELECT DISTINCT m.name, m.first_name, m.last_name
            FROM `tabMember` m
            INNER JOIN `tabMember Volunteer Expenses` ve ON ve.parent = m.name
            LIMIT 1
        """,
            as_dict=True,
        )

        if members_with_expenses:
            member_name = members_with_expenses[0].name
            member = frappe.get_doc("Member", member_name)

            print(f"Testing member: {member.name}")
            initial_count = len(member.volunteer_expenses) if member.volunteer_expenses else 0
            print(f"Initial expense entries: {initial_count}")

            if member.volunteer_expenses:
                # Test updating an existing expense
                test_expense = member.volunteer_expenses[0].expense_claim
                print(f"Testing with expense: {test_expense}")

                member.add_expense_to_history(test_expense)

                member.reload()
                new_count = len(member.volunteer_expenses) if member.volunteer_expenses else 0
                print(f"Expense entries after update: {new_count}")

                if new_count >= initial_count:
                    print("✅ SUCCESS: Expense history handled correctly!")
                else:
                    print("❌ FAILURE: Expense history count decreased!")

        else:
            print("No members with expense history found for testing")

    except Exception as e:
        print(f"❌ ERROR: {e}")


def test_sorting_and_limits():
    """Test that entries are properly sorted (newest first) and limited to 30"""
    print("\n=== Testing Sorting and Limits ===")

    try:
        from verenigingen.utils.member_financial_history_manager import get_payment_history_manager

        # Find a member with payment history
        members = frappe.get_all("Member", filters={"customer": ["!=", ""]}, fields=["name"], limit=1)

        if members:
            member = frappe.get_doc("Member", members[0].name)
            print(f"Testing sorting for member: {member.name}")

            if member.payment_history:
                print(f"Payment history entries: {len(member.payment_history)}")
                print("✅ Entry limit check:", "PASS" if len(member.payment_history) <= 30 else "FAIL")

                # Check sorting (newest first by posting_date)
                dates = [entry.posting_date for entry in member.payment_history[:5] if entry.posting_date]
                if dates:
                    is_sorted = all(dates[i] >= dates[i + 1] for i in range(len(dates) - 1))
                    print("✅ Sorting check:", "PASS" if is_sorted else "FAIL")
                    print(f"Sample dates: {dates}")

        else:
            print("No members found for sorting test")

    except Exception as e:
        print(f"❌ ERROR: {e}")


if __name__ == "__main__":
    print("Testing Consolidated Member Financial History Manager")
    print("=" * 60)

    test_payment_history_consolidation()
    test_expense_history_consolidation()
    test_sorting_and_limits()

    print("\n" + "=" * 60)
    print("Test completed!")
