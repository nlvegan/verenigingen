import base64
import hashlib
import os
import tempfile
import traceback

import frappe
from frappe.utils import getdate, today

# Dutch Banking Transaction Type Mapping (ING, Triodos, ABN AMRO, Rabobank)
DUTCH_BOOKING_CODES = {
    "005": "Transfer/Wire",
    "020": "Check Payment",
    "051": "Periodic Transfer",
    "115": "POS Payment",
    "152": "ATM Withdrawal",
    "186": "Direct Debit",
    "199": "Cash Deposit",
    "202": "Bank Transfer",
    "544": "SEPA Credit Transfer",
    "694": "SEPA Direct Debit",
    "805": "Bank Costs",
    "806": "Bank Charges",
    "901": "Cash Withdrawal",
    "904": "Interest Credit",
    "905": "Interest Debit",
}

# SEPA Transaction Types for enhanced classification
SEPA_TRANSACTION_TYPES = {
    "SALA": "Salary Payment",
    "PENS": "Pension Payment",
    "DIVD": "Dividend Payment",
    "GOVT": "Government Payment",
    "TRAD": "Trade Payment",
    "LOAN": "Loan Payment",
    "RENT": "Rent Payment",
    "UTIL": "Utility Payment",
    "TELE": "Telephone Payment",
    "INSUR": "Insurance Payment",
    "TAXES": "Tax Payment",
    "CHAR": "Charity Payment",
    "SECU": "Securities Purchase/Sale",
}


@frappe.whitelist()
def import_mt940_file(bank_account, file_content, company=None):
    """
    Import MT940 bank statement file without expensive fintech license.

    Args:
        bank_account: ERPNext Bank Account name
        file_content: Base64 encoded MT940 file content
        company: Company name (optional, will be fetched from bank account)

    Returns:
        dict: Import results with success/error information
    """
    try:
        # Validate inputs
        if not bank_account:
            return {"success": False, "message": "Bank Account is required"}

        if not file_content:
            return {"success": False, "message": "File content is required"}

        # Decode file content
        try:
            mt940_content = base64.b64decode(file_content).decode("utf-8")
        except Exception as e:
            return {"success": False, "message": f"Failed to decode file content: {str(e)}"}

        # Get company from bank account if not provided
        if not company:
            company = frappe.db.get_value("Bank Account", bank_account, "company")
            if not company:
                return {
                    "success": False,
                    "message": f"Could not determine company for bank account {bank_account}",
                }

        # Validate bank account exists
        if not frappe.db.exists("Bank Account", bank_account):
            return {"success": False, "message": f"Bank Account {bank_account} does not exist"}

        # Process the MT940 file
        result = process_mt940_document(mt940_content, bank_account, company)

        return result

    except Exception as e:
        frappe.logger().error(f"Error in MT940 import: {str(e)}")
        frappe.logger().error(traceback.format_exc())
        return {"success": False, "message": f"Import failed with error: {str(e)}"}


def extract_sepa_data_enhanced(mt940_transaction):
    """
    Extract SEPA data from MT940 transaction using Banking app approach.

    Attempts to access SEPA fields (EREF, MREF, CRED, SVWZ, ABWA) if available
    in the mt940 library, with fallbacks to standard MT940 fields.
    """
    transaction_data = mt940_transaction.data

    # Try to access SEPA fields if available in mt940 library
    sepa_data = getattr(mt940_transaction, "sepa", {}) or {}

    # Extract enhanced SEPA information with fallbacks
    eref = (
        sepa_data.get("EREF")
        or transaction_data.get("transaction_reference")
        or transaction_data.get("reference")
        or ""
    )

    # Mandate Reference - crucial for direct debit processing
    mref = sepa_data.get("MREF") or transaction_data.get("mandate_reference") or ""

    # Payment purpose (Verwendungszweck) - enhanced description
    svwz = (
        sepa_data.get("SVWZ") or transaction_data.get("purpose") or transaction_data.get("description") or ""
    )

    # Creditor Reference
    creditor_ref = sepa_data.get("CRED") or transaction_data.get("creditor_reference") or ""

    # Counterparty name (ABWA = Abweichender Auftraggeber/Begünstigter)
    counterparty = (
        sepa_data.get("ABWA")
        or transaction_data.get("counterparty_name")
        or transaction_data.get("name")
        or ""
    )

    # Additional SEPA data extraction
    counterparty_iban = (
        transaction_data.get("counterparty_account")
        or transaction_data.get("iban")
        or transaction_data.get("account")
        or ""
    )

    return {
        "eref": eref,
        "mref": mref,
        "svwz": svwz,
        "creditor_ref": creditor_ref,
        "counterparty": counterparty,
        "counterparty_iban": counterparty_iban,
        "raw_sepa": sepa_data,  # Keep raw SEPA data for debugging
    }


