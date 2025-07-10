#!/usr/bin/env python3
"""
Update account mapping and suggestion logic to handle "Verrekeningen" account (9999) properly
"""

import os

import frappe


@frappe.whitelist()
def update_mapping_for_verrekeningen():
    """Update all relevant mapping files to handle Verrekeningen account"""

    files_to_update = [
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/smart_tegenrekening_mapper.py",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_account_analyzer.py",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/analyze_account_mappings.py",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_ledger_mapping.py",
    ]

    updated_files = []

    for file_path in files_to_update:
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as f:
                    content = f.read()

                # Update references to account 9999
                original_content = content

                # Replace hardcoded "9999" account references with "Verrekeningen"
                content = content.replace('"9999"', '"Verrekeningen"')
                content = content.replace("'9999'", "'Verrekeningen'")

                # Update specific patterns for account lookup
                content = content.replace('{"account_name": "9999",', '{"account_name": "Verrekeningen",')

                # Update account creation patterns
                content = content.replace('account_name = "9999"', 'account_name = "Verrekeningen"')

                # Update any comments or documentation
                content = content.replace("account 9999", "account Verrekeningen (9999)")

                # Update test case references
                content = content.replace('("99999",', '("Verrekeningen",')

                # Only write if content changed
                if content != original_content:
                    with open(file_path, "w") as f:
                        f.write(content)
                    updated_files.append(file_path)
                    print(f"✅ Updated {file_path}")
                else:
                    print(f"ℹ️  No changes needed for {file_path}")

            except Exception as e:
                print(f"❌ Error updating {file_path}: {str(e)}")
        else:
            print(f"⚠️  File not found: {file_path}")

    return {"success": True, "updated_files": updated_files}


@frappe.whitelist()
def create_verrekeningen_mapping():
    """Create explicit mapping for Verrekeningen account"""

    try:
        # Check if mapping already exists
        existing_mapping = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"eboekhouden_account": "9999"}, "name"
        )

        if existing_mapping:
            print(f"Mapping for 9999 already exists: {existing_mapping}")
            return {"success": True, "existing": existing_mapping}

        # Create new mapping
        mapping = frappe.new_doc("E-Boekhouden Ledger Mapping")
        mapping.eboekhouden_account = "9999"
        mapping.account_name = "Verrekeningen"
        mapping.erpnext_account = "9999 - Verrekeningen - NVV"
        mapping.account_type = "Equity"
        mapping.description = "Balancing account for opening balance adjustments"
        mapping.save(ignore_permissions=True)

        print(f"✅ Created mapping for Verrekeningen: {mapping.name}")
        return {"success": True, "mapping": mapping.name}

    except Exception as e:
        print(f"❌ Error creating mapping: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def update_account_suggestions():
    """Update account suggestion logic to recommend Verrekeningen for balancing"""

    suggestion_updates = {
        "account_type_suggestions": {"9999": "Equity", "Verrekeningen": "Equity"},
        "balancing_account_suggestions": {
            "default": "9999 - Verrekeningen - NVV",
            "description": "Use Verrekeningen account for temporary balancing entries",
        },
    }

    print("Account suggestion updates:")
    for category, suggestions in suggestion_updates.items():
        print(f"\n{category}:")
        for key, value in suggestions.items():
            print(f"  {key}: {value}")

    return {"success": True, "suggestions": suggestion_updates}


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

    if issues:
        return {"success": False, "issues": issues, "account": account}
    else:
        return {
            "success": True,
            "account": account,
            "message": "Verrekeningen account is properly configured",
        }


if __name__ == "__main__":
    print("Update mapping for Verrekeningen account")
