import base64
import os
import tempfile
import traceback

import frappe


@frappe.whitelist()
def import_mt940_file_auto(file_content, company=None):
    """
    Import MT940 bank statement file with automatic bank account matching.

    This function automatically finds the correct ERPNext Bank Account by matching
    the IBAN from the MT940 file to the IBAN or bank_account_no in Bank Account records.

    Args:
        file_content: Base64 encoded MT940 file content
        company: Company name (optional, filters bank accounts by company)

    Returns:
        dict: Import results with success/error information and bank account used
    """
    try:
        # Validate input
        if not file_content:
            return {"success": False, "message": "File content is required"}

        # Decode file content
        try:
            mt940_content = base64.b64decode(file_content).decode("utf-8")
        except Exception as e:
            return {"success": False, "message": f"Failed to decode file content: {str(e)}"}

        # Extract IBAN from MT940 file first
        statement_iban = extract_iban_from_mt940(mt940_content)
        if not statement_iban:
            return {
                "success": False,
                "message": "Could not extract IBAN from MT940 file. Please use manual import with specific bank account.",
            }

        # Find matching bank account
        bank_account = find_bank_account_by_iban(statement_iban, company)
        if not bank_account:
            return {
                "success": False,
                "message": f"No Bank Account found with IBAN {statement_iban}. Please create a Bank Account record or use manual import.",
                "extracted_iban": statement_iban,
            }

        # Import using the matched bank account
        from verenigingen.utils.mt940_import import process_mt940_document

        # Get company from bank account if not provided
        if not company:
            company = frappe.db.get_value("Bank Account", bank_account, "company")

        result = process_mt940_document(mt940_content, bank_account, company)

        # Add bank account info to result
        if result.get("success"):
            result["bank_account_used"] = bank_account
            result["matched_iban"] = statement_iban

        return result

    except Exception as e:
        frappe.logger().error(f"Error in automatic MT940 import: {str(e)}")
        frappe.logger().error(traceback.format_exc())
        return {"success": False, "message": f"Import failed with error: {str(e)}"}


def extract_iban_from_mt940(mt940_content):
    """
    Extract IBAN from MT940 file content.

    Looks for the :25: field which contains the account identification.
    """
    try:
        # Try to import the mt940 library
        try:
            import mt940
        except ImportError:
            # Fallback to manual parsing if library not available
            return extract_iban_manual(mt940_content)

        # Use temporary file for mt940 library
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            # Parse with mt940 library
            transactions = mt940.parse(temp_file_path)
            transaction_list = list(transactions)

            for statement in transaction_list:
                if hasattr(statement, "data") and "account_identification" in statement.data:
                    return statement.data["account_identification"]

        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception as e:
        frappe.logger().error(f"Error extracting IBAN from MT940: {str(e)}")

    # Fallback to manual parsing
    return extract_iban_manual(mt940_content)


def extract_iban_manual(mt940_content):
    """
    Manually extract IBAN from MT940 content by parsing :25: field.

    The :25: field in MT940 format contains the account identification (IBAN).
    """
    try:
        lines = mt940_content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith(":25:"):
                # Extract account identification after :25:
                account_id = line[4:].strip()

                # Clean up common prefixes/suffixes
                account_id = account_id.replace("EUR", "").strip()

                # Check if it looks like an IBAN (starts with country code, correct length)
                if len(account_id) >= 15 and account_id[:2].isalpha():
                    return account_id

    except Exception as e:
        frappe.logger().error(f"Error in manual IBAN extraction: {str(e)}")

    return None


