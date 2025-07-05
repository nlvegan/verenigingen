import traceback

import frappe
from frappe.utils import getdate, today


@frappe.whitelist()
def import_camt_file(bank_account, file_content, company=None):
    """
    Manual CAMT.053 file import for when EBICS isn't available or too expensive.

    Args:
        bank_account: ERPNext Bank Account name
        file_content: Base64 encoded CAMT XML file content
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
        import base64

        try:
            xml_content = base64.b64decode(file_content).decode("utf-8")
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

        # Process the CAMT file using the banking app's logic
        result = process_manual_camt_document(xml_content, bank_account, company)

        return result

    except Exception as e:
        frappe.logger().error(f"Error in manual CAMT import: {str(e)}")
        frappe.logger().error(traceback.format_exc())
        return {"success": False, "message": f"Import failed with error: {str(e)}"}


def process_manual_camt_document(xml_content, bank_account, company):
    """
    Process CAMT document content manually without EBICS.

    Uses the same logic as the banking app but for manual file uploads.
    """
    try:
        # Try to import the fintech library (might not be available without license)
        try:
            from fintech.sepa import CAMTDocument
        except ImportError:
            return {
                "success": False,
                "message": "Fintech library not available. For bank file imports, please use MT940 format instead via verenigingen.utils.mt940_import",
            }

        # Parse the CAMT document
        try:
            camt_document = CAMTDocument(xml=xml_content)
        except Exception as e:
            return {"success": False, "message": f"Failed to parse CAMT document: {str(e)}"}

        # Get bank account IBAN for validation
        bank_account_iban = frappe.db.get_value("Bank Account", bank_account, "bank_account_no")

        # Validate IBAN matches (if available)
        if bank_account_iban and camt_document.iban and bank_account_iban != camt_document.iban:
            return {
                "success": False,
                "message": f"IBAN mismatch: Bank Account IBAN {bank_account_iban} does not match CAMT IBAN {camt_document.iban}",
            }

        # Process transactions
        transactions_created = 0
        transactions_skipped = 0
        errors = []

        for transaction in camt_document:
            try:
                # Skip non-booked transactions
                if transaction.status and transaction.status != "BOOK":
                    transactions_skipped += 1
                    continue

                # Create bank transaction using the same logic as EBICS
                if create_bank_transaction_from_sepa(transaction, bank_account, company):
                    transactions_created += 1
                else:
                    transactions_skipped += 1

            except Exception as e:
                errors.append(f"Transaction error: {str(e)}")
                frappe.logger().error(f"Error processing transaction: {str(e)}")

        return {
            "success": True,
            "message": f"Import completed: {transactions_created} transactions created, {transactions_skipped} skipped",
            "transactions_created": transactions_created,
            "transactions_skipped": transactions_skipped,
            "errors": errors[:10],  # Limit errors shown
            "iban": camt_document.iban,
            "statement_date": str(getdate(today())),
        }

    except Exception as e:
        return {"success": False, "message": f"Failed to process CAMT document: {str(e)}"}


def create_bank_transaction_from_sepa(sepa_transaction, bank_account, company):
    """
    Create ERPNext Bank Transaction from SEPA transaction.
    Adapted from banking app's _create_bank_transaction function.
    """
    try:
        import contextlib

        # Generate transaction ID
        transaction_id = (
            getattr(sepa_transaction, "bank_reference", None)
            or getattr(sepa_transaction, "eref", None)
            or generate_transaction_hash(sepa_transaction)
        )

        # Check if transaction already exists
        if transaction_id and frappe.db.exists(
            "Bank Transaction", {"transaction_id": transaction_id, "bank_account": bank_account}
        ):
            return False  # Already exists

        # Create new Bank Transaction
        bt = frappe.new_doc("Bank Transaction")
        bt.date = sepa_transaction.date
        bt.bank_account = bank_account
        bt.company = company

        amount = float(sepa_transaction.amount.value)
        bt.deposit = max(amount, 0)
        bt.withdrawal = abs(min(amount, 0))
        bt.currency = sepa_transaction.amount.currency

        # Set description from purpose lines or info
        purposes = getattr(sepa_transaction, "purpose", [])
        if purposes:
            bt.description = "\n".join(purposes)
        else:
            bt.description = getattr(sepa_transaction, "info", "")

        bt.reference_number = getattr(sepa_transaction, "ere", "")
        bt.transaction_id = transaction_id
        bt.bank_party_iban = getattr(sepa_transaction, "iban", "")
        bt.bank_party_name = getattr(sepa_transaction, "name", "")

        # Insert and submit
        with contextlib.suppress(frappe.exceptions.UniqueValidationError):
            bt.insert()
            bt.submit()
            return True

    except Exception as e:
        frappe.logger().error(f"Error creating bank transaction: {str(e)}")
        raise

    return False


def generate_transaction_hash(transaction):
    """Generate a hash for transaction identification"""
    import hashlib

    sha = hashlib.sha256()
    hash_components = [
        str(transaction.date),
        str(getattr(transaction, "iban", "")),
        str(getattr(transaction, "name", "")),
        str(getattr(transaction, "ere", "")),
        str(transaction.amount.value),
        str(transaction.amount.currency),
        str(getattr(transaction, "info", "")),
    ]

    # Add purpose lines if available
    purposes = getattr(transaction, "purpose", [])
    if purposes:
        hash_components.extend(str(p) for p in purposes)

    sha.update("".join(hash_components).encode())
    return sha.hexdigest()[:16]  # Use first 16 characters


@frappe.whitelist()
def get_import_status():
    """Get status of manual CAMT imports"""
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
def validate_camt_file(file_content):
    """Validate a CAMT file without importing it"""
    try:
        # Decode file content
        import base64

        xml_content = base64.b64decode(file_content).decode("utf-8")

        # Try to import fintech
        try:
            from fintech.sepa import CAMTDocument
        except ImportError:
            return {
                "success": False,
                "message": "Fintech library not available for CAMT validation. For Dutch banks, please use MT940 format instead via verenigingen.utils.mt940_import",
            }

        # Parse document
        camt_document = CAMTDocument(xml=xml_content)

        # Count transactions
        transaction_count = sum(1 for _ in camt_document)

        return {
            "success": True,
            "message": f"Valid CAMT file with {transaction_count} transactions",
            "transaction_count": transaction_count,
            "iban": getattr(camt_document, "iban", "Unknown"),
            "file_size": len(xml_content),
        }

    except Exception as e:
        return {"success": False, "message": f"Invalid CAMT file: {str(e)}"}