def get_enhanced_transaction_type(mt940_transaction):
    """
    Enhanced transaction type classification using Banking app approach.

    Priority order:
    1. booking_text (human-readable bank description)
    2. Dutch booking code mapping
    3. SEPA transaction type classification
    4. Amount-based fallback
    """
    transaction_data = mt940_transaction.data

    # Priority 1: Use booking_text if available (Banking app approach)
    booking_text = transaction_data.get("booking_text")
    if booking_text and booking_text.strip():
        return booking_text.strip()[:50]  # ERPNext field limit

    # Priority 2: Map Dutch banking codes
    booking_key = transaction_data.get("booking_key") or transaction_data.get("gv_code")
    if booking_key and str(booking_key) in DUTCH_BOOKING_CODES:
        return DUTCH_BOOKING_CODES[str(booking_key)]

    # Priority 3: SEPA transaction type classification
    sepa_data = extract_sepa_data_enhanced(mt940_transaction)
    purpose = sepa_data["svwz"].upper()

    for sepa_code, sepa_type in SEPA_TRANSACTION_TYPES.items():
        if sepa_code in purpose:
            return sepa_type

    # Priority 4: Amount-based fallback with transaction direction
    amount_obj = transaction_data.get("amount")
    if amount_obj:
        amount = float(amount_obj.amount) if hasattr(amount_obj, "amount") else float(amount_obj)
    else:
        amount = 0

    if amount > 0:
        return "Incoming Transfer"
    else:
        return "Outgoing Transfer"


def get_enhanced_duplicate_hash(mt940_transaction, sepa_data):
    """
    Enhanced duplicate detection using Banking app strategy.

    Includes transaction type and SEPA data for more robust duplicate detection.
    """
    transaction_data = mt940_transaction.data

    # Enhanced hash components following Banking app approach
    # Extract date and amount from transaction data
    trans_date = transaction_data.get("date", "")
    amount_obj = transaction_data.get("amount")
    if amount_obj:
        amount_val = amount_obj.amount if hasattr(amount_obj, "amount") else amount_obj
        currency_val = getattr(amount_obj, "currency", "EUR") if hasattr(amount_obj, "currency") else "EUR"
    else:
        amount_val = 0
        currency_val = "EUR"

    values_to_hash = [
        str(trans_date),  # Transaction date
        str(amount_val),  # Amount
        str(currency_val),  # Currency
        sepa_data["eref"],  # SEPA End-to-end reference
        sepa_data["counterparty"],  # Counterparty name
        sepa_data["counterparty_iban"],  # Counterparty IBAN
        get_enhanced_transaction_type(mt940_transaction),  # Transaction type
        sepa_data["svwz"],  # SEPA payment purpose
        transaction_data.get("booking_key", ""),  # Bank booking code
        transaction_data.get("bank_reference", ""),  # Bank reference
    ]

    # Create SHA256 hash
    sha = hashlib.sha256()
    for value in values_to_hash:
        if value:
            sha.update(str(value).encode("utf-8"))

    return sha.hexdigest()


def extract_sepa_purpose_code(purpose_text):
    """
    Extract SEPA purpose code from payment purpose text.

    Args:
        purpose_text: Payment purpose text from SVWZ field

    Returns:
        str: SEPA purpose code (e.g., SALA, PENS, GOVT) or empty string
    """
    if not purpose_text:
        return ""

    purpose_upper = purpose_text.upper()

    # Check for SEPA purpose codes in the text
    for code in SEPA_TRANSACTION_TYPES.keys():
        if code in purpose_upper:
            return code

    return ""