def find_bank_account_by_iban(iban, company=None):
    """
    Find ERPNext Bank Account by IBAN.

    Searches in both 'iban' and 'bank_account_no' fields as banks may store
    the account number in either field.

    Args:
        iban: IBAN to search for
        company: Optional company filter

    Returns:
        str: Bank Account name if found, None otherwise
    """
    try:
        # Clean IBAN (remove spaces, convert to uppercase)
        clean_iban = iban.replace(" ", "").upper()

        # Build filters
        filters = {"disabled": 0, "is_company_account": 1}

        if company:
            filters["company"] = company

        # First try exact match in iban field
        filters["iban"] = clean_iban
        bank_account = frappe.db.get_value("Bank Account", filters)
        if bank_account:
            return bank_account

        # Try exact match in bank_account_no field
        filters.pop("iban")
        filters["bank_account_no"] = clean_iban
        bank_account = frappe.db.get_value("Bank Account", filters)
        if bank_account:
            return bank_account

        # Try without spaces in both fields (in case stored differently)
        clean_iban_no_spaces = clean_iban.replace(" ", "")

        # Custom SQL query to handle different formatting
        sql_query = """
            SELECT name FROM `tabBank Account`
            WHERE disabled = 0
            AND is_company_account = 1
            AND (
                REPLACE(UPPER(iban), ' ', '') = %(iban)s
                OR REPLACE(UPPER(bank_account_no), ' ', '') = %(iban)s
            )
        """

        params = {"iban": clean_iban_no_spaces}

        if company:
            sql_query += " AND company = %(company)s"
            params["company"] = company

        sql_query += " LIMIT 1"

        result = frappe.db.sql(sql_query, params)
        if result:
            return result[0][0]

    except Exception as e:
        frappe.logger().error(f"Error finding bank account by IBAN {iban}: {str(e)}")

    return None


@frappe.whitelist()
def get_bank_accounts_for_mt940():
    """
    Get list of available Bank Accounts that can be used for MT940 import.

    Returns company bank accounts with their IBANs for user selection.
    """
    try:
        accounts = frappe.get_all(
            "Bank Account",
            filters={"disabled": 0, "is_company_account": 1},
            fields=["name", "account_name", "iban", "bank_account_no", "bank", "company"],
            order_by="company, account_name",
        )

        return {"success": True, "accounts": accounts, "count": len(accounts)}

    except Exception as e:
        return {"success": False, "message": f"Error fetching bank accounts: {str(e)}"}


@frappe.whitelist()
def preview_mt940_import(file_content):
    """
    Preview MT940 import without actually importing.

    Shows which bank account would be matched and transaction summary.
    """
    try:
        # Decode file content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        # Extract IBAN and find bank account
        statement_iban = extract_iban_from_mt940(mt940_content)
        bank_account = find_bank_account_by_iban(statement_iban) if statement_iban else None

        # Validate the file
        from verenigingen.utils.mt940_import import validate_mt940_file

        validation_result = validate_mt940_file(file_content)

        # Combine results
        return {
            "success": True,
            "extracted_iban": statement_iban,
            "matched_bank_account": bank_account,
            "validation": validation_result,
            "can_auto_import": bool(statement_iban and bank_account),
            "message": "Preview completed successfully",
        }

    except Exception as e:
        return {"success": False, "message": f"Preview failed: {str(e)}"}


@frappe.whitelist()
def setup_bank_account_for_mt940(bank_name, account_name, iban, company):
    """
    Helper function to create/setup a Bank Account for MT940 imports.

    Creates the Bank and Bank Account records if they don't exist.
    """
    try:
        # Clean IBAN
        clean_iban = iban.replace(" ", "").upper()

        # Check if Bank exists, create if not
        if not frappe.db.exists("Bank", bank_name):
            bank = frappe.new_doc("Bank")
            bank.bank_name = bank_name
            bank.insert()

        # Check if Bank Account already exists
        existing_account = find_bank_account_by_iban(clean_iban, company)
        if existing_account:
            return {
                "success": True,
                "message": f"Bank Account {existing_account} already exists with this IBAN",
                "bank_account": existing_account,
            }

        # Create new Bank Account
        bank_account = frappe.new_doc("Bank Account")
        bank_account.account_name = account_name
        bank_account.bank = bank_name
        bank_account.iban = clean_iban
        bank_account.bank_account_no = clean_iban  # Store in both fields
        bank_account.company = company
        bank_account.is_company_account = 1
        bank_account.insert()

        return {
            "success": True,
            "message": f"Bank Account {bank_account.name} created successfully",
            "bank_account": bank_account.name,
        }

    except Exception as e:
        return {"success": False, "message": f"Error creating bank account: {str(e)}"}
