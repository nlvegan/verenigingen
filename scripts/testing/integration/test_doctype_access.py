#!/usr/bin/env python3
"""
Test script to check doctype accessibility
"""

import json

import frappe


def test_doctype_access():
    """Test if verenigingen doctypes are accessible"""

    frappe.init("dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    print("=== Testing DocType Accessibility ===")

    # Test doctypes
    doctypes_to_test = ["Chapter", "Donor", "Donation Type", "Donation"]

    for doctype_name in doctypes_to_test:
        print(f"\nTesting {doctype_name}:")

        try:
            # Test 1: Can we access the doctype meta?
            meta = frappe.get_meta(doctype_name)
            print(f"  ✓ Meta accessible - app={meta.app}, module={meta.module}")

            # Test 2: Can we create a new document?
            doc = frappe.new_doc(doctype_name)
            print(f"  ✓ Can create new document")

            # Test 3: Can we get list (empty is OK)?
            try:
                records = frappe.get_all(doctype_name, limit=1)
                print(f"  ✓ get_all works - found {len(records)} records")
            except Exception as e:
                print(f"  ✗ get_all failed: {e}")

            # Test 4: Check permissions
            has_perm = frappe.has_permission(doctype_name, "read")
            print(f"  ✓ Read permission: {has_perm}")

        except Exception as e:
            print(f"  ✗ Failed: {e}")

    print("\n=== Test Summary ===")
    print("If all tests show ✓, the doctypes should be accessible in the interface.")

    # Test 5: Check if DocType records exist in database
    print("\n=== Database DocType Records ===")
    for doctype_name in doctypes_to_test:
        record = frappe.db.get_value("DocType", doctype_name, ["app", "module"], as_dict=True)
        if record:
            print(f"{doctype_name}: app={record.app}, module={record.module}")
        else:
            print(f"{doctype_name}: NOT FOUND in DocType table")


if __name__ == "__main__":
    test_doctype_access()
