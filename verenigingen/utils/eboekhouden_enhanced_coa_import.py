"""
Enhanced Chart of Accounts import with automatic Bank and Bank Account creation
"""

import json
import re

import frappe


@frappe.whitelist()
def enhanced_coa_import_with_bank_accounts(migration_doc_name):
    """
    Enhanced CoA import that creates Bank and Bank Account records for bank accounts
    """
    try:
        # Get the migration document
        migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_doc_name)

        # Import CoA first using existing functionality
        from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
            EBoekhoudenMigration,
        )

        migration = EBoekhoudenMigration(migration_doc.doctype, migration_doc.name)

        # Run standard CoA import
        coa_result = migration.migrate_chart_of_accounts()

        if not coa_result.get("success"):
            return coa_result

        # Now enhance with bank account creation
        bank_creation_result = create_bank_accounts_from_coa(migration_doc)

        # Combine results
        combined_result = {
            "success": True,
            "coa_import": coa_result,
            "bank_accounts_created": bank_creation_result,
            "message": f"CoA imported successfully. {bank_creation_result.get('created', 0)} bank accounts created.",
        }

        return combined_result

    except Exception as e:
        frappe.log_error(f"Enhanced CoA import error: {str(e)}", "E-Boekhouden Enhanced CoA")
        return {"success": False, "error": str(e)}


def create_bank_accounts_from_coa(migration_doc):
    """
    Create Bank and Bank Account records from imported Chart of Accounts
    """
    try:
        company = migration_doc.company or frappe.db.get_single_value(
            "E-Boekhouden Settings", "default_company"
        )

        if not company:
            return {"success": False, "error": "No company specified"}

        # Get all bank-type accounts created during CoA import
        bank_accounts = frappe.get_all(
            "Account",
            filters={"company": company, "account_type": "Bank", "is_group": 0},
            fields=["name", "account_name", "account_number"],
        )

        created_bank_accounts = 0
        errors = []

        for account in bank_accounts:
            try:
                # Extract IBAN and bank info from account name
                bank_info = extract_bank_info_from_account_name(account.account_name)

                if bank_info.get("account_number"):
                    # Check if Bank Account already exists (by account number or IBAN)
                    existing_bank_account = None
                    if bank_info.get("iban"):
                        existing_bank_account = frappe.db.exists("Bank Account", {"iban": bank_info["iban"]})

                    if not existing_bank_account and bank_info.get("account_number"):
                        existing_bank_account = frappe.db.exists(
                            "Bank Account", {"bank_account_no": bank_info["account_number"]}
                        )

                    if not existing_bank_account:
                        # Create or get Bank record
                        bank_name = get_or_create_bank(bank_info)

                        # Create Bank Account record
                        bank_account = create_bank_account_record(
                            account=account, bank_name=bank_name, bank_info=bank_info, company=company
                        )

                        if bank_account:
                            created_bank_accounts += 1
                            frappe.logger().info(
                                f"Created Bank Account: {bank_account} for account: {bank_info['account_number']}"
                            )
                    else:
                        frappe.logger().info(
                            f"Bank Account already exists for account: {bank_info['account_number']}"
                        )

            except Exception as e:
                errors.append(f"Error processing {account.name}: {str(e)}")
                frappe.logger().error(f"Error creating bank account for {account.name}: {str(e)}")

        return {
            "success": True,
            "created": created_bank_accounts,
            "errors": errors,
            "message": f"Created {created_bank_accounts} bank accounts",
        }

    except Exception as e:
        frappe.log_error(f"Bank account creation error: {str(e)}", "E-Boekhouden Bank Creation")
        return {"success": False, "error": str(e)}


