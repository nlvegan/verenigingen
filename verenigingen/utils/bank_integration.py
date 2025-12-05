"""
Bank Integration Utilities for Dutch Banking Systems

Provides functionality for importing bank statements, processing SEPA files,
and handling payment reconciliation with Dutch banks.

Supports:
- CAMT.053 (Cash Management) format
- MT940 (SWIFT) format
- SEPA Direct Debit processing
- Payment reconciliation
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, today


class BankStatementImporter:
    """Main class for importing bank statements from various formats"""

    def __init__(self):
        self.supported_formats = ["CAMT.053", "MT940"]
        self.transactions = []
        self.errors = []
        self.warnings = []

    def import_statement(self, file_path: str, format_type: str) -> Dict:
        """
        Import bank statement from file

        Args:
            file_path: Path to the bank statement file
            format_type: Format type (CAMT.053 or MT940)

        Returns:
            Dict with import results
        """
        try:
            if format_type not in self.supported_formats:
                return {
                    "success": False,
                    "error": f"Unsupported format: {format_type}",
                    "transactions_imported": 0,
                }

            # Read file content
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if format_type == "CAMT.053":
                return self._import_camt053(content)
            elif format_type == "MT940":
                return self._import_mt940(content)

        except Exception as e:
            frappe.log_error(f"Bank statement import error: {str(e)}", "Bank Import Error")
            return {"success": False, "error": f"Import failed: {str(e)}", "transactions_imported": 0}

    def _import_camt053(self, xml_content: str) -> Dict:
        """Import CAMT.053 format bank statement"""
        try:
            # Parse XML
            root = ET.fromstring(xml_content)

            # Define XML namespaces
            ns = {"camt": "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"}

            # Extract account information
            account_element = root.find(".//camt:Acct/camt:Id/camt:IBAN", ns)
            if account_element is None:
                return {
                    "success": False,
                    "error": "No IBAN found in CAMT.053 file",
                    "transactions_imported": 0,
                }

            account_iban = account_element.text

            # Process transactions
            transactions = []
            entries = root.findall(".//camt:Ntry", ns)

            for entry in entries:
                transaction = self._parse_camt_entry(entry, ns, account_iban)
                if transaction:
                    transactions.append(transaction)

            # Create payment entries from transactions
            imported_count = 0
            for transaction in transactions:
                if self._create_payment_entry(transaction):
                    imported_count += 1

            return {
                "success": True,
                "transactions_imported": imported_count,
                "amount_total": sum(t.get("amount", 0) for t in transactions),
                "account_iban": account_iban,
            }

        except ET.ParseError as e:
            return {"success": False, "error": f"Invalid XML format: {str(e)}", "transactions_imported": 0}
        except Exception as e:
            frappe.log_error(f"CAMT.053 import error: {str(e)}", "CAMT Import Error")
            return {
                "success": False,
                "error": f"CAMT.053 processing failed: {str(e)}",
                "transactions_imported": 0,
            }

    def _parse_camt_entry(self, entry, ns: Dict, account_iban: str) -> Optional[Dict]:
        """Parse individual CAMT.053 entry"""
        try:
            # Extract amount and direction
            amount_elem = entry.find("camt:Amt", ns)
            direction_elem = entry.find("camt:CdtDbtInd", ns)

            if amount_elem is None or direction_elem is None:
                return None

            amount = flt(amount_elem.text)
            is_credit = direction_elem.text == "CRDT"

            if not is_credit:
                return None  # Only process credit entries for membership payments

            # Extract booking date
            booking_date_elem = entry.find(".//camt:BookgDt/camt:Dt", ns)
            booking_date = booking_date_elem.text if booking_date_elem is not None else today()

            # Extract debtor information
            debtor_name_elem = entry.find(".//camt:RltdPties/camt:Dbtr/camt:Nm", ns)
            debtor_iban_elem = entry.find(".//camt:RltdPties/camt:DbtrAcct/camt:Id/camt:IBAN", ns)

            # Extract reference information
            end_to_end_elem = entry.find(".//camt:Refs/camt:EndToEndId", ns)
            reference = end_to_end_elem.text if end_to_end_elem is not None else ""

            # Extract remittance information
            remittance_elem = entry.find(".//camt:RmtInf/camt:Ustrd", ns)
            description = remittance_elem.text if remittance_elem is not None else ""

            return {
                "amount": amount,
                "date": booking_date,
                "debtor_name": debtor_name_elem.text if debtor_name_elem is not None else "",
                "debtor_iban": debtor_iban_elem.text if debtor_iban_elem is not None else "",
                "reference": reference,
                "description": description,
                "account_iban": account_iban,
            }

        except Exception as e:
            self.warnings.append(f"Failed to parse CAMT entry: {str(e)}")
            return None

    def _import_mt940(self, mt940_content: str) -> Dict:
        """Import MT940 format bank statement"""
        try:
            lines = mt940_content.strip().split("\n")
            transactions = []
            current_transaction = {}

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Parse MT940 fields
                if line.startswith(":25:"):
                    # Account identification
                    account_info = line[4:]
                    iban_match = re.search(r"([A-Z]{2}\d{2}[A-Z0-9]+)", account_info)
                    account_iban = iban_match.group(1) if iban_match else ""

                elif line.startswith(":61:"):
                    # Statement line
                    if current_transaction:
                        transactions.append(current_transaction)
                        current_transaction = {}

                    # Parse :61: field
                    # Format: :61:YYMMDDMMDDCRDR[funds_code]amount[Swift_code][reference]
                    match = re.match(r":61:(\d{6})(\d{4})?(C|D)R?([0-9,]+)([A-Z]{3})?([A-Z0-9]*)/?(.*)", line)
                    if match:
                        date_str = match.group(1)
                        direction = match.group(3)
                        amount_str = match.group(4).replace(",", ".")
                        reference = match.group(7) if match.group(7) else ""

                        # Only process credit entries
                        if direction == "C":
                            current_transaction = {
                                "date": f"20{date_str[:2]}-{date_str[2:4]}-{date_str[4:6]}",
                                "amount": flt(amount_str),
                                "reference": reference,
                                "account_iban": account_iban,
                            }

                elif line.startswith(":86:") and current_transaction:
                    # Transaction details
                    details = line[4:]

                    # Extract structured information
                    name_match = re.search(r"/NAME/([^/]+)", details)
                    iban_match = re.search(r"([A-Z]{2}\d{2}[A-Z0-9]+)", details)

                    current_transaction.update(
                        {
                            "description": details,
                            "debtor_name": name_match.group(1).strip() if name_match else "",
                            "debtor_iban": iban_match.group(1) if iban_match else "",
                        }
                    )

            # Add last transaction
            if current_transaction:
                transactions.append(current_transaction)

            # Create payment entries
            imported_count = 0
            for transaction in transactions:
                if self._create_payment_entry(transaction):
                    imported_count += 1

            return {
                "success": True,
                "transactions_imported": imported_count,
                "amount_total": sum(t.get("amount", 0) for t in transactions),
            }

        except Exception as e:
            frappe.log_error(f"MT940 import error: {str(e)}", "MT940 Import Error")
            return {
                "success": False,
                "error": f"MT940 processing failed: {str(e)}",
                "transactions_imported": 0,
            }

    def _create_payment_entry(self, transaction: Dict) -> bool:
        """Create payment entry from transaction data"""
        try:
            # Find matching sales invoice
            matching_invoice = self._find_matching_invoice(transaction)
            if not matching_invoice:
                self.warnings.append(
                    f"No matching invoice found for transaction: {transaction.get('reference', 'Unknown')}"
                )
                return False

            # Check for duplicate payment
            existing_payment = frappe.db.exists(
                "Payment Entry", {"reference_no": f"BANK_IMPORT_{matching_invoice}", "docstatus": 1}
            )

            if existing_payment:
                self.warnings.append(f"Payment already exists for invoice {matching_invoice}")
                return False

            # Get invoice details
            invoice = frappe.get_doc("Sales Invoice", matching_invoice)

            # Get default accounts from company
            company_doc = frappe.get_doc("Company", invoice.company)
            default_bank_account = company_doc.default_bank_account
            default_receivable_account = company_doc.default_receivable_account

            # Fall back to getting accounts from Mode of Payment if company defaults not set
            if not default_bank_account:
                mode_of_payment = frappe.get_doc("Mode of Payment", "Bank Transfer")
                for account in mode_of_payment.accounts:
                    if account.company == invoice.company:
                        default_bank_account = account.default_account
                        break

            if not default_receivable_account:
                default_receivable_account = frappe.get_cached_value(
                    "Company", invoice.company, "default_receivable_account"
                )

            # Create payment entry
            payment_entry = frappe.new_doc("Payment Entry")
            payment_entry.update(
                {
                    "payment_type": "Receive",
                    "party_type": "Customer",
                    "party": invoice.customer,
                    "company": invoice.company,
                    "posting_date": transaction.get("date", today()),
                    "paid_amount": transaction["amount"],
                    "received_amount": transaction["amount"],
                    "reference_no": f"BANK_IMPORT_{matching_invoice}",
                    "reference_date": transaction.get("date", today()),
                    "remarks": f"Bank import: {transaction.get('description', '')}",
                    "mode_of_payment": "Bank Transfer",
                    # Exchange rates - mandatory in ERPNext v15+
                    "source_exchange_rate": 1.0,
                    "target_exchange_rate": 1.0,
                    # Payment accounts
                    "paid_from": default_receivable_account,  # Receivables for "Receive" payments
                    "paid_to": default_bank_account,  # Bank account where money goes
                    "paid_from_account_currency": invoice.currency or "EUR",
                    "paid_to_account_currency": "EUR",
                }
            )

            # Add reference to invoice
            payment_entry.append(
                "references",
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": matching_invoice,
                    "allocated_amount": min(transaction["amount"], invoice.outstanding_amount),
                },
            )

            payment_entry.insert()
            payment_entry.submit()

            return True

        except Exception as e:
            self.errors.append(f"Failed to create payment entry: {str(e)}")
            frappe.log_error(f"Payment entry creation error: {str(e)}", "Bank Import Payment Error")
            return False

    def _find_matching_invoice(self, transaction: Dict) -> Optional[str]:
        """Find matching sales invoice for transaction"""
        reference = transaction.get("reference", "")
        amount = transaction.get("amount", 0)
        debtor_name = transaction.get("debtor_name", "")

        # Try to find invoice by reference number
        if reference:
            # Direct reference match
            if frappe.db.exists("Sales Invoice", reference):
                return reference

            # Extract invoice number from reference
            invoice_patterns = [r"(ACC-SINV-\d{4}-\d+)", r"(SINV-\d+)", r"(INV-\d+)"]

            for pattern in invoice_patterns:
                match = re.search(pattern, reference)
                if match and frappe.db.exists("Sales Invoice", match.group(1)):
                    return match.group(1)

        # Try to match by amount and customer
        if debtor_name and amount:
            # Find customer by name
            customers = frappe.get_all(
                "Customer", filters={"customer_name": ["like", f"%{debtor_name}%"]}, fields=["name"]
            )

            for customer in customers:
                # Find unpaid invoice with matching amount
                invoices = frappe.get_all(
                    "Sales Invoice",
                    filters={"customer": customer.name, "outstanding_amount": amount, "docstatus": 1},
                    fields=["name"],
                    limit=1,
                )

                if invoices:
                    return invoices[0].name

        return None


class BankAPIClient:
    """Client for bank API integration"""

    def __init__(self):
        self.timeout = 30
        self.retry_count = 3

    def fetch_statements(self, date: str) -> Dict:
        """
        Fetch bank statements from API using PSD2 standards

        Implements actual bank API integration following Open Banking/PSD2 standards
        used by major Dutch banks (ABN AMRO, ING, Rabobank, etc.)
        """
        try:
            import requests

            # Validate date format
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                return {"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}

            # Get bank configuration from settings
            bank_settings = (
                frappe.get_single("Bank Integration Settings")
                if frappe.db.exists("DocType", "Bank Integration Settings")
                else None
            )

            if not bank_settings or not bank_settings.get("api_endpoint"):
                return {
                    "success": False,
                    "error": "Bank API not configured. Please configure Bank Integration Settings",
                }

            # Prepare OAuth2 headers for PSD2 compliance
            headers = {
                "Authorization": f"Bearer {bank_settings.get('access_token', '')}",
                "X-Request-ID": frappe.generate_hash(length=16),
                "PSU-IP-Address": frappe.local.request.environ.get("REMOTE_ADDR", "127.0.0.1"),
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            # Build API request for account statements
            api_url = f"{bank_settings.api_endpoint}/accounts/{bank_settings.account_id}/transactions"
            params = {"dateFrom": date, "dateTo": date, "bookingStatus": "booked"}  # PSD2 standard parameter

            # Make actual API request with timeout
            response = requests.get(
                api_url, headers=headers, params=params, timeout=30  # 30 second timeout for bank APIs
            )

            # Handle response
            if response.status_code == 200:
                response_data = response.json()

                # Extract transactions in standardized format
                transactions = []
                if "transactions" in response_data:
                    for txn in response_data["transactions"]["booked"]:
                        transactions.append(
                            {
                                "transaction_id": txn.get("transactionId"),
                                "amount": float(txn.get("transactionAmount", {}).get("amount", 0)),
                                "currency": txn.get("transactionAmount", {}).get("currency", "EUR"),
                                "booking_date": txn.get("bookingDate"),
                                "value_date": txn.get("valueDate"),
                                "reference": txn.get("remittanceInformationUnstructured", ""),
                                "counterparty_name": txn.get("debtorName") or txn.get("creditorName", ""),
                                "counterparty_account": txn.get("debtorAccount", {}).get("iban")
                                or txn.get("creditorAccount", {}).get("iban", ""),
                            }
                        )

                return {
                    "success": True,
                    "statements": transactions,
                    "date": date,
                    "bank": bank_settings.get("bank_name", "Unknown"),
                    "account": bank_settings.get("account_id", ""),
                }

            elif response.status_code == 401:
                return {"success": False, "error": "Unauthorized. Please refresh bank API token"}
            elif response.status_code == 429:
                return {"success": False, "error": "Rate limit exceeded. Please try again later"}
            else:
                return {
                    "success": False,
                    "error": f"Bank API error: {response.status_code} - {response.text}",
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Bank API request timeout - please try again later"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Cannot connect to bank API - please check network connection"}
        except Exception as e:
            frappe.log_error(f"Bank API integration error: {str(e)}", "Bank Integration Error")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}


def import_bank_statement(file_path: str, format_type: str) -> Dict:
    """
    Main function to import bank statement

    Args:
        file_path: Path to bank statement file
        format_type: Format type (CAMT.053 or MT940)

    Returns:
        Dict with import results
    """
    importer = BankStatementImporter()
    return importer.import_statement(file_path, format_type)


def create_bank_transaction(transaction_data: Dict) -> str:
    """
    Create bank transaction record.

    Uses centralized BankTransactionCreator for consistent creation logic.

    Args:
        transaction_data: Transaction information (must include bank_account, company, amount, date)

    Returns:
        Name of created bank transaction
    """
    from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
        get_bank_transaction_creator,
    )

    # Extract required fields
    bank_account = transaction_data.get("bank_account")
    company = transaction_data.get("company")

    if not bank_account or not company:
        frappe.throw("bank_account and company are required for Bank Transaction creation")

    # Prepare transaction data for BankTransactionCreator
    creator_data = {
        "date": transaction_data.get("date", today()),
        "amount": transaction_data.get("amount", 0),
        "currency": transaction_data.get("currency", "EUR"),
        "description": transaction_data.get("description", "Bank integration transaction"),
        "reference_number": transaction_data.get("reference_number", ""),
    }

    # Create Bank Transaction using centralized service
    creator = get_bank_transaction_creator()
    bank_transaction_name = creator.create_from_dict(
        transaction_data=creator_data,
        bank_account=bank_account,
        company=company,
        source_type="Bank Integration",
    )

    if not bank_transaction_name:
        frappe.throw("Failed to create Bank Transaction")

    return bank_transaction_name
