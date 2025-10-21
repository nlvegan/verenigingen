"""
Bank Transaction Creator Service

Reusable service for creating Bank Transactions from various sources
(Mollie payments, settlements, manual imports, etc.)
"""

from typing import Dict, Optional

import frappe
from frappe.utils import getdate


class BankTransactionCreator:
    """
    Service for creating Bank Transactions with idempotency and validation.

    Uses PaymentDataExtractor for consistent amount/currency/date extraction.
    """

    def __init__(self):
        """Initialize with PaymentDataExtractor for data extraction."""
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

        self._extractor = get_payment_data_extractor()

    def create_from_mollie_payment(
        self,
        payment,
        bank_account: str,
        company: Optional[str] = None,
        additional_description: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create Bank Transaction from Mollie payment object.

        Args:
            payment: Mollie payment object (from SDK)
            bank_account: ERPNext Bank Account name
            company: Company name (auto-detected if not provided)
            additional_description: Optional text to append to description

        Returns:
            Bank Transaction name if created/exists, None on failure
        """
        payment_id = payment.id

        # Check for existing Bank Transaction first (before expensive validation)
        existing_bt = self._check_existing_by_reference(payment_id)
        if existing_bt:
            frappe.logger().info(f"⏭️ Bank Transaction already exists: {existing_bt}")
            return existing_bt

        # Auto-detect company if not provided (needed for currency validation)
        if not company:
            company = self._get_default_company()

        # Use centralized PaymentDataExtractor for consistent extraction
        amount = self._extractor.extract_amount(payment)
        currency = self._extractor.extract_currency(payment, company)
        payment_date = self._extractor.extract_date(payment, field_name="paid_at")

        # Extract description
        description = self._extractor.extract_description(
            payment, fallback_description=f"Mollie payment {payment_id}"
        )

        # Build description
        bt_description = description
        if additional_description:
            bt_description += f" | {additional_description}"

        # Create Bank Transaction
        return self._create_bank_transaction(
            date=payment_date,
            bank_account=bank_account,
            company=company,
            deposit=amount,
            withdrawal=0.0,
            currency=currency,
            reference_number=payment_id,
            description=bt_description,
        )

    def create_from_settlement(
        self,
        settlement,
        bank_account: str,
        company: str,
        settlement_amount: float,
        settlement_date,
        currency: str,
        description: str,
    ) -> Optional[str]:
        """
        Create Bank Transaction from Mollie settlement.

        Args:
            settlement: Mollie settlement object
            bank_account: ERPNext Bank Account name
            company: Company name
            settlement_amount: Settlement amount
            settlement_date: Settlement date
            currency: Currency code
            description: Settlement description

        Returns:
            Bank Transaction name if created/exists, None on failure
        """
        settlement_id = settlement.id

        # Check for existing Bank Transaction
        existing_bt = self._check_existing_by_reference(settlement_id)
        if existing_bt:
            frappe.logger().info(f"⏭️ Bank Transaction already exists: {existing_bt}")
            return existing_bt

        # Create Bank Transaction
        return self._create_bank_transaction(
            date=settlement_date,
            bank_account=bank_account,
            company=company,
            deposit=settlement_amount,
            withdrawal=0.0,
            currency=currency,
            reference_number=settlement_id,
            description=description,
        )

    def _check_existing_by_reference(self, reference_number: str) -> Optional[str]:
        """
        Check if Bank Transaction already exists with this reference number.

        Args:
            reference_number: Reference number to check (payment ID, settlement ID, etc.)

        Returns:
            Bank Transaction name if exists, None otherwise
        """
        return frappe.db.get_value("Bank Transaction", {"reference_number": reference_number}, "name")

    def check_already_processed(
        self, reference_number: str, check_payment_entry: bool = False
    ) -> Dict[str, any]:
        """
        Comprehensive idempotency check for payment processing.

        Checks for existing Bank Transaction and optionally Payment Entry to prevent
        duplicate processing. Handles cancelled documents properly (allows reprocessing).

        Args:
            reference_number: Payment/settlement/transaction reference ID
            check_payment_entry: If True, also checks for Payment Entry (default: False)

        Returns:
            dict: {
                "already_processed": bool,  # True if found non-cancelled document
                "bank_transaction": str or None,  # Bank Transaction name if found
                "payment_entry": str or None,  # Payment Entry name if found (when check_payment_entry=True)
                "docstatus": int or None,  # 0=Draft, 1=Submitted, 2=Cancelled
                "document_type": str or None,  # "Bank Transaction" or "Payment Entry"
                "details": str  # Human-readable description
            }

        Examples:
            # Basic check (Bank Transaction only)
            result = creator.check_already_processed("tr_abc123")
            if result["already_processed"]:
                print(f"Already exists: {result['details']}")

            # Dual mode check (both Bank Transaction and Payment Entry)
            result = creator.check_already_processed("tr_abc123", check_payment_entry=True)
            if result["already_processed"]:
                print(f"Found {result['document_type']}: {result['details']}")
        """
        result = {
            "already_processed": False,
            "bank_transaction": None,
            "payment_entry": None,
            "docstatus": None,
            "document_type": None,
            "details": "Not yet processed",
        }

        # Check Payment Entry first (if requested)
        if check_payment_entry:
            existing_entries = frappe.db.get_all(
                "Payment Entry",
                filters={"reference_no": reference_number},
                fields=["name", "docstatus"],
                limit=1,
            )

            if existing_entries:
                entry = existing_entries[0]
                status_map = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
                status_text = status_map.get(entry.docstatus, "Unknown")

                # Cancelled documents can be reprocessed
                if entry.docstatus == 2:
                    frappe.logger().info(
                        f"Found cancelled Payment Entry {entry.name} for reference {reference_number}. "
                        f"Allowing reprocessing."
                    )
                    # Continue to check Bank Transaction below
                else:
                    # Draft or Submitted - already processed
                    result.update(
                        {
                            "already_processed": True,
                            "payment_entry": entry.name,
                            "docstatus": entry.docstatus,
                            "document_type": "Payment Entry",
                            "details": f"Payment Entry {entry.name} already exists ({status_text})",
                        }
                    )
                    return result

        # Check Bank Transaction
        existing_bt = frappe.db.get_all(
            "Bank Transaction",
            filters={"reference_number": reference_number},
            fields=["name", "docstatus"],
            limit=1,
        )

        if existing_bt:
            bt = existing_bt[0]
            status_map = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
            status_text = status_map.get(bt.docstatus, "Unknown")

            # Cancelled documents can be reprocessed
            if bt.docstatus == 2:
                frappe.logger().info(
                    f"Found cancelled Bank Transaction {bt.name} for reference {reference_number}. "
                    f"Allowing reprocessing."
                )
                # Return "not processed" result
                return result
            else:
                # Draft or Submitted - already processed
                result.update(
                    {
                        "already_processed": True,
                        "bank_transaction": bt.name,
                        "docstatus": bt.docstatus,
                        "document_type": "Bank Transaction",
                        "details": f"Bank Transaction {bt.name} already exists ({status_text})",
                    }
                )
                return result

        return result

    def get_mollie_bank_account_config(self) -> Dict[str, any]:
        """
        Get Mollie bank account configuration from settings.

        Uses centralized MollieConfigurationService for consistent configuration access.

        Returns:
            dict with 'bank_account' and 'company', or error info

        Example:
            config = creator.get_mollie_bank_account_config()
            if config.get('error'):
                # Handle error
            else:
                bank_account = config['bank_account']
                company = config['company']
        """
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

        try:
            # Get clearing account GL from centralized config
            mollie_config = get_mollie_config()
            mollie_clearing_account = mollie_config.get_clearing_account()

            # Get Bank Account linked to Mollie clearing account
            # This should return "Mollie" Bank Account, not Triodos
            bank_account = frappe.db.get_value("Bank Account", {"account": mollie_clearing_account}, "name")

            if not bank_account:
                return {
                    "error": f"No Bank Account found for Mollie clearing account '{mollie_clearing_account}'",
                }

            # Get company
            company = self._get_default_company()

            frappe.logger().info(
                f"✅ Mollie config: Bank Account='{bank_account}', Clearing Account='{mollie_clearing_account}'"
            )

            return {
                "bank_account": bank_account,
                "company": company,
                "clearing_account": mollie_clearing_account,
            }

        except frappe.ValidationError as e:
            # MollieConfigurationService throws ValidationError for missing config
            return {"error": str(e)}

    def _get_default_company(self) -> str:
        """
        Get default company from system settings.

        Returns:
            Company name

        Raises:
            ValueError if no default company configured
        """
        company = frappe.defaults.get_user_default("Company")
        if not company:
            # Fallback to first company in system
            company = frappe.db.get_value("Company", {}, "name")

        if not company:
            raise ValueError("No company found in system. Please configure a company first.")

        return company

    def create(
        self,
        date,
        bank_account: str,
        company: str,
        deposit: float,
        withdrawal: float,
        currency: str,
        reference_number: str,
        description: str,
        transaction_id: Optional[str] = None,
        party_type: Optional[str] = None,
        party: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create and submit Bank Transaction (low-level method for all transaction types).

        This is the canonical method for creating Bank Transactions from any source
        (Mollie payments, settlements, balance transactions, manual imports, etc.)

        Args:
            date: Transaction date
            bank_account: Bank Account name (ERPNext Bank Account DocType)
            company: Company name
            deposit: Deposit amount (incoming, use 0 for withdrawals)
            withdrawal: Withdrawal amount (outgoing, use 0 for deposits)
            currency: Currency code (e.g., EUR, USD)
            reference_number: Unique reference for idempotency (payment/settlement/balance ID)
            description: Human-readable description
            transaction_id: Optional additional transaction ID for tracking
            party_type: Optional party type (e.g., "Customer", "Supplier") for dues payments
            party: Optional party name (Customer/Supplier name) for dues payments

        Returns:
            Bank Transaction name if created, None on failure
        """
        # Check for existing Bank Transaction first (idempotency)
        existing_bt = self._check_existing_by_reference(reference_number)
        if existing_bt:
            frappe.logger().info(f"⏭️ Bank Transaction already exists: {existing_bt}")
            return existing_bt

        return self._create_bank_transaction(
            date=date,
            bank_account=bank_account,
            company=company,
            deposit=deposit,
            withdrawal=withdrawal,
            currency=currency,
            reference_number=reference_number,
            description=description,
            transaction_id=transaction_id,
            party_type=party_type,
            party=party,
        )

    def _create_bank_transaction(
        self,
        date,
        bank_account: str,
        company: str,
        deposit: float,
        withdrawal: float,
        currency: str,
        reference_number: str,
        description: str,
        transaction_id: Optional[str] = None,
        party_type: Optional[str] = None,
        party: Optional[str] = None,
    ) -> Optional[str]:
        """
        Internal method to create and submit Bank Transaction.

        Args:
            date: Transaction date
            bank_account: Bank Account name
            company: Company name
            deposit: Deposit amount (incoming)
            withdrawal: Withdrawal amount (outgoing)
            currency: Currency code
            reference_number: Unique reference (payment/settlement ID)
            description: Human-readable description
            transaction_id: Optional transaction ID field

        Returns:
            Bank Transaction name if created, None on failure
        """
        from frappe.exceptions import DuplicateEntryError

        try:
            bank_transaction_dict = {
                "doctype": "Bank Transaction",
                "date": date,
                "bank_account": bank_account,
                "company": company,
                "deposit": deposit,
                "withdrawal": withdrawal,
                "currency": currency,
                "reference_number": reference_number,
                "description": description,
                "status": "Unreconciled",
                "unallocated_amount": deposit if deposit > 0 else abs(withdrawal),
                "allocated_amount": 0.0,
            }

            # Add transaction_id if provided (for balance transactions)
            if transaction_id:
                bank_transaction_dict["transaction_id"] = transaction_id

            # Add party fields if provided (for dues payments)
            if party_type:
                bank_transaction_dict["party_type"] = party_type
            if party:
                bank_transaction_dict["party"] = party

            bank_transaction = frappe.get_doc(bank_transaction_dict)

            # Insert and submit Bank Transaction
            bank_transaction.insert()
            bank_transaction.submit()

            frappe.logger().info(
                f"✅ Created Bank Transaction: {bank_transaction.name} "
                f"(ref: {reference_number}, amount: {currency} {deposit or withdrawal})"
            )

            return bank_transaction.name

        except DuplicateEntryError:
            # Handle race condition: another process created this Bank Transaction
            frappe.logger().info(f"⏭️ Bank Transaction already created (race condition): {reference_number}")
            # Return existing Bank Transaction
            return self._check_existing_by_reference(reference_number)

        except Exception as e:
            frappe.logger().error(f"❌ Failed to create Bank Transaction: {e}")
            frappe.log_error(
                f"Bank Transaction creation failed for reference {reference_number}: {e}",
                "Bank Transaction Creation Error",
            )
            return None


def get_bank_transaction_creator() -> BankTransactionCreator:
    """
    Factory function to get BankTransactionCreator singleton.

    Returns:
        BankTransactionCreator instance
    """
    return BankTransactionCreator()