def extract_bank_info_from_account_name(account_name):
    """
    Extract bank account number and bank information from E-boekhouden account names

    Common patterns:
    - "Triodos - 19.83.96.716 - Algemeen"
    - "ING - 123456789"
    - "Rabo - 1234.56.789 - Zakelijk"
    - "PayPal - info@veganisme.org"
    """
    bank_info = {
        "account_number": None,
        "iban": None,
        "bank_name": None,
        "account_holder": None,
        "description": None,
    }

    # Normalize the account name
    name = account_name.strip()

    # Try to extract bank account number patterns
    # Pattern 1: xx.xx.xx.xxx format (Triodos style)
    account_pattern_1 = r"\d{2}\.\d{2}\.\d{2}\.\d{3}"
    # Pattern 2: Simple numeric sequence
    account_pattern_2 = r"\b\d{7,10}\b"
    # Pattern 3: xxx.xx.xxx format
    account_pattern_3 = r"\d{3,4}\.\d{2}\.\d{3,4}"

    account_number = None
    for pattern in [account_pattern_1, account_pattern_3, account_pattern_2]:
        match = re.search(pattern, name)
        if match:
            account_number = match.group(0)
            break

    if account_number:
        bank_info["account_number"] = account_number

        # Try to generate IBAN if we can identify the bank
        # For now, skip IBAN generation as it requires proper check digit calculation
        # bank_code = identify_bank_code_from_name(name)
        # if bank_code:
        #     bank_info["iban"] = generate_dutch_iban(account_number, bank_code)

    # Extract bank name and description from parts
    parts = name.split(" - ")
    if len(parts) >= 1:
        bank_info["bank_name"] = identify_bank_name(parts[0].strip())

    if len(parts) >= 3:
        bank_info["description"] = parts[2].strip()
    elif len(parts) == 2 and not account_number:
        # Might be description in second part
        bank_info["description"] = parts[1].strip()

    # Handle special cases like PayPal
    if "paypal" in name.lower():
        bank_info["bank_name"] = "PayPal"
        # Extract email if present
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        email_match = re.search(email_pattern, name)
        if email_match:
            bank_info["account_holder"] = email_match.group(0)
            bank_info["account_number"] = email_match.group(0)

    return bank_info


def identify_bank_name(bank_part):
    """
    Identify full bank name from account name part
    """
    bank_part_lower = bank_part.lower()

    bank_names = {
        "triodos": "Triodos Bank",
        "ing": "ING Bank",
        "rabo": "Rabobank",
        "abn": "ABN AMRO",
        "bunq": "bunq",
        "sns": "SNS Bank",
        "asn": "ASN Bank",
        "paypal": "PayPal",
    }

    for key, full_name in bank_names.items():
        if key in bank_part_lower:
            return full_name

    # Return original if no match found
    return bank_part


def identify_bank_code_from_name(account_name):
    """
    Identify bank code for IBAN generation
    """
    name_lower = account_name.lower()

    bank_codes = {
        "triodos": "TRIO",
        "ing": "INGB",
        "rabo": "RABO",
        "abn": "ABNA",
        "bunq": "BUNQ",
        "sns": "SNSB",
        "asn": "ASNB",
    }

    for key, code in bank_codes.items():
        if key in name_lower:
            return code

    return None


def generate_dutch_iban(account_number, bank_code):
    """
    Generate Dutch IBAN from account number and bank code
    Note: This is a simplified generation - real IBAN calculation involves check digits
    """
    try:
        # Remove dots and spaces from account number
        clean_account = account_number.replace(".", "").replace(" ", "")

        # Pad to 10 digits
        if len(clean_account) < 10:
            clean_account = clean_account.zfill(10)
        elif len(clean_account) > 10:
            clean_account = clean_account[:10]

        # Simple IBAN format (this would need proper check digit calculation in production)
        # For now, use "00" as placeholder check digits
        iban = f"NL00{bank_code}{clean_account}"

        return iban

    except Exception:
        return None


def get_or_create_bank(bank_info):
    """
    Get existing Bank record or create new one
    """
    bank_name = bank_info.get("bank_name")

    if not bank_name:
        bank_name = "Unknown Bank"

    # Check if Bank already exists
    existing_bank = frappe.db.exists("Bank", {"bank_name": bank_name})

    if existing_bank:
        return existing_bank

    # Create new Bank record
    try:
        bank = frappe.new_doc("Bank")
        bank.bank_name = bank_name

        # Set additional fields if available
        if "triodos" in bank_name.lower():
            bank.swift_number = "TRIONL2U"
            bank.website = "https://www.triodos.nl"
        elif "ing" in bank_name.lower():
            bank.swift_number = "INGBNL2A"
            bank.website = "https://www.ing.nl"
        elif "rabo" in bank_name.lower():
            bank.swift_number = "RABONL2U"
            bank.website = "https://www.rabobank.nl"
        elif "abn" in bank_name.lower():
            bank.swift_number = "ABNANL2A"
            bank.website = "https://www.abnamro.nl"

        bank.insert(ignore_permissions=True)
        frappe.logger().info(f"Created Bank: {bank.name}")
        return bank.name

    except Exception as e:
        frappe.logger().error(f"Error creating Bank {bank_name}: {str(e)}")
        return "Unknown Bank"


