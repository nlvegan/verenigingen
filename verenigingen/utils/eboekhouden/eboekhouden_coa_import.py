"""
Chart of Accounts import with automatic Bank and Bank Account creation
"""

import json
import re

import frappe


@frappe.whitelist()
def coa_import_with_bank_accounts(migration_doc_name):
    """
    CoA import that creates Bank and Bank Account records for bank accounts
    """
    try:
        # Get the migration document
        # migration_doc = frappe.get_doc("E-Boekhouden Migration", migration_doc_name)

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


def is_potential_bank_account(account_name, account_code=None):
    """
    Enhanced detection for potential bank accounts
    """
    name_lower = account_name.lower()

    # Explicit bank account indicators
    bank_indicators = [
        "bank",
        "rekening",
        "spaarrekening",
        "betaalrekening",
        "girorekening",
        "giro",
        "kas",
        "liquide",
        "triodos",
        "ing",
        "rabo",
        "abn",
        "bunq",
        "sns",
        "asn",
        "paypal",
        "spaar",
        "betaal",
        "zicht",
        "deposito",
    ]

    # Check for bank patterns in name
    for indicator in bank_indicators:
        if indicator in name_lower:
            return True

    # Check for account number patterns (including old 10-digit)
    if has_account_number_pattern(account_name):
        return True

    # Check for group codes that typically contain bank accounts
    if account_code and (account_code.startswith("002") or account_code.startswith("FIN")):
        return True

    return False


def has_account_number_pattern(account_name):
    """
    Check if account name contains recognizable account number patterns
    """
    patterns = [
        r"\d{2}\.\d{2}\.\d{2}\.\d{3}",  # xx.xx.xx.xxx (Triodos style)
        r"\d{3,4}\.\d{2}\.\d{3,4}",  # xxx.xx.xxx format
        r"\b\d{10}\b",  # Old 10-digit account numbers
        r"\b\d{7,9}\b",  # 7-9 digit account numbers
        r"NL\d{2}[A-Z]{4}\d{10}",  # Full IBAN format
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # Email (PayPal, etc.)
    ]

    for pattern in patterns:
        if re.search(pattern, account_name):
            return True

    return False


