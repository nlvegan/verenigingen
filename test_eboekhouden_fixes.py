#!/usr/bin/env python
"""Test script to verify eBoekhouden import fixes."""

import frappe
from frappe.utils import nowdate

from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import PaymentEntryHandler


@frappe.whitelist()
def test_payment_fixes():
    """Test the payment processing fixes."""

    # Test case 1: Zero amount payment
    test_mutation_1 = {
        "id": "TEST001",
        "type": 4,  # Supplier payment
        "amount": 0.0,
        "date": nowdate(),
        "relationId": "REL001",
        "invoiceNumber": "INV001,INV002",
        "ledgerId": 13201869,
        "description": "Test zero amount payment",
        "rows": [{"amount": 100.0, "ledgerId": 1001}, {"amount": -100.0, "ledgerId": 1002}],
    }

    # Test case 2: Payment with invoice allocation
    test_mutation_2 = {
        "id": "TEST002",
        "type": 4,
        "amount": 1000.0,
        "date": nowdate(),
        "relationId": "REL002",
        "invoiceNumber": "M2021.1",
        "ledgerId": 13201869,
        "description": "Test payment with invoice",
        "rows": [],
    }

    company = frappe.defaults.get_defaults().get("company") or "Noordelijk Veganisme Vereniging"

    handler = PaymentEntryHandler(company)

    results = []

    # Test zero amount payment
    try:
        print("Testing zero amount payment...")
        result = handler.process_payment_mutation(test_mutation_1)
        if result:
            results.append(f"✅ Zero amount payment processed successfully: {result}")
        else:
            results.append("❌ Zero amount payment failed")
    except Exception as e:
        results.append(f"❌ Zero amount payment error: {str(e)}")

    # Test payment with invoice
    try:
        print("Testing payment with invoice...")
        result = handler.process_payment_mutation(test_mutation_2)
        if result:
            results.append(f"✅ Payment with invoice processed successfully: {result}")
        else:
            results.append("❌ Payment with invoice failed")
    except Exception as e:
        results.append(f"❌ Payment with invoice error: {str(e)}")

    # Print debug log
    print("\n=== Debug Log ===")
    for log_entry in handler.get_debug_log():
        print(log_entry)

    print("\n=== Test Results ===")
    for result in results:
        print(result)

    return {"success": True, "results": results, "debug_log": handler.get_debug_log()}


if __name__ == "__main__":
    frappe.connect()
    test_payment_fixes()