def process_mt940_document(mt940_content, bank_account, company):
    """
    Process MT940 document content using the WoLpH/mt940 library.

    Uses the free mt940 library instead of expensive fintech license.
    """
    try:
        # Try to import the mt940 library
        try:
            import mt940
        except ImportError:
            return {
                "success": False,
                "message": "MT940 library not available. Please install with: pip install mt-940",
            }

        # Write content to temporary file (mt940 library expects file path)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            # Parse the MT940 file
            transactions = mt940.parse(temp_file_path)

            # Convert to list to check if any transactions found
            transaction_list = list(transactions)

            if not transaction_list:
                return {"success": False, "message": "No transactions found in MT940 file"}

            # Get bank account IBAN for validation
            bank_account_iban = frappe.db.get_value("Bank Account", bank_account, "bank_account_no")

            # Process transactions
            transactions_created = 0
            transactions_skipped = 0
            errors = []
            statement_iban = None

            # Process transactions - avoid double counting by processing all transactions directly
            processed_transaction_ids = set()  # Track processed transactions to avoid duplicates

            for statement in transaction_list:
                # Extract IBAN from statement
                if hasattr(statement, "data") and "account_identification" in statement.data:
                    statement_iban = statement.data["account_identification"]

                # Validate IBAN matches (if available)
                if bank_account_iban and statement_iban and bank_account_iban != statement_iban:
                    return {
                        "success": False,
                        "message": f"IBAN mismatch: Bank Account IBAN {bank_account_iban} does not match MT940 IBAN {statement_iban}",
                    }

                # In MT940 library, each statement object IS a transaction, not a container
                # The library structure treats each parsed item as a single transaction
                try:
                    # Generate transaction ID to check for duplicates within this import
                    from verenigingen.utils.mt940_import import (
                        extract_sepa_data_enhanced,
                        get_enhanced_duplicate_hash,
                    )

                    sepa_data = extract_sepa_data_enhanced(statement)
                    transaction_id = get_enhanced_duplicate_hash(statement, sepa_data)[:16]

                    # Skip if we've already processed this exact transaction in this import
                    if transaction_id in processed_transaction_ids:
                        continue

                    processed_transaction_ids.add(transaction_id)

                    # Create bank transaction using enhanced method
                    if create_enhanced_bank_transaction_from_mt940(statement, bank_account, company):
                        transactions_created += 1
                    else:
                        transactions_skipped += 1

                except Exception as e:
                    errors.append(f"Transaction error: {str(e)}")
                    frappe.logger().error(f"Error processing MT940 transaction: {str(e)}")

            # Calculate date range from processed transactions - each statement IS a transaction
            transaction_dates = []
            processed_dates = set()  # Track unique dates to avoid duplicates

            for statement in transaction_list:
                # Extract date from statement data
                transaction_data = getattr(statement, "data", {})
                if transaction_data and "date" in transaction_data:
                    date_obj = transaction_data["date"]
                    date_str = str(date_obj)

                    # Only add unique dates to avoid counting the same date multiple times
                    if date_str not in processed_dates:
                        transaction_dates.append(date_obj)
                        processed_dates.add(date_str)

            # Determine date range
            from_date = min(transaction_dates) if transaction_dates else getdate(today())
            to_date = max(transaction_dates) if transaction_dates else getdate(today())

            return {
                "success": True,
                "message": f"Import completed: {transactions_created} transactions created, {transactions_skipped} skipped",
                "transactions_created": transactions_created,
                "transactions_skipped": transactions_skipped,
                "errors": errors[:10],  # Limit errors shown
                "iban": statement_iban,
                "statement_date": str(getdate(today())),
                "statement_from_date": str(from_date),
                "statement_to_date": str(to_date),
                "transaction_count": len(transaction_dates),
            }

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception as e:
        return {"success": False, "message": f"Failed to process MT940 document: {str(e)}"}


