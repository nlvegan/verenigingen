#!/usr/bin/env python3
"""
Create proper mapping for Verrekeningen account using correct field names
"""

import frappe


@frappe.whitelist()
def create_verrekeningen_mapping():
    """Create explicit mapping for Verrekeningen account with correct field names"""

    try:
        # Check if mapping already exists
        existing_mapping = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_code": "9999"}, "name")

        if existing_mapping:
            print(f"Mapping for 9999 already exists: {existing_mapping}")

            # Update existing mapping to ensure it's correct
            mapping = frappe.get_doc("E-Boekhouden Ledger Mapping", existing_mapping)
            mapping.ledger_name = "Verrekeningen"
            mapping.erpnext_account = "9999 - Verrekeningen - NVV"
            mapping.save(ignore_permissions=True)

            print(f"✅ Updated existing mapping: {mapping.name}")
            return {"success": True, "mapping": mapping.name, "action": "updated"}

        # Create new mapping
        mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
        mapping.ledger_id = "9999"
        mapping.ledger_code = "9999"
        mapping.ledger_name = "Verrekeningen"
        mapping.erpnext_account = "9999 - Verrekeningen - NVV"
        mapping.save(ignore_permissions=True)

        print(f"✅ Created mapping for Verrekeningen: {mapping.name}")
        return {"success": True, "mapping": mapping.name, "action": "created"}

    except Exception as e:
        print(f"❌ Error with mapping: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def verify_verrekeningen_setup():
    """Verify that Verrekeningen account is properly set up"""

    # Check account exists and is properly configured
    account = frappe.db.get_value(
        "Account",
        {"account_name": "Verrekeningen", "company": "Ned Ver Vegan"},
        ["name", "account_type", "root_type", "parent_account"],
        as_dict=True,
    )

    if not account:
        return {"success": False, "error": "Verrekeningen account not found"}

    # Check configuration
    issues = []

    if account.account_type != "Equity":
        issues.append("Account type is {account.account_type}, should be Equity")

    if account.root_type != "Equity":
        issues.append("Root type is {account.root_type}, should be Equity")

    if "Eigen Vermogen" not in account.parent_account:
        issues.append("Parent account is {account.parent_account}, should be under Eigen Vermogen")

    # Check mapping exists
    mapping = frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_code": "9999"}, "name")

    if not mapping:
        issues.append("No ledger mapping found for 9999")

    if issues:
        return {"success": False, "issues": issues, "account": account}
    else:
        return {
            "success": True,
            "account": account,
            "mapping": mapping,
            "message": "Verrekeningen account is properly configured",
        }


if __name__ == "__main__":
    print("Create Verrekeningen mapping with correct fields")
