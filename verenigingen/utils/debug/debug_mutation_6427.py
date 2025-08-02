#!/usr/bin/env python3
"""
Debug script for E-Boekhouden mutation 6427 processing error
"""

import json

import frappe


def debug_mutation_6427():
    """Debug the specific mutation that's failing"""

    print("=== Debugging E-Boekhouden Mutation 6427 ===")

    # The failing mutation data
    mutation_data = {
        "id": 6427,
        "type": 3,
        "date": "2025-01-26",
        "description": "TRTP SEPA OVERBOEKING IBAN NL10ASNB0267553269 BIC ASNBNL21A. Pena Reyes Bestelling 50158 tr_qrmwJyxmXL",
        "termOfPayment": 0,
        "ledgerId": 43981046,
        "relationId": 60657073,
        "inExVat": "IN",
        "invoiceNumber": "50158",
        "entryNumber": "",
        "rows": [
            {
                "ledgerId": 13201873,
                "vatCode": "GEEN",
                "amount": 20.0,
                "description": "TRTP SEPA OVERBOEKING IBAN NL10ASNB0267553269 BIC ASNBNL21A. Pena Reyes Bestelling 50158 tr_qrmwJyxmXL",
            }
        ],
        "vat": [],
        "amount": 20.0,
    }

    print("Mutation details:")
    print(json.dumps(mutation_data, indent=2))

    print("\n=== Step 1: Check Party Resolution ===")

    # Test party resolution
    try:
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        resolver = EBoekhoudenPartyResolver()
        debug_info = []

        print(f"Resolving relationId: {mutation_data['relationId']}")
        customer_name = resolver.resolve_customer(mutation_data["relationId"], debug_info)

        print("Party resolution debug info:")
        for info in debug_info:
            print(f"  - {info}")

        print(f"Result: Customer name = {customer_name}")

        if not customer_name:
            print("❌ Party resolution failed - this is likely the root cause")
            return False
        else:
            print("✓ Party resolution successful")

    except Exception as e:
        print(f"❌ Party resolution error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    print("\n=== Step 2: Check Bank Account Resolution ===")

    # Test bank account resolution
    try:
        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        # Get a company for testing
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not company:
            company = frappe.db.get_value("Company", {}, "name")

        print(f"Using company: {company}")

        handler = PaymentEntryHandler(company)
        bank_account = handler._determine_bank_account(
            mutation_data["ledgerId"], "Receive", mutation_data["description"]  # Type 3 = Receive
        )

        print(f"Bank account resolved: {bank_account}")

        if not bank_account:
            print("❌ Bank account resolution failed")
            return False
        else:
            print("✓ Bank account resolution successful")

    except Exception as e:
        print(f"❌ Bank account resolution error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    print("\n=== Step 3: Test Full Payment Processing ===")

    # Test the full payment processing
    try:
        from verenigingen.e_boekhouden.utils.eboekhouden_payment_import import create_payment_entry

        debug_info = []
        cost_center = frappe.db.get_value("Company", company, "cost_center")

        print(f"Processing payment with company: {company}, cost_center: {cost_center}")

        payment_name = create_payment_entry(mutation_data, company, cost_center, debug_info)

        print("Payment processing debug info:")
        for info in debug_info:
            print(f"  - {info}")

        if payment_name:
            print(f"✅ Payment processing successful: {payment_name}")
            return True
        else:
            print("❌ Payment processing failed")
            return False

    except Exception as e:
        print(f"❌ Payment processing error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def check_existing_data():
    """Check if related data already exists"""
    print("\n=== Checking Existing Data ===")

    # Check if customer exists
    customer = frappe.db.get_value(
        "Customer", {"eboekhouden_relation_code": "60657073"}, ["name", "customer_name"], as_dict=True
    )

    if customer:
        print(f"✓ Customer exists: {customer['customer_name']} ({customer['name']})")
    else:
        print("❌ Customer does not exist for relationId 60657073")

    # Check for invoice 50158
    invoice = frappe.db.get_value(
        "Sales Invoice", {"name": "50158"}, ["name", "customer", "status", "outstanding_amount"], as_dict=True
    )

    if invoice:
        print(
            f"✓ Invoice exists: {invoice['name']} for customer {invoice['customer']}, status: {invoice['status']}, outstanding: {invoice['outstanding_amount']}"
        )
    else:
        print("❌ Invoice 50158 does not exist")

    # Check ledger mappings
    main_ledger = frappe.db.get_value(
        "E-Boekhouden Ledger Mapping",
        {"ledger_id": "43981046"},
        ["erpnext_account", "account_name"],
        as_dict=True,
    )

    if main_ledger:
        print(
            f"✓ Main ledger mapping exists: {main_ledger['ledger_id']} -> {main_ledger['erpnext_account']} ({main_ledger['account_name']})"
        )
    else:
        print("❌ Main ledger mapping missing for ledgerId 43981046")

    row_ledger = frappe.db.get_value(
        "E-Boekhouden Ledger Mapping",
        {"ledger_id": "13201873"},
        ["erpnext_account", "account_name"],
        as_dict=True,
    )

    if row_ledger:
        print(
            f"✓ Row ledger mapping exists: {row_ledger['ledger_id']} -> {row_ledger['erpnext_account']} ({row_ledger['account_name']})"
        )
    else:
        print("❌ Row ledger mapping missing for ledgerId 13201873")


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        check_existing_data()
        result = debug_mutation_6427()

        if result:
            print("\n✅ Mutation 6427 processing should work correctly")
        else:
            print("\n❌ Issues found that need to be addressed")

    except Exception as e:
        print(f"Script error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
