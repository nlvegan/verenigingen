#!/usr/bin/env python3
"""
Test comprehensive duplicate detection across all E-Boekhouden document types
"""

import frappe


def test_duplicate_detection_comprehensive():
    """Test duplicate detection across all document types"""

    print("=== Testing Comprehensive Duplicate Detection ===")

    # Get some existing mutation numbers from the database
    existing_mutations = {}

    # Check for existing Payment Entries
    pe_mutations = frappe.db.sql(
        """
        SELECT eboekhouden_mutation_nr, name, payment_type, party
        FROM `tabPayment Entry`
        WHERE eboekhouden_mutation_nr != ''
        LIMIT 3
    """,
        as_dict=True,
    )

    if pe_mutations:
        existing_mutations["Payment Entry"] = pe_mutations
        print(f"Found {len(pe_mutations)} existing Payment Entries")
        for pe in pe_mutations:
            print(f"  - {pe.name}: mutation {pe.eboekhouden_mutation_nr} ({pe.payment_type} to {pe.party})")

    # Check for existing Journal Entries
    je_mutations = frappe.db.sql(
        """
        SELECT eboekhouden_mutation_nr, name, voucher_type, title
        FROM `tabJournal Entry`
        WHERE eboekhouden_mutation_nr != ''
        LIMIT 3
    """,
        as_dict=True,
    )

    if je_mutations:
        existing_mutations["Journal Entry"] = je_mutations
        print(f"Found {len(je_mutations)} existing Journal Entries")
        for je in je_mutations:
            print(f"  - {je.name}: mutation {je.eboekhouden_mutation_nr} ({je.voucher_type}: {je.title})")

    # Check for existing Sales Invoices
    si_mutations = frappe.db.sql(
        """
        SELECT eboekhouden_mutation_nr, name, customer, grand_total
        FROM `tabSales Invoice`
        WHERE eboekhouden_mutation_nr != ''
        LIMIT 3
    """,
        as_dict=True,
    )

    if si_mutations:
        existing_mutations["Sales Invoice"] = si_mutations
        print(f"Found {len(si_mutations)} existing Sales Invoices")
        for si in si_mutations:
            print(f"  - {si.name}: mutation {si.eboekhouden_mutation_nr} ({si.customer}: {si.grand_total})")

    # Check for existing Purchase Invoices
    pi_mutations = frappe.db.sql(
        """
        SELECT eboekhouden_mutation_nr, name, supplier, grand_total
        FROM `tabPurchase Invoice`
        WHERE eboekhouden_mutation_nr != ''
        LIMIT 3
    """,
        as_dict=True,
    )

    if pi_mutations:
        existing_mutations["Purchase Invoice"] = pi_mutations
        print(f"Found {len(pi_mutations)} existing Purchase Invoices")
        for pi in pi_mutations:
            print(f"  - {pi.name}: mutation {pi.eboekhouden_mutation_nr} ({pi.supplier}: {pi.grand_total})")

    print(f"\n=== Summary ===")
    print(f"Total document types with E-Boekhouden mutations: {len(existing_mutations)}")

    total_mutations = sum(len(docs) for docs in existing_mutations.values())
    print(f"Total existing mutations found: {total_mutations}")

    # Test the duplicate detection function
    print(f"\n=== Testing Duplicate Detection Function ===")

    from verenigingen.e_boekhouden.utils.eboekhouden_rest_full_migration import _check_if_already_imported

    if pe_mutations:
        test_mutation_id = pe_mutations[0]["eboekhouden_mutation_nr"]
        result = _check_if_already_imported(test_mutation_id, "Payment Entry")
        if result:
            print(f"✓ Duplicate detection works: mutation {test_mutation_id} found as {result}")
        else:
            print(f"❌ Duplicate detection failed for mutation {test_mutation_id}")

    # Test that non-existent mutations return None
    fake_mutation_id = "999999999"
    result = _check_if_already_imported(fake_mutation_id, "Payment Entry")
    if not result:
        print(f"✓ Non-existent mutation detection works: {fake_mutation_id} correctly returns None")
    else:
        print(f"❌ Non-existent mutation detection failed: {fake_mutation_id} unexpectedly found as {result}")

    print(f"\n=== Testing Enhanced Payment Handler Duplicate Detection ===")

    if pe_mutations:
        # Test the enhanced payment handler directly
        from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import (
            PaymentEntryHandler,
        )

        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not company:
            company = frappe.db.get_value("Company", {}, "name")

        handler = PaymentEntryHandler(company)

        # Create a fake mutation with an existing mutation ID
        test_mutation = {
            "id": int(pe_mutations[0]["eboekhouden_mutation_nr"]),
            "type": 3,  # Receive payment
            "date": "2025-01-26",
            "description": "Test duplicate detection",
            "amount": 20.0,
            "relationId": "12345",  # Fake relation
            "ledgerId": "67890",  # Fake ledger
            "rows": [{"amount": 20.0, "ledgerId": "67890"}],
        }

        result = handler.process_payment_mutation(test_mutation)
        debug_log = handler.get_debug_log()

        print(f"Enhanced handler result: {result}")
        print("Debug log:")
        for log_entry in debug_log[-5:]:  # Show last 5 entries
            print(f"  - {log_entry}")

        if result == pe_mutations[0]["name"]:
            print(f"✅ Enhanced payment handler correctly returned existing payment: {result}")
        else:
            print(f"❌ Enhanced payment handler failed. Expected: {pe_mutations[0]['name']}, Got: {result}")

    return True


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()
        test_duplicate_detection_comprehensive()
    except Exception as e:
        print(f"Test error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