def create_bank_account_record(account, bank_name, bank_info, company):
    """
    Create Bank Account record linked to the Chart of Accounts
    """
    try:
        bank_account = frappe.new_doc("Bank Account")

        # Basic information
        bank_account.account_name = account.account_name
        bank_account.account = account.name
        bank_account.bank = bank_name
        bank_account.company = company
        # Don't set account_type as it might not be required or have limited options
        bank_account.is_company_account = 1
        bank_account.is_default = 0

        # Account number and IBAN details
        if bank_info.get("account_number"):
            bank_account.bank_account_no = bank_info["account_number"]

        # Skip IBAN for now - requires proper validation
        # if bank_info.get("iban"):
        #     bank_account.iban = bank_info["iban"]

        # Account holder (use company name if not specified)
        if bank_info.get("account_holder"):
            # For non-IBAN accounts like PayPal
            bank_account.party_type = "Company"
            bank_account.party = company

        bank_account.insert(ignore_permissions=True)
        frappe.logger().info(f"Created Bank Account: {bank_account.name}")
        return bank_account.name

    except Exception as e:
        # Log detailed error information
        error_msg = f"Error creating Bank Account for {account.get('name', 'Unknown')}: {str(e)}"
        frappe.logger().error(error_msg)

        # Also log to error log for debugging
        frappe.log_error(error_msg, "Bank Account Creation")

        return None


@frappe.whitelist()
def test_iban_extraction(account_names):
    """
    Test IBAN extraction from account names
    """
    if isinstance(account_names, str):
        account_names = json.loads(account_names)

    results = []
    for name in account_names:
        bank_info = extract_bank_info_from_account_name(name)
        results.append({"input": name, "extracted": bank_info})

    return {"results": results}


@frappe.whitelist()
def find_bank_accounts_in_coa():
    """
    Find potential bank accounts in existing Chart of Accounts
    """
    try:
        # Get settings for company
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        if not company:
            return {"success": False, "error": "No default company set"}

        # Get all accounts that might be bank accounts
        accounts = frappe.get_all(
            "Account",
            filters={"company": company, "is_group": 0, "account_type": ["in", ["Bank", "Cash", ""]]},
            fields=["name", "account_name", "account_number", "account_type"],
        )

        potential_bank_accounts = []

        for account in accounts:
            bank_info = extract_bank_info_from_account_name(account.account_name)

            if bank_info.get("iban") or bank_info.get("bank_name"):
                potential_bank_accounts.append(
                    {
                        "account": account,
                        "bank_info": bank_info,
                        "has_bank_account": bool(frappe.db.exists("Bank Account", {"account": account.name})),
                    }
                )

        return {"success": True, "found": len(potential_bank_accounts), "accounts": potential_bank_accounts}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def create_bank_accounts_for_existing_coa():
    """
    Create Bank Account records for existing Chart of Accounts bank accounts
    """
    try:
        # Get settings for company
        settings = frappe.get_single("E-Boekhouden Settings")
        company = settings.default_company

        if not company:
            return {"success": False, "error": "No default company set"}

        # Find potential bank accounts
        result = find_bank_accounts_in_coa()
        if not result["success"]:
            return result

        accounts_to_process = [
            acc
            for acc in result["accounts"]
            if not acc["has_bank_account"] and acc["bank_info"].get("account_number")
        ]

        created_bank_accounts = 0
        errors = []

        for account_data in accounts_to_process:
            try:
                account = account_data["account"]
                bank_info = account_data["bank_info"]

                # Create or get Bank record
                bank_name = get_or_create_bank(bank_info)

                # Create Bank Account record
                bank_account = create_bank_account_record(
                    account=account, bank_name=bank_name, bank_info=bank_info, company=company
                )

                if bank_account:
                    created_bank_accounts += 1
                    frappe.logger().info(
                        f"Created Bank Account: {bank_account} for account: {account['name']}"
                    )

            except Exception as e:
                errors.append(f"Error processing {account['name']}: {str(e)}")
                frappe.logger().error(f"Error creating bank account for {account['name']}: {str(e)}")

        return {
            "success": True,
            "created": created_bank_accounts,
            "processed": len(accounts_to_process),
            "errors": errors,
            "message": f"Created {created_bank_accounts} bank accounts from {len(accounts_to_process)} eligible CoA accounts",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
