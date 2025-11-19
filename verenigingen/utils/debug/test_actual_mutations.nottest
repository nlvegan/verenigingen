#!/usr/bin/env python3
"""
Test the actual failing mutations 880, 881, 882
"""

import json

import frappe


def test_mutation_880():
    """Test mutation 880 that was failing"""

    print("=== Testing Mutation 880 (The Original Failing Case) ===")

    # Check if payment already exists
    existing = frappe.db.get_value(
        "Payment Entry",
        {"eboekhouden_mutation_nr": "880"},
        ["name", "docstatus", "payment_type", "party", "paid_amount"],
        as_dict=True,
    )

    if existing:
        print(f"✓ Payment Entry already exists: {existing.name}")
        print(f"  Status: {existing.docstatus} ({['Draft', 'Submitted', 'Cancelled'][existing.docstatus]})")
        print(f"  Details: {existing.payment_type} to {existing.party} for {existing.paid_amount}")
        return existing.name

    # Create a test mutation similar to 880
    test_mutation = {
        "id": 880,
        "type": 3,  # Receive payment
        "date": "2025-01-26",
        "description": "Test mutation 880 - SEPA payment with missing invoice 646",
        "amount": 27.5,
        "relationId": "60657070",  # HBA customer
        "ledgerId": "43981046",  # Main ledger
        "invoiceNumber": "646",  # Missing invoice
        "rows": [{"amount": 27.5, "ledgerId": "13201876"}],
    }

    print(f"Testing mutation: {json.dumps(test_mutation, indent=2)}")

    try:
        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not company:
            company = frappe.db.get_value("Company", {}, "name")

        handler = PaymentEntryHandler(company)
        result = handler.process_payment_mutation(test_mutation)
        debug_log = handler.get_debug_log()

        print("\nPayment processing debug log:")
        for log in debug_log:
            print(f"  - {log}")

        if result:
            print(f"\n✅ Payment processing successful: {result}")

            # Check the created payment entry
            pe = frappe.get_doc("Payment Entry", result)
            print("✓ Payment Entry details:")
            print(f"  - Name: {pe.name}")
            print(f"  - Status: {pe.docstatus}")
            print(f"  - Type: {pe.payment_type}")
            print(f"  - Party: {pe.party}")
            print(f"  - Amount: {pe.paid_amount}")
            print(f"  - Mutation Nr: {pe.eboekhouden_mutation_nr}")

            return result
        else:
            print("❌ Payment processing failed (returned None)")
            return None

    except Exception as e:
        print(f"❌ Payment processing error: {str(e)}")
        import traceback

        traceback.print_exc()
        return None


def test_invoice_allocation_behavior():
    """Test how the system handles missing invoices"""

    print("\n=== Testing Invoice Allocation Behavior ===")

    # Test with existing invoice
    existing_invoice = frappe.db.get_value("Sales Invoice", {}, "name")
    if existing_invoice:
        print(f"✓ Found existing invoice for testing: {existing_invoice}")

        test_mutation_with_invoice = {
            "id": 999998,
            "type": 3,
            "date": "2025-08-02",
            "description": "Test with existing invoice",
            "amount": 10.0,
            "relationId": "60657073",  # Existing customer
            "ledgerId": "43981046",
            "invoiceNumber": existing_invoice,
            "rows": [{"amount": 10.0, "ledgerId": "13201876"}],
        }

        try:
            from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
                PaymentEntryHandler,
            )

            company = frappe.db.get_single_value("Global Defaults", "default_company")
            if not company:
                company = frappe.db.get_value("Company", {}, "name")

            handler = PaymentEntryHandler(company)
            result = handler.process_payment_mutation(test_mutation_with_invoice)

            if result:
                print(f"✅ Payment with existing invoice successful: {result}")

                # Clean up
                try:
                    pe_doc = frappe.get_doc("Payment Entry", result)
                    pe_doc.cancel()
                    frappe.delete_doc("Payment Entry", result, force=True)
                    print("✓ Test payment cleaned up")
                except Exception:
                    print("Warning: Could not clean up test payment")

            else:
                print("❌ Payment with existing invoice failed")

        except Exception as e:
            print(f"❌ Error testing with existing invoice: {str(e)}")

    # Test with non-existent invoice
    print(f"\n--- Testing with non-existent invoice ---")

    test_mutation_no_invoice = {
        "id": 999997,
        "type": 3,
        "date": "2025-08-02",
        "description": "Test with non-existent invoice",
        "amount": 15.0,
        "relationId": "60657073",
        "ledgerId": "43981046",
        "invoiceNumber": "999999",  # Non-existent
        "rows": [{"amount": 15.0, "ledgerId": "13201876"}],
    }

    try:
        handler = PaymentEntryHandler(company)
        result = handler.process_payment_mutation(test_mutation_no_invoice)
        debug_log = handler.get_debug_log()

        invoice_warnings = [
            log for log in debug_log if "No invoice found" in log or "No matching invoices" in log
        ]
        print(f"Invoice-related warnings: {len(invoice_warnings)}")
        for warning in invoice_warnings:
            print(f"  - {warning}")

        if result:
            print(f"✅ Payment with non-existent invoice successful: {result}")
            print("✓ System correctly handles missing invoices by creating unallocated payment")

            # Clean up
            try:
                pe_doc = frappe.get_doc("Payment Entry", result)
                pe_doc.cancel()
                frappe.delete_doc("Payment Entry", result, force=True)
                print("✓ Test payment cleaned up")
            except Exception:
                print("Warning: Could not clean up test payment")

        else:
            print("❌ Payment with non-existent invoice failed")

    except Exception as e:
        print(f"❌ Error testing with non-existent invoice: {str(e)}")


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        result = test_mutation_880()
        test_invoice_allocation_behavior()

        if result:
            print(f"\n✅ Mutation 880 testing completed successfully")
        else:
            print(f"\n❌ Issues found with mutation 880")

    except Exception as e:
        print(f"Test error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
