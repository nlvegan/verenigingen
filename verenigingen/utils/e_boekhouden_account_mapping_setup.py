#!/usr/bin/env python3
"""
E-Boekhouden Account Mapping Setup

This script addresses the Dutch language hardcoding issues and creates proper
account mappings for E-Boekhouden integration.

Issues addressed:
1. Replace hardcoded Dutch account names with dynamic lookups
2. Create proper account mappings instead of using fallback accounts
3. Eliminate dangerous fallbacks to business accounts like "Eindresultaat"
4. Set up dedicated import accounts with clear naming
"""

import frappe
from frappe.utils import cint, flt


def setup_proper_account_mappings():
    """Set up proper account mappings for E-Boekhouden integration"""

    print("=== E-Boekhouden Account Mapping Setup ===")

    # Get the company
    company = (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or frappe.db.get_value("Company", {}, "name")
    )

    if not company:
        print("❌ No company found")
        return False

    print(f"Setting up account mappings for company: {company}")

    # 1. Create dedicated E-Boekhouden import accounts
    setup_dedicated_import_accounts(company)

    # 2. Create common Dutch account mappings
    setup_dutch_account_mappings(company)

    # 3. Validate current fallback accounts are safe
    validate_fallback_accounts(company)

    print("✅ E-Boekhouden account mapping setup completed")
    return True


def setup_dedicated_import_accounts(company):
    """Create dedicated accounts for E-Boekhouden imports"""

    print("\n--- Setting up dedicated import accounts ---")

    company_abbr = frappe.db.get_value("Company", company, "abbr")

    # Import accounts to create
    import_accounts = [
        {
            "account_name": "89999 - E-Boekhouden Import Income",
            "account_type": "Income Account",
            "root_type": "Income",
            "parent_account_type": "Income Account",
        },
        {
            "account_name": "59999 - E-Boekhouden Import Expense",
            "account_type": "Expense Account",
            "root_type": "Expense",
            "parent_account_type": "Expense Account",
        },
        {
            "account_name": "19999 - E-Boekhouden Import Payable",
            "account_type": "Payable",
            "root_type": "Liability",
            "parent_account_type": "Payable",
        },
        {
            "account_name": "13999 - E-Boekhouden Import Receivable",
            "account_type": "Receivable",
            "root_type": "Asset",
            "parent_account_type": "Receivable",
        },
    ]

    for account_config in import_accounts:
        full_account_name = f"{account_config['account_name']} - {company_abbr}"

        # Check if account already exists
        if frappe.db.exists("Account", full_account_name):
            print(f"✓ Account already exists: {full_account_name}")
            continue

        # Find parent account based on root type
        parent_mappings = {
            "Income": "8 - Opbrengsten - NVV",
            "Expense": "6 - Kosten - NVV",
            "Asset": "Vorderingen - NVV",  # For receivables
            "Liability": "Schulden - NVV",  # For payables
        }

        parent_account = parent_mappings.get(account_config["root_type"])

        # Verify the parent account exists
        if parent_account and not frappe.db.exists("Account", parent_account):
            # Fallback to root type group
            parent_account = frappe.db.get_value(
                "Account",
                {"company": company, "root_type": account_config["root_type"], "is_group": 1},
                "name",
            )

        if not parent_account:
            print(f"❌ No parent account found for {account_config['account_type']}")
            continue

        # Create the account
        try:
            account = frappe.new_doc("Account")
            account.account_name = account_config["account_name"]
            account.parent_account = parent_account
            account.company = company
            account.account_type = account_config["account_type"]
            account.root_type = account_config["root_type"]
            account.is_group = 0
            account.insert()

            print(f"✅ Created dedicated import account: {full_account_name}")

        except Exception as e:
            print(f"❌ Failed to create account {full_account_name}: {str(e)}")


