#!/usr/bin/env python3
"""
Debug script to understand why mutation 6029 is failing.
This mutation has rows with amounts 339.0 and 0.91 but seems to be calculating as 0.
"""

import json
from datetime import datetime

import frappe
from frappe.utils import flt


def debug_payment_mutation():
    """Debug mutation 6029 payment processing"""

    # Recreate the exact mutation structure from the error logs
    mutation_6029 = {
        "id": 6029,
        "type": 4,  # Type 4 = Supplier Payment
        "date": "2024-09-27",
        "description": "NL68INGB0008927840 INGBNL2A Anne Koreman 2024092 7225649TRIONL2UXXXE000058108 Declaraties 20240923",
        "termOfPayment": 0,
        "ledgerId": 13201869,
        "relationId": 57542052,
        "inExVat": "EX",
        "invoiceNumber": "20240923,20240923-2",
        "entryNumber": "",
        "rows": [
            {
                "ledgerId": 13201883,
                "vatCode": "GEEN",
                "amount": 339.0,
                "description": "NL68INGB0008927840 INGBNL2A Anne Koreman 2024092 7225649TRIONL2UXXXE000058108 Declaraties 20240923",
            },
            {
                "ledgerId": 13201883,
                "vatCode": "GEEN",
                "amount": 0.91,
                "description": "NL68INGB0008927840 INGBNL2A Anne Koreman 2024092 7225649TRIONL2UXXXE000058108 Declaraties 20240923",
            },
        ],
        "vat": [],
        # Note: No direct 'amount' field at mutation level
    }

    print("=" * 80)
    print("DEBUG: Payment Mutation 6029 Analysis")
    print("=" * 80)
    print(f"\nMutation ID: {mutation_6029['id']}")
    print(f"Type: {mutation_6029['type']} (Supplier Payment)")
    print(f"Date: {mutation_6029['date']}")
    print(f"Invoice Numbers: {mutation_6029['invoiceNumber']}")
    print(f"Relation ID: {mutation_6029['relationId']}")

    # Check if direct amount field exists
    direct_amount = mutation_6029.get("amount")
    print(f"\nDirect 'amount' field: {direct_amount} (type: {type(direct_amount)})")

    # Analyze rows
    print(f"\nRows Analysis:")
    print(f"Number of rows: {len(mutation_6029.get('rows', []))}")

    total_from_rows = 0
    for i, row in enumerate(mutation_6029.get("rows", [])):
        row_amount = row.get("amount", 0)
        print(f"  Row {i+1}: amount = {row_amount} (type: {type(row_amount)})")
        total_from_rows += abs(flt(row_amount, 2))

    print(f"\nTotal from rows: {total_from_rows}")

    # Simulate PaymentEntryHandler logic
    print("\n" + "-" * 40)
    print("Simulating PaymentEntryHandler logic:")
    print("-" * 40)

    # Step 1: Initial amount from mutation
    amount = abs(flt(mutation_6029.get("amount", 0), 2))
    print(f"\nStep 1 - Initial amount from mutation.get('amount'): {amount}")

    # Step 2: If no direct amount, calculate from rows
    if amount == 0 and mutation_6029.get("rows"):
        print("\nStep 2 - No direct amount, calculating from rows:")
        row_amounts = []
        for row in mutation_6029.get("rows", []):
            row_amt = abs(flt(row.get("amount", 0), 2))
            row_amounts.append(row_amt)
            print(f"  Row amount: {row.get('amount', 0)} -> abs(flt()) = {row_amt}")

        amount = sum(row_amounts)
        print(f"  Sum of row amounts: {amount}")

    print(f"\nFinal calculated amount: {amount}")

    # Test actual PaymentEntryHandler
    print("\n" + "=" * 80)
    print("Testing with actual PaymentEntryHandler:")
    print("=" * 80)

    try:
        from vereinigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        # Initialize handler
        handler = PaymentEntryHandler("Ned Ver Vegan", "Main - NVV")

        # Process the mutation
        print("\nProcessing mutation through handler...")

        # Add debug to see what's happening
        result = handler.process_payment_mutation(mutation_6029)

        if result:
            print(f"\nSUCCESS: Payment Entry created: {result}")
        else:
            print("\nFAILED: Payment Entry creation failed")

        # Print debug log
        print("\nHandler Debug Log:")
        for log_entry in handler.get_debug_log():
            print(f"  {log_entry}")

    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {str(e)}")
        import traceback

        print("\nTraceback:")
        print(traceback.format_exc())

    # Additional debugging - check for field types
    print("\n" + "=" * 80)
    print("Field Type Analysis:")
    print("=" * 80)

    print(f"\nChecking mutation structure:")
    print(f"  mutation is dict: {isinstance(mutation_6029, dict)}")
    print(f"  'rows' exists: {'rows' in mutation_6029}")
    print(f"  'rows' is list: {isinstance(mutation_6029.get('rows'), list)}")

    if mutation_6029.get("rows"):
        for i, row in enumerate(mutation_6029["rows"]):
            print(f"\n  Row {i+1}:")
            print(f"    row is dict: {isinstance(row, dict)}")
            print(f"    'amount' exists: {'amount' in row}")
            print(f"    amount value: {row.get('amount')}")
            print(f"    amount type: {type(row.get('amount'))}")

    # Test flt function behavior
    print("\n" + "=" * 80)
    print("Testing flt() function behavior:")
    print("=" * 80)

    test_values = [339.0, 0.91, "339.0", "0.91", None, "", 0, "0"]
    for val in test_values:
        result = flt(val, 2)
        abs_result = abs(flt(val, 2))
        print(f"  flt({repr(val)}, 2) = {result}, abs() = {abs_result}")


if __name__ == "__main__":
    # Initialize Frappe
    import sys

    sys.path.insert(0, "/home/frappe/frappe-bench")

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        debug_payment_mutation()
    finally:
        frappe.destroy()