def create_enhanced_bank_transaction_from_mt940(mt940_transaction, bank_account, company):
    """
    Enhanced Bank Transaction creation inspired by Banking app approach.

    Features:
    - Advanced SEPA data extraction (EREF, MREF, SVWZ, ABWA)
    - Sophisticated transaction type classification
    - Enhanced duplicate detection using multiple fields
    - Better handling of Dutch banking codes
    """
    try:
        import contextlib

        # Extract enhanced SEPA data
        sepa_data = extract_sepa_data_enhanced(mt940_transaction)

        # Generate enhanced transaction ID using Banking app strategy
        transaction_id = get_enhanced_duplicate_hash(mt940_transaction, sepa_data)[:16]

        # Check if transaction already exists
        if transaction_id and frappe.db.exists(
            "Bank Transaction", {"transaction_id": transaction_id, "bank_account": bank_account}
        ):
            return False  # Already exists

        # Create new Bank Transaction with enhanced data
        bt = frappe.new_doc("Bank Transaction")

        # Extract date from transaction data
        transaction_data = mt940_transaction.data
        bt.date = transaction_data.get("date") or getdate(today())
        bt.bank_account = bank_account
        bt.company = company

        # Handle amount and direction - amount is in the data structure
        amount_obj = transaction_data.get("amount")
        if amount_obj:
            amount = float(amount_obj.amount) if hasattr(amount_obj, "amount") else float(amount_obj)
            bt.currency = getattr(amount_obj, "currency", "EUR") if hasattr(amount_obj, "currency") else "EUR"
        else:
            amount = 0.0
            bt.currency = "EUR"

        bt.deposit = max(amount, 0)
        bt.withdrawal = abs(min(amount, 0))

        # Enhanced description using SEPA SVWZ field (Banking app approach)
        description = sepa_data["svwz"]
        if not description:
            # Fallback to other description sources
            transaction_data = mt940_transaction.data
            description_parts = []
            if transaction_data.get("purpose"):
                description_parts.append(str(transaction_data["purpose"]))
            if transaction_data.get("extra_details"):
                description_parts.append(str(transaction_data["extra_details"]))
            description = " | ".join(filter(None, description_parts))

        bt.description = description or "MT940 Transaction"

        # Enhanced transaction type using Banking app approach
        bt.transaction_type = get_enhanced_transaction_type(mt940_transaction)

        # Enhanced reference using SEPA EREF (Banking app approach)
        reference = sepa_data["eref"]
        bt.reference_number = reference if reference != "NONREF" else ""
        bt.transaction_id = transaction_id

        # Enhanced party information using SEPA ABWA field
        bt.bank_party_name = sepa_data["counterparty"]
        bt.bank_party_iban = sepa_data["counterparty_iban"]

        # Store additional SEPA data in custom fields (if available)
        try:
            from verenigingen.utils.mt940_enhanced_fields import (
                populate_enhanced_mt940_fields,
                validate_enhanced_fields_exist,
            )

            if validate_enhanced_fields_exist():
                enhanced_data = {
                    "mandate_reference": sepa_data["mref"],
                    "creditor_reference": sepa_data["creditor_ref"],
                    "booking_key": mt940_transaction.data.get("booking_key", ""),
                    "bank_reference": mt940_transaction.data.get("bank_reference", ""),
                    "enhanced_transaction_type": bt.transaction_type,
                    "sepa_purpose_code": extract_sepa_purpose_code(sepa_data["svwz"]),
                }

                populate_enhanced_mt940_fields(bt, enhanced_data)
            else:
                # Store in temporary attribute for debugging if fields don't exist
                bt._enhanced_data = {
                    "mandate_reference": sepa_data["mref"],
                    "creditor_reference": sepa_data["creditor_ref"],
                    "booking_key": mt940_transaction.data.get("booking_key", ""),
                    "bank_reference": mt940_transaction.data.get("bank_reference", ""),
                    "raw_sepa": sepa_data["raw_sepa"],
                }
        except ImportError:
            # Enhanced fields module not available
            pass

        # Insert and submit with enhanced error handling
        with contextlib.suppress(frappe.exceptions.UniqueValidationError):
            bt.insert()
            bt.submit()

            # Log enhanced transaction creation for debugging
            frappe.logger().info(
                f"Enhanced MT940 transaction created: {transaction_id} - "
                f"{bt.transaction_type} - {amount} {bt.currency} - {sepa_data['counterparty']}"
            )
            return True

    except Exception as e:
        frappe.logger().error(f"Error creating enhanced bank transaction from MT940: {str(e)}")
        # Log additional debug information
        frappe.logger().error(f"Transaction data: {getattr(mt940_transaction, 'data', {})}")
        raise

    return False


def create_bank_transaction_from_mt940(mt940_transaction, bank_account, company):
    """
    Legacy function - redirects to enhanced version for backwards compatibility.
    """
    return create_enhanced_bank_transaction_from_mt940(mt940_transaction, bank_account, company)


def generate_mt940_transaction_hash(transaction):
    """Generate a hash for MT940 transaction identification"""
    import hashlib

    sha = hashlib.sha256()
    hash_components = [
        str(transaction.date),
        str(transaction.amount.amount),
        str(getattr(transaction.amount, "currency", "EUR")),
        str(transaction.data.get("transaction_reference", "")),
        str(transaction.data.get("bank_reference", "")),
        str(transaction.data.get("purpose", "")),
        str(transaction.data.get("counterparty_name", "")),
        str(transaction.data.get("counterparty_account", "")),
    ]

    sha.update("".join(hash_components).encode())
    return sha.hexdigest()[:16]  # Use first 16 characters


