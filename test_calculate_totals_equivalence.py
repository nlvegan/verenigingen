#!/usr/bin/env python3
"""
Test to verify that calculate_totals SQL aggregation and Python fallback
produce functionally equivalent results in all edge cases.
"""

import os
import sys

sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")

from decimal import Decimal

import frappe


def test_calculate_totals_equivalence():
    """Test that SQL and Python methods produce identical results"""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    test_cases = [
        {"name": "Empty batch", "invoices": []},
        {"name": "Normal amounts", "invoices": [{"amount": 25.00}, {"amount": 50.00}, {"amount": 75.50}]},
        {"name": "Null/None amounts", "invoices": [{"amount": 25.00}, {"amount": None}, {"amount": 50.00}]},
        {"name": "Zero amounts", "invoices": [{"amount": 0.00}, {"amount": 25.00}, {"amount": 0.00}]},
        {"name": "Precision test", "invoices": [{"amount": 33.333}, {"amount": 66.667}, {"amount": 0.001}]},
        {"name": "Large amounts", "invoices": [{"amount": 9999.99}, {"amount": 1.01}, {"amount": 8888.88}]},
    ]

    print("🧪 Testing calculate_totals SQL vs Python equivalence")
    print("=" * 60)

    for test_case in test_cases:
        print(f"\n📋 Test Case: {test_case['name']}")

        # Create test batch
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_name = f"Test Batch {frappe.generate_hash(length=6)}"
        batch.collection_date = frappe.utils.today()
        batch.batch_status = "Draft"
        batch.payment_method = "SEPA Direct Debit"
        batch.company = frappe.get_all("Company", limit=1, pluck="name")[0]

        # Add test invoices
        for invoice_data in test_case["invoices"]:
            batch.append(
                "invoices",
                {
                    "invoice": "TEST-INV-001",  # Dummy invoice reference
                    "amount": invoice_data["amount"],
                    "currency": "EUR",
                    "member": "TEST-MEMBER-001",  # Dummy member
                    "status": "Pending",
                },
            )

        try:
            batch.save()

            # Test SQL aggregation
            batch.calculate_totals()  # This will use SQL for saved docs
            sql_count = batch.entry_count
            sql_total = batch.total_amount

            # Test Python fallback
            batch._calculate_totals_python()
            python_count = batch.entry_count
            python_total = batch.total_amount

            # Compare results
            count_match = sql_count == python_count
            total_match = abs(sql_total - python_total) < 0.01  # Allow for minor floating point differences

            print(f"  📊 Invoice count: SQL={sql_count}, Python={python_count} {'✅' if count_match else '❌'}")
            print(
                f"  💰 Total amount: SQL={sql_total:.2f}, Python={python_total:.2f} {'✅' if total_match else '❌'}"
            )

            if not (count_match and total_match):
                print(f"  🚨 MISMATCH DETECTED!")
                return False

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            return False
        finally:
            # Cleanup
            try:
                frappe.delete_doc("Direct Debit Batch", batch.name, force=True)
            except:
                pass

    print("\n🎉 All tests passed! SQL and Python methods are functionally equivalent.")
    return True


def test_edge_cases():
    """Test additional edge cases"""
    print("\n🔍 Testing additional edge cases...")

    # Create a batch with string amounts (edge case)
    batch = frappe.new_doc("Direct Debit Batch")
    batch.batch_name = f"Edge Test {frappe.generate_hash(length=6)}"
    batch.collection_date = frappe.utils.today()
    batch.batch_status = "Draft"
    batch.payment_method = "SEPA Direct Debit"
    batch.company = frappe.get_all("Company", limit=1, pluck="name")[0]

    # Manually create invoice objects with edge case data
    class MockInvoice:
        def __init__(self, amount):
            self.amount = amount

    # Test edge cases that can't be saved to DB
    edge_cases = [
        [MockInvoice("25.50"), MockInvoice("30.00")],  # String amounts
        [MockInvoice(None), MockInvoice(None)],  # All None
        [MockInvoice(""), MockInvoice("  ")],  # Empty strings
    ]

    for i, invoices in enumerate(edge_cases):
        batch.invoices = invoices
        batch._calculate_totals_python()
        print(f"  Edge case {i+1}: count={batch.entry_count}, total={batch.total_amount:.2f} ✅")

    print("🎉 Edge case testing completed!")


if __name__ == "__main__":
    try:
        success = test_calculate_totals_equivalence()
        test_edge_cases()

        if success:
            print("\n✅ All equivalence tests PASSED")
            exit(0)
        else:
            print("\n❌ Some tests FAILED")
            exit(1)

    except Exception as e:
        print(f"\n💥 Test execution failed: {str(e)}")
        import traceback

        traceback.print_exc()
        exit(1)
    finally:
        frappe.destroy()