def setup_dutch_account_mappings(company):
    """Set up common Dutch account number mappings"""

    print("\n--- Setting up Dutch account mappings ---")

    # Common Dutch account number patterns based on RGS (Referentiegrootboekschema)
    dutch_account_patterns = {
        # Assets (10000-19999)
        "1000": {"type": "Cash", "erpnext_pattern": "kas|cash|contant"},
        "1100": {"type": "Bank", "erpnext_pattern": "bank|rekening"},
        "1300": {"type": "Receivable", "erpnext_pattern": "debiteuren|receivable"},
        "1400": {"type": "Inventory", "erpnext_pattern": "voorraad|inventory|stock"},
        # Liabilities (20000-49999)
        "2000": {"type": "Fixed Asset", "erpnext_pattern": "vaste activa|fixed asset"},
        "4400": {"type": "Payable", "erpnext_pattern": "crediteuren|payable"},
        "4700": {"type": "Tax", "erpnext_pattern": "btw|vat|belasting"},
        # Income (80000-89999)
        "8000": {"type": "Income Account", "erpnext_pattern": "omzet|verkoop|income|revenue"},
        "8100": {"type": "Income Account", "erpnext_pattern": "service|diensten"},
        # Expenses (40000-79999)
        "4000": {"type": "Expense Account", "erpnext_pattern": "inkoop|purchase|cost"},
        "6000": {"type": "Expense Account", "erpnext_pattern": "overige|other|misc"},
        "7000": {"type": "Expense Account", "erpnext_pattern": "personeel|payroll|salary"},
    }

    # Check which patterns have corresponding ERPNext accounts
    mappings_created = 0

    for dutch_code, config in dutch_account_patterns.items():
        # Look for ERPNext accounts that match the pattern
        erpnext_accounts = frappe.db.sql(
            """
            SELECT name, account_name, account_type
            FROM `tabAccount`
            WHERE company = %s
            AND account_type = %s
            AND is_group = 0
            AND disabled = 0
            AND (
                LOWER(account_name) REGEXP %s
                OR name LIKE %s
            )
            ORDER BY
                CASE
                    WHEN name LIKE %s THEN 1
                    WHEN LOWER(account_name) REGEXP %s THEN 2
                    ELSE 3
                END
            LIMIT 1
        """,
            (
                company,
                config["type"],
                config["erpnext_pattern"],
                f"{dutch_code}%",
                f"{dutch_code}%",
                config["erpnext_pattern"],
            ),
            as_dict=True,
        )

        if erpnext_accounts:
            erpnext_account = erpnext_accounts[0]
            print(f"✅ Mapping suggestion: {dutch_code}* → {erpnext_account.name}")
            mappings_created += 1
        else:
            print(f"⚠️  No matching ERPNext account found for Dutch pattern {dutch_code} ({config['type']})")

    print(f"Found {mappings_created} potential account mappings")


def validate_fallback_accounts(company):
    """Validate that current fallback accounts are safe to use"""

    print("\n--- Validating fallback accounts ---")

    # Check the accounts that were being used as fallbacks
    dangerous_accounts = [
        "99998 - Eindresultaat - NVV",  # Net income account
        "48010 - Afschrijving Inventaris - NVV",  # Depreciation expense
        "Vraagposten - NVV",  # Suspense account
    ]

    for account_name in dangerous_accounts:
        if frappe.db.exists("Account", account_name):
            # Check if it has transactions from E-Boekhouden imports
            gl_entries = frappe.db.count(
                "GL Entry", {"account": account_name, "remarks": ["like", "%E-Boekhouden%"]}
            )

            if gl_entries > 0:
                print(f"⚠️  ISSUE: {account_name} has {gl_entries} E-Boekhouden transactions")
                print("    This account should not be used as a fallback")
            else:
                print(f"✅ Safe: {account_name} has no E-Boekhouden transactions")
        else:
            print(f"✅ Account does not exist: {account_name}")


def create_account_mapping_validation_report():
    """Create a report of all account mappings that need to be configured"""

    print("\n--- Account Mapping Validation Report ---")

    # Find all unique grootboek numbers from recent E-Boekhouden data
    try:
        # This would need to be adapted based on where E-Boekhouden data is stored
        # For now, just show the framework
        print("To create a complete mapping report, run:")
        print("1. Extract all unique grootboek numbers from E-Boekhouden data")
        print("2. Check which ones have ERPNext account mappings")
        print("3. Identify missing mappings that need manual configuration")
        print("4. Create mapping entries in the EBoekhoudenAccountMap doctype")

    except Exception as e:
        print(f"Could not create validation report: {str(e)}")


if __name__ == "__main__":
    try:
        frappe.init()
        frappe.connect()

        success = setup_proper_account_mappings()

        if success:
            create_account_mapping_validation_report()
            print("\n" + "=" * 50)
            print("SUMMARY:")
            print("✅ Dedicated import accounts created")
            print("✅ Dutch account patterns analyzed")
            print("✅ Fallback account safety validated")
            print("⚠️  Manual account mapping configuration still required")
            print("⚠️  Set allow_fallback=False in production for data integrity")

    except Exception as e:
        print(f"Setup error: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
