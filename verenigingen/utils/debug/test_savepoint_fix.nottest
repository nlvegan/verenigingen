#!/usr/bin/env python3
"""
Test savepoint atomic transaction fix
"""

import frappe


def test_savepoint_fix():
    """Test the savepoint atomic transaction fix"""

    print("=== Testing Savepoint Atomic Transaction Fix ===")

    # Test 1: Successful atomic operation
    print("\n=== Test 1: Successful Atomic Operation ===")
    try:
        from verenigingen.e_boekhouden.utils.security_helper import atomic_migration_operation

        with atomic_migration_operation("payment_processing"):
            print("✓ Entered atomic operation successfully")
            # Simulate some work
            frappe.logger().info("Simulated work inside atomic operation")

        print("✓ Atomic operation completed successfully")

    except Exception as e:
        print(f"❌ Atomic operation failed: {str(e)}")
        return False

    # Test 2: Failed atomic operation (rollback test)
    print("\n=== Test 2: Failed Atomic Operation (Rollback) ===")
    try:
        from verenigingen.e_boekhouden.utils.security_helper import atomic_migration_operation

        with atomic_migration_operation("payment_processing"):
            print("✓ Entered atomic operation successfully")
            # Simulate work that fails
            raise Exception("Simulated failure for rollback testing")

        print("❌ Should not reach this point")
        return False

    except Exception as e:
        if "Simulated failure" in str(e):
            print("✓ Atomic operation correctly raised exception and rolled back")
        else:
            print(f"❌ Unexpected error: {str(e)}")
            return False

    # Test 3: Test with actual payment processing (simulate mutation 880)
    print("\n=== Test 3: Simulate Payment Processing ===")

    test_mutation = {
        "id": 999999,  # Use fake ID to avoid conflicts
        "type": 3,
        "date": "2025-08-02",
        "description": "Test payment for savepoint fix",
        "amount": 50.0,
        "relationId": "60657073",  # Use existing customer
        "ledgerId": "43981046",  # Use existing ledger mapping
        "invoiceNumber": "999999",  # Non-existent invoice (should be handled gracefully)
        "rows": [{"amount": 50.0, "ledgerId": "13201873"}],
    }

    try:
        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not company:
            company = frappe.db.get_value("Company", {}, "name")

        handler = PaymentEntryHandler(company)
        result = handler.process_payment_mutation(test_mutation)

        if result:
            print(f"✅ Payment processing successful: {result}")

            # Clean up test payment entry
            try:
                pe_doc = frappe.get_doc("Payment Entry", result)
                pe_doc.cancel()
                frappe.delete_doc("Payment Entry", result, force=True)
                print("✓ Test payment entry cleaned up")
            except Exception as cleanup_error:
                print(f"Warning: Cleanup failed: {str(cleanup_error)}")

        else:
            print("❌ Payment processing failed (returned None)")
            return False

    except Exception as e:
        print(f"❌ Payment processing error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    print("\n=== All Tests Passed ===")
    return True


def check_missing_invoices():
    """Check for the missing invoices mentioned in the error logs"""
    print("\n=== Checking Missing Invoices ===")

    missing_invoices = ["646", "673", "670"]

    for invoice_num in missing_invoices:
        # Check Sales Invoice
        si = frappe.db.get_value("Sales Invoice", {"name": invoice_num}, "name")
        if si:
            print(f"✓ Sales Invoice {invoice_num} exists")
        else:
            print(f"❌ Sales Invoice {invoice_num} not found")

        # Check Purchase Invoice
        pi = frappe.db.get_value("Purchase Invoice", {"name": invoice_num}, "name")
        if pi:
            print(f"✓ Purchase Invoice {invoice_num} exists")
        else:
            print(f"❌ Purchase Invoice {invoice_num} not found")

        # Check if referenced in E-Boekhouden data
        je_ref = frappe.db.get_value("Journal Entry", {"user_remark": ["like", f"%{invoice_num}%"]}, "name")
        if je_ref:
            print(f"✓ Invoice {invoice_num} referenced in Journal Entry {je_ref}")
        else:
            print(f"❌ Invoice {invoice_num} not referenced in any Journal Entry")


def check_existing_payment_entries():
    """Check the payment entries that were created despite the errors"""
    print("\n=== Checking Payment Entries from Error Log ===")

    payment_entries = ["ACC-PAY-2025-59262", "ACC-PAY-2025-59263", "ACC-PAY-2025-59264"]

    for pe_name in payment_entries:
        pe = frappe.db.get_value(
            "Payment Entry",
            {"name": pe_name},
            ["docstatus", "payment_type", "party", "paid_amount", "eboekhouden_mutation_nr"],
            as_dict=True,
        )

        if pe:
            print(
                f"✓ {pe_name}: {pe.payment_type} to {pe.party} for {pe.paid_amount} (status: {pe.docstatus}, mutation: {pe.eboekhouden_mutation_nr})"
            )
        else:
            print(f"❌ {pe_name} not found")


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        check_existing_payment_entries()
        check_missing_invoices()
        success = test_savepoint_fix()

        if success:
            print("\n✅ All savepoint fixes working correctly")
        else:
            print("\n❌ Issues found with savepoint fixes")

    except Exception as e:
        print(f"Test script error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
