#!/usr/bin/env python3
"""
Manual test script for enhanced payment processing.
Run from bench directory.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import frappe

frappe.init(site="dev.veganisme.net")
frappe.connect()

try:
    from verenigingen.utils.eboekhouden.test_enhanced_payment import test_enhanced_payment_with_mutation_5473

    print("Testing enhanced payment handler...")
    result = test_enhanced_payment_with_mutation_5473()

    print("\nResult:")
    print(f"Success: {result.get('success')}")
    if result.get("success"):
        print(f"Payment Entry: {result.get('payment_entry')}")
        print(f"Bank Account: {result.get('bank_account')}")
        print(f"Amount: {result.get('amount')}")
        print(f"\nImprovements:")
        for improvement in result.get("improvements", []):
            print(f"  {improvement}")
    else:
        print(f"Error: {result.get('error')}")

    print("\nDebug Log:")
    for log in result.get("debug_log", [])[-10:]:  # Last 10 entries
        print(f"  {log}")

finally:
    frappe.destroy()
