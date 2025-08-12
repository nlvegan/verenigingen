#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def check_eboekhouden_fields():
    """Check if E-Boekhouden custom fields exist"""
    print("Testing E-Boekhouden custom fields...")

    # Check if fields exist
    fields_to_check = [
        ("Journal Entry", "eboekhouden_mutation_nr"),
        ("Journal Entry", "eboekhouden_relation_code"),
        ("Journal Entry", "eboekhouden_invoice_number"),
        ("Journal Entry", "eboekhouden_main_ledger_id"),
        ("Journal Entry", "eboekhouden_mutation_type"),
        ("Sales Invoice", "eboekhouden_mutation_nr"),
        ("Sales Invoice", "eboekhouden_invoice_number"),
        ("Purchase Invoice", "eboekhouden_mutation_nr"),
        ("Purchase Invoice", "eboekhouden_invoice_number"),
        ("Payment Entry", "eboekhouden_mutation_nr"),
        ("Payment Entry", "eboekhouden_mutation_type"),
        ("Customer", "eboekhouden_relation_code"),
        ("Supplier", "eboekhouden_relation_code"),
        ("Account", "eboekhouden_grootboek_nummer"),
    ]

    results = []
    for doctype, fieldname in fields_to_check:
        exists = frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname})
        results.append((doctype, fieldname, "EXISTS" if exists else "MISSING"))
        status = "✅ EXISTS" if exists else "❌ MISSING"
        print(f"{doctype}.{fieldname}: {status}")

    missing_count = len([r for r in results if r[2] == "MISSING"])
    total_count = len(results)
    existing_count = total_count - missing_count

    print(f"\n📊 Summary: {existing_count}/{total_count} fields exist, {missing_count} missing")

    if missing_count == 0:
        print("✅ All E-Boekhouden custom fields are properly created!")
        return {"success": True, "message": "All E-Boekhouden custom fields exist", "results": results}
    else:
        print("⚠️ Some E-Boekhouden custom fields are missing")
        missing_fields = [(dt, fn) for dt, fn, status in results if status == "MISSING"]
        return {
            "success": False,
            "message": f"{missing_count} E-Boekhouden fields missing",
            "missing_fields": missing_fields,
            "results": results,
        }
