#!/usr/bin/env python3
"""
Test what mapping issues we'll encounter
"""

import frappe


@frappe.whitelist()
def test_mapping_issues():
    """Test mapping issues without actually importing"""

    print("Testing for potential mapping issues...\n")

    company = frappe.db.get_value("E-Boekhouden Settings", None, "default_company")

    # Test 1: Check bank account mappings
    print("1. BANK ACCOUNT MAPPINGS")
    bank_mappings = frappe.db.sql(
        """
        SELECT lm.ledger_id, lm.ledger_name, lm.erpnext_account
        FROM `tabE-Boekhouden Ledger Mapping` lm
        JOIN `tabAccount` a ON a.name = lm.erpnext_account
        WHERE a.account_type IN ('Bank', 'Cash')
        AND a.company = %s
    """,
        company,
        as_dict=True,
    )

    print(f"   Found {len(bank_mappings)} bank/cash account mappings")
    for m in bank_mappings[:5]:
        print(f"   - Ledger {m.ledger_id}: {m.ledger_name} -> {m.erpnext_account}")

    # Test 2: Check receivable account mappings
    print("\n2. RECEIVABLE ACCOUNT MAPPINGS")
    receivable_mappings = frappe.db.sql(
        """
        SELECT lm.ledger_id, lm.ledger_name, lm.erpnext_account
        FROM `tabE-Boekhouden Ledger Mapping` lm
        JOIN `tabAccount` a ON a.name = lm.erpnext_account
        WHERE a.account_type = 'Receivable'
        AND a.company = %s
    """,
        company,
        as_dict=True,
    )

    print(f"   Found {len(receivable_mappings)} receivable account mappings")
    for m in receivable_mappings[:5]:
        print(f"   - Ledger {m.ledger_id}: {m.ledger_name} -> {m.erpnext_account}")

    # Test 3: Check payable account mappings
    print("\n3. PAYABLE ACCOUNT MAPPINGS")
    payable_mappings = frappe.db.sql(
        """
        SELECT lm.ledger_id, lm.ledger_name, lm.erpnext_account
        FROM `tabE-Boekhouden Ledger Mapping` lm
        JOIN `tabAccount` a ON a.name = lm.erpnext_account
        WHERE a.account_type = 'Payable'
        AND a.company = %s
    """,
        company,
        as_dict=True,
    )

    print(f"   Found {len(payable_mappings)} payable account mappings")
    for m in payable_mappings[:5]:
        print(f"   - Ledger {m.ledger_id}: {m.ledger_name} -> {m.erpnext_account}")

    # Test 4: Check existing customers/suppliers
    print("\n4. EXISTING PARTIES")
    customer_count = frappe.db.count("Customer")
    supplier_count = frappe.db.count("Supplier")

    print(f"   Customers: {customer_count}")
    print(f"   Suppliers: {supplier_count}")

    # Test 5: Check items
    print("\n5. ITEMS")
    item_count = frappe.db.count("Item")
    print(f"   Items: {item_count}")

    # Test 6: Look for unmapped ledgers
    print("\n6. CHECK FOR POTENTIAL UNMAPPED LEDGERS")

    # Get all mapped ledger IDs
    mapped_ledgers = frappe.db.sql(
        """
        SELECT ledger_id FROM `tabE-Boekhouden Ledger Mapping`
    """,
        pluck="ledger_id",
    )

    print(f"   Total mapped ledgers: {len(mapped_ledgers)}")

    # Test 7: Check if we have the required fallback items
    print("\n7. REQUIRED ITEMS")
    required_items = ["E-Boekhouden Import Item"]
    for item_name in required_items:
        exists = frappe.db.exists("Item", {"item_name": item_name})
        print(f"   {item_name}: {'✓ Exists' if exists else '✗ Missing'}")

    # Summary
    print("\n=== POTENTIAL ISSUES ===")
    issues = []

    if len(bank_mappings) == 0:
        issues.append("No bank account mappings found")
    if len(receivable_mappings) == 0:
        issues.append("No receivable account mappings found")
    if len(payable_mappings) == 0:
        issues.append("No payable account mappings found")
    if customer_count == 0:
        issues.append("No customers exist - all sales will fail")
    if supplier_count == 0:
        issues.append("No suppliers exist - all purchases will fail")
    if item_count == 0:
        issues.append("No items exist - invoice lines will fail")

    if issues:
        print("The following issues will cause import failures:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("Basic mappings appear to be in place")

    # Recommendations
    print("\n=== RECOMMENDATIONS ===")
    print("Since fallbacks have been removed, ensure:")
    print("1. All ledger accounts used in eBoekhouden have mappings")
    print("2. Create customers/suppliers before import or handle creation")
    print("3. Create required items or handle item creation")
    print("4. Map all bank/cash accounts properly")

    return {
        "bank_mappings": len(bank_mappings),
        "receivable_mappings": len(receivable_mappings),
        "payable_mappings": len(payable_mappings),
        "customers": customer_count,
        "suppliers": supplier_count,
        "items": item_count,
        "issues": issues,
    }


if __name__ == "__main__":
    print("Test mapping issues")