@frappe.whitelist()
def get_mt940_import_status():
    """Get status of recent MT940 imports"""
    try:
        # Get recent bank transactions that might have been imported
        recent_transactions = frappe.get_all(
            "Bank Transaction",
            filters={"modified": [">=", frappe.utils.add_days(today(), -7)]},
            fields=["name", "date", "bank_account", "deposit", "withdrawal", "description"],
            order_by="modified desc",
            limit=20,
        )

        return {
            "success": True,
            "recent_transactions": recent_transactions,
            "total_recent": len(recent_transactions),
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def validate_mt940_file(file_content):
    """Validate an MT940 file without importing it"""
    try:
        # Decode file content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        # Try to import mt940 library
        try:
            import mt940
        except ImportError:
            return {
                "success": False,
                "message": "MT940 library not available. Please install with: pip install mt-940",
            }

        # Write to temporary file and parse
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            # Parse document
            transactions = mt940.parse(temp_file_path)
            transaction_list = list(transactions)

            # Count total transactions
            total_transactions = 0
            statement_iban = None

            for statement in transaction_list:
                if hasattr(statement, "data") and "account_identification" in statement.data:
                    statement_iban = statement.data["account_identification"]

                # Count transactions in statement
                if hasattr(statement, "transactions"):
                    total_transactions += len(statement.transactions)
                elif hasattr(statement, "__iter__"):
                    try:
                        total_transactions += len(list(statement))
                    except Exception:
                        total_transactions += 1
                else:
                    total_transactions += 1

            return {
                "success": True,
                "message": f"Valid MT940 file with {total_transactions} transactions",
                "transaction_count": total_transactions,
                "iban": statement_iban or "Unknown",
                "file_size": len(mt940_content),
                "statements_count": len(transaction_list),
            }

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception as e:
        return {"success": False, "message": f"Invalid MT940 file: {str(e)}"}


@frappe.whitelist()
def convert_mt940_to_csv(file_content, bank_account):
    """
    Convert MT940 file to CSV format that ERPNext can import.

    This provides an alternative approach using ERPNext's existing
    Bank Statement Import functionality.
    """
    try:
        # Decode and validate MT940 content
        mt940_content = base64.b64decode(file_content).decode("utf-8")

        # Import mt940 library
        try:
            import mt940
        except ImportError:
            return {
                "success": False,
                "message": "MT940 library not available. Please install with: pip install mt-940",
            }

        # Parse MT940 file
        import csv
        import io

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sta", delete=False) as temp_file:
            temp_file.write(mt940_content)
            temp_file_path = temp_file.name

        try:
            transactions = mt940.parse(temp_file_path)

            # Create CSV output
            output = io.StringIO()
            csv_writer = csv.writer(output)

            # Write header row matching ERPNext Bank Transaction fields
            csv_writer.writerow(
                [
                    "Date",
                    "Description",
                    "Reference Number",
                    "Deposit",
                    "Withdrawal",
                    "Bank Account",
                    "Bank Party Name",
                    "Bank Party IBAN",
                ]
            )

            # Write transaction rows
            for statement in transactions:
                statement_transactions = []
                if hasattr(statement, "transactions"):
                    statement_transactions = statement.transactions
                elif hasattr(statement, "__iter__"):
                    try:
                        statement_transactions = list(statement)
                    except Exception:
                        statement_transactions = [statement]
                else:
                    statement_transactions = [statement]

                for transaction in statement_transactions:
                    transaction_data = transaction.data
                    amount = float(transaction.amount.amount)

                    csv_writer.writerow(
                        [
                            transaction.date.strftime("%Y-%m-%d"),
                            transaction_data.get("purpose", "MT940 Transaction"),
                            transaction_data.get("transaction_reference", ""),
                            max(amount, 0),  # Deposit (positive amounts)
                            abs(min(amount, 0)),  # Withdrawal (negative amounts as positive)
                            bank_account,
                            transaction_data.get("counterparty_name", ""),
                            transaction_data.get("counterparty_account", ""),
                        ]
                    )

            csv_content = output.getvalue()
            output.close()

            # Encode as base64 for download
            csv_base64 = base64.b64encode(csv_content.encode()).decode()

            return {
                "success": True,
                "message": "MT940 file converted to CSV successfully",
                "csv_content": csv_base64,
                "filename": f"mt940_import_{today()}.csv",
            }

        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception as e:
        return {"success": False, "message": f"Failed to convert MT940 to CSV: {str(e)}"}