def extract_bank_info_from_account_name(account_name):
    """
    Enhanced bank info extraction with support for old account numbers

    Common patterns:
    - "Triodos - 19.83.96.716 - Algemeen"
    - "ING - 123456789"
    - "Rabo - 1234.56.789 - Zakelijk"
    - "PayPal - info@veganisme.org"
    - "Triodos Spaarrekening - 1234567890"
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

    # Enhanced patterns including old 10-digit numbers
    patterns = [
        r"\d{2}\.\d{2}\.\d{2}\.\d{3}",  # xx.xx.xx.xxx (Triodos style)
        r"\d{3,4}\.\d{2}\.\d{3,4}",  # xxx.xx.xxx format
        r"\b\d{10}\b",  # Old 10-digit account numbers
        r"\b\d{7,9}\b",  # 7-9 digit account numbers
        r"NL\d{2}[A-Z]{4}\d{10}",  # Full IBAN format
    ]

    # Try each pattern
    account_number = None
    for pattern in patterns:
        match = re.search(pattern, name)
        if match:
            account_number = match.group(0)
            # For IBAN, extract just the account number part
            if pattern == r"NL\d{2}[A-Z]{4}\d{10}":
                bank_info["iban"] = account_number
                account_number = account_number[-10:]  # Last 10 digits
            break

    if account_number:
        bank_info["account_number"] = account_number

    # Enhanced bank name detection
    bank_info["bank_name"] = identify_bank_name_enhanced(name)

    # Extract description from parts
    parts = name.split(" - ")
    if len(parts) >= 1:
        # Use enhanced bank name detection
        if not bank_info["bank_name"]:
            bank_info["bank_name"] = identify_bank_name(parts[0].strip())

    if len(parts) >= 3:
        bank_info["description"] = parts[2].strip()
    elif len(parts) == 2 and not account_number:
        # Might be description in second part
        bank_info["description"] = parts[1].strip()

    # Handle special account types
    if "spaar" in name.lower():
        bank_info["description"] = (
            "Spaarrekening" if not bank_info["description"] else "Spaarrekening - {bank_info['description']}"
        )
    elif "betaal" in name.lower():
        bank_info["description"] = (
            "Betaalrekening"
            if not bank_info["description"]
            else f"Betaalrekening - {bank_info['description']}"
        )

    # Handle special cases like PayPal
    if "paypal" in name.lower():
        bank_info["bank_name"] = "PayPal"
        # Extract email if present
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        email_match = re.search(email_pattern, name)
        if email_match:
            bank_info["account_holder"] = email_match.group(0)
            bank_info["account_number"] = email_match.group(0)

    # Try to generate IBAN if we have enough info and don't have one already
    if bank_info["account_number"] and bank_info["bank_name"] and not bank_info["iban"]:
        bank_info["iban"] = generate_iban_if_possible(bank_info["account_number"], bank_info["bank_name"])

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


def identify_bank_name_enhanced(account_name):
    """
    Enhanced bank name identification from full account name
    """
    name_lower = account_name.lower()

    # Extended bank name patterns
    bank_patterns = {
        "triodos": "Triodos Bank",
        "ing": "ING Bank",
        "rabo": "Rabobank",
        "abn": "ABN AMRO",
        "bunq": "bunq",
        "sns": "SNS Bank",
        "asn": "ASN Bank",
        "paypal": "PayPal",
        "knab": "Knab",
        "regiobank": "RegioBank",
        "volksbank": "de Volksbank",
        "van lanschot": "Van Lanschot",
        "handelsbanken": "Handelsbanken",
        "deutsche": "Deutsche Bank",
        "credit suisse": "Credit Suisse",
        "bnp paribas": "BNP Paribas",
        "postbank": "Postbank",
        "friesland": "Friesland Bank",
        "bng": "BNG Bank",
        "nvb": "Nederlandse Waterschapsbank",
    }

    # Check each pattern
    for pattern, full_name in bank_patterns.items():
        if pattern in name_lower:
            return full_name

    # If no specific bank found, try to extract from first part
    parts = account_name.split(" - ")
    if len(parts) >= 1:
        first_part = parts[0].strip()
        # Check if first part looks like a bank name
        if any(word in first_part.lower() for word in ["bank", "rabo", "ing", "triodos", "abn"]):
            return first_part

    # Default fallback
    return "Unknown Bank"


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
        "knab": "KNAB",
        "regiobank": "REGI",
        "volksbank": "FVLB",
        "van lanschot": "FVLB",
        "handelsbanken": "HAND",
        "deutsche": "DEUT",
        "bng": "BNGB",
        "nvb": "NWAB",
    }

    for key, code in bank_codes.items():
        if key in name_lower:
            return code

    return None


def generate_iban_if_possible(account_number, bank_name):
    """
    Generate IBAN if possible for Dutch banks
    """
    try:
        bank_code = identify_bank_code_from_name(bank_name)
        if bank_code:
            return generate_dutch_iban(account_number, bank_code)
    except Exception as e:
        frappe.logger().debug(f"Could not generate IBAN for {account_number}: {str(e)}")

    return None


def generate_dutch_iban(account_number, bank_code):
    """
    Generate Dutch IBAN from account number and bank code with proper check digit calculation
    """
    try:
        # Remove dots and spaces from account number
        clean_account = account_number.replace(".", "").replace(" ", "")

        # Pad to 10 digits
        if len(clean_account) < 10:
            clean_account = clean_account.zfill(10)
        elif len(clean_account) > 10:
            clean_account = clean_account[:10]

        # Calculate proper check digits using MOD-97 algorithm
        # Create the IBAN structure: NL + check digits + bank code + account number
        # For calculation, we use: bank code + account number + country code (NL=2321) + 00
        check_string = f"{bank_code}{clean_account}232100"

        # Convert letters to numbers (A=10, B=11, ..., Z=35)
        check_digits_calc = ""
        for char in check_string:
            if char.isalpha():
                check_digits_calc += str(ord(char.upper()) - ord("A") + 10)
            else:
                check_digits_calc += char

        # Calculate check digits
        check_digits = 98 - (int(check_digits_calc) % 97)
        check_digits_str = f"{check_digits:02d}"

        # Create final IBAN
        iban = f"NL{check_digits_str}{bank_code}{clean_account}"

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
    Enhanced Bank Account creation with proper CoA mapping validation
    """
    try:
        # Validate that the Chart of Accounts account exists
        account_name = account.get("name") if isinstance(account, dict) else account.name
        if not frappe.db.exists("Account", account_name):
            frappe.logger().error(f"Chart of Accounts account {account_name} not found")
            return None

        # Get account details
        account_doc = frappe.get_doc("Account", account_name) if isinstance(account, dict) else account

        bank_account = frappe.new_doc("Bank Account")

        # Enhanced account name generation - ensure uniqueness
        account_display_name = (
            account_doc.account_name if hasattr(account_doc, "account_name") else account_doc.name
        )

        if bank_info.get("description") and bank_info.get("account_number"):
            bank_account.account_name = (
                "{bank_info['bank_namef']} - {bank_info['account_number']} - {bank_info['description']}"
            )
        elif bank_info.get("account_number"):
            bank_account.account_name = f"{bank_info['bank_name']} - {bank_info['account_number']}"
        elif bank_info.get("description"):
            bank_account.account_name = f"{bank_info['bank_name']} - {bank_info['description']}"
        else:
            # Use Chart of Accounts account name to ensure uniqueness
            bank_account.account_name = f"{bank_info['bank_name']} - {account_display_name}"

        # Critical: Ensure proper Chart of Accounts mapping
        bank_account.account = account_name
        bank_account.bank = bank_name
        bank_account.company = company
        bank_account.is_company_account = 1
        bank_account.is_default = 0

        # Set account details
        if bank_info.get("account_number"):
            bank_account.bank_account_no = bank_info["account_number"]

        # Add IBAN if available
        if bank_info.get("iban"):
            bank_account.iban = bank_info["iban"]

        # Set currency (default to EUR for Dutch banks)
        bank_account.currency = "EUR"

        # Account holder (use company name if not specified)
        if bank_info.get("account_holder"):
            # For non-IBAN accounts like PayPal
            bank_account.party_type = "Company"
            bank_account.party = company

        # Save and validate
        bank_account.insert(ignore_permissions=True)

        # Validate the mapping was successful
        if not bank_account.account:
            frappe.logger().error(f"Bank Account {bank_account.name} created but not mapped to CoA account")
            return None

        # Verify the Chart of Accounts account has proper type
        coa_account_type = frappe.db.get_value("Account", bank_account.account, "account_type")
        if coa_account_type != "Bank":
            frappe.logger().warning(
                "Chart of Accounts account {bank_account.account} should be type 'Bank', got f'{coa_account_type}'"
            )

        frappe.logger().info(f"Created Bank Account: {bank_account.name} mapped to {account_name}")
        return bank_account.name

    except Exception as e:
        # Log detailed error information
        error_msg = f"Error creating Bank Account for {account.get('name', 'Unknown')}: {str(e)}"
        frappe.logger().error(error_msg)

        # Also log to error log for debugging
        frappe.log_error(error_msg, "Bank Account Creation")

        return None


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
            "message": "Created {created_bank_accounts} bank accounts from {len(accounts_to_process)} eligible CoA accounts",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def validate_bank_account_mappings(company=None):
    """
    Validate that all bank accounts are properly mapped to Chart of Accounts
    """
    try:
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        # Get all bank accounts for the company
        bank_accounts = frappe.get_all(
            "Bank Account",
            filters={"company": company},
            fields=["name", "account", "account_name", "bank_account_no", "iban"],
        )

        issues = []
        valid_accounts = []

        for ba in bank_accounts:
            account_issues = []

            # Check if mapped to Chart of Accounts
            if not ba.account:
                account_issues.append("Not mapped to Chart of Accounts")
            elif not frappe.db.exists("Account", ba.account):
                account_issues.append("Mapped to non-existent account {ba.account}")
            else:
                # Check if Chart of Accounts account has proper type
                account_type = frappe.db.get_value("Account", ba.account, "account_type")
                if account_type != "Bank":
                    account_issues.append(
                        "Chart of Accounts account should be type 'Bank', got f'{account_type}'"
                    )

                # Check if account belongs to the same company
                account_company = frappe.db.get_value("Account", ba.account, "company")
                if account_company != company:
                    account_issues.append(f"Account belongs to different company: {account_company}")

            if account_issues:
                issues.append(
                    {"bank_account": ba.name, "account_name": ba.account_name, "issues": account_issues}
                )
            else:
                valid_accounts.append(ba.name)

        return {
            "success": True,
            "total_bank_accounts": len(bank_accounts),
            "valid_accounts": len(valid_accounts),
            "issues_found": len(issues),
            "issues": issues,
            "valid_account_names": valid_accounts,
        }

    except Exception as e:
        frappe.log_error(f"Bank account validation error: {str(e)}", "Bank Account Validation")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def discover_missing_bank_accounts(company=None):
    """
    Find Chart of Accounts accounts that should have Bank Account records
    """
    try:
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        # Get all potential bank accounts from Chart of Accounts
        potential_bank_accounts = frappe.get_all(
            "Account",
            filters={
                "company": company,
                "is_group": 0,
                "account_type": ["in", ["Bank", "Cash", ""]],
            },
            fields=["name", "account_name", "account_number", "account_type"],
        )

        missing_bank_accounts = []
        already_mapped = []

        for account in potential_bank_accounts:
            # Check if this account already has a Bank Account record
            existing_bank_account = frappe.db.exists("Bank Account", {"account": account.name})

            if existing_bank_account:
                already_mapped.append(
                    {
                        "account": account.name,
                        "account_name": account.account_name,
                        "bank_account": existing_bank_account,
                    }
                )
            else:
                # Check if this looks like a bank account
                if (
                    is_potential_bank_account(account.account_name, account.account_number)
                    or account.account_type == "Bank"
                ):
                    # Extract bank info to show what would be created
                    bank_info = extract_bank_info_from_account_name(account.account_name)
                    missing_bank_accounts.append(
                        {
                            "account": account.name,
                            "account_name": account.account_name,
                            "account_type": account.account_type,
                            "extracted_bank_info": bank_info,
                        }
                    )

        return {
            "success": True,
            "missing_bank_accounts": missing_bank_accounts,
            "already_mapped": already_mapped,
            "total_missing": len(missing_bank_accounts),
            "total_mapped": len(already_mapped),
        }

    except Exception as e:
        frappe.log_error(f"Bank account discovery error: {str(e)}", "Bank Account Discovery")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def create_missing_bank_accounts(company=None):
    """
    Create Bank Account records for Chart of Accounts accounts that are missing them
    """
    try:
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        # First discover missing bank accounts
        discovery_result = discover_missing_bank_accounts(company)

        if not discovery_result.get("success"):
            return discovery_result

        missing_accounts = discovery_result.get("missing_bank_accounts", [])
        created_accounts = []
        errors = []

        for missing_account in missing_accounts:
            try:
                account_name = missing_account["account"]
                account_doc = frappe.get_doc("Account", account_name)
                bank_info = missing_account["extracted_bank_info"]

                # Create or get Bank record
                bank_name = get_or_create_bank(bank_info)

                # Create Bank Account record
                bank_account = create_bank_account_record(
                    account=account_doc, bank_name=bank_name, bank_info=bank_info, company=company
                )

                if bank_account:
                    created_accounts.append(
                        {"account": account_name, "bank_account": bank_account, "bank_name": bank_name}
                    )
                else:
                    errors.append(f"Failed to create Bank Account for {account_name}")

            except Exception as e:
                error_msg = f"Error creating Bank Account for {missing_account['account']}: {str(e)}"
                errors.append(error_msg)
                frappe.logger().error(error_msg)

        return {
            "success": True,
            "created_accounts": created_accounts,
            "errors": errors,
            "total_created": len(created_accounts),
            "total_errors": len(errors),
        }

    except Exception as e:
        frappe.log_error(f"Missing bank account creation error: {str(e)}", "Missing Bank Account Creation")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def fix_bank_account_mappings(company=None):
    """
    Fix bank account mappings and ensure Chart of Accounts accounts have proper types
    """
    try:
        if not company:
            settings = frappe.get_single("E-Boekhouden Settings")
            company = settings.default_company

        if not company:
            return {"success": False, "error": "No company specified"}

        # First validate current mappings
        validation_result = validate_bank_account_mappings(company)

        if not validation_result.get("success"):
            return validation_result

        issues = validation_result.get("issues", [])
        fixed_accounts = []
        errors = []

        for issue in issues:
            try:
                bank_account_name = issue["bank_account"]
                bank_account = frappe.get_doc("Bank Account", bank_account_name)

                # Try to fix each issue
                for issue_desc in issue["issues"]:
                    if "should be type 'Bank'" in issue_desc and bank_account.account:
                        # Fix Chart of Accounts account type
                        account_doc = frappe.get_doc("Account", bank_account.account)
                        if account_doc.account_type != "Bank":
                            account_doc.account_type = "Bank"
                            account_doc.save(ignore_permissions=True)
                            fixed_accounts.append(
                                {
                                    "bank_account": bank_account_name,
                                    "account": bank_account.account,
                                    "fix": "Changed account type to 'Bank'",
                                }
                            )

                    elif "different company" in issue_desc:
                        # Log this as it requires manual intervention
                        errors.append(f"Company mismatch for {bank_account_name} - requires manual review")

            except Exception as e:
                error_msg = f"Error fixing {issue['bank_account']}: {str(e)}"
                errors.append(error_msg)
                frappe.logger().error(error_msg)

        return {
            "success": True,
            "fixed_accounts": fixed_accounts,
            "errors": errors,
            "total_fixed": len(fixed_accounts),
            "total_errors": len(errors),
        }

    except Exception as e:
        frappe.log_error(f"Bank account mapping fix error: {str(e)}", "Bank Account Mapping Fix")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def cleanup_duplicate_bank_accounts():
    """
    Clean up duplicate bank accounts with problematic names
    """
    try:
        # Find duplicate bank accounts
        problem_accounts = frappe.get_all(
            "Bank Account",
            filters={
                "account_name": ["like", "%Unknown Bank - None%"],
            },
            fields=["name", "account_name"],
        )

        problem_accounts += frappe.get_all(
            "Bank Account",
            filters={
                "account_name": ["like", "%ING Bank - None%"],
            },
            fields=["name", "account_name"],
        )

        deleted_count = 0
        for account in problem_accounts:
            try:
                frappe.delete_doc("Bank Account", account.name, ignore_permissions=True)
                deleted_count += 1
            except Exception as e:
                frappe.logger().error(f"Error deleting {account.name}: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": "Deleted {deleted_count} problematic bank accounts",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
