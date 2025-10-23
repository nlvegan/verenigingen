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

    def create_from_dict(
        self,
        transaction_data: Dict,
        bank_account: str,
        company: str,
        source_type: str = "Generic Import",
    ) -> Optional[str]:
        """
        Create Bank Transaction from generic dictionary data.

        This method enables Bank Transaction creation from any data source:
        - SEPA/CAMT XML imports
        - MT940 bank statement imports
        - Manual CSV/Excel imports
        - Member payment imports
        - Generic banking integrations

        Args:
            transaction_data: Dictionary with transaction details. Required keys:
                - date: Transaction date (datetime or date object, or ISO string)
                - amount: Transaction amount (float, positive=deposit, negative=withdrawal)

                Optional keys:
                - currency: Currency code (default: EUR)
                - description: Transaction description (default: generated from source_type)
                - reference_number: External reference (default: empty string)
                - transaction_id: Additional transaction ID for tracking
                - party_type: Party type (Customer, Supplier, Member)
                - party: Party name
                - bank_party_name: Counterparty name from bank statement
                - bank_party_iban: Counterparty IBAN
                - bank_party_account_number: Counterparty account number
                - Any custom_ fields will be passed through to Bank Transaction

            bank_account: ERPNext Bank Account name
            company: Company name
            source_type: Source identifier for description (e.g., "SEPA Import", "Member Payment")

        Returns:
            Bank Transaction name if created, None on failure

        Example:
            >>> creator = get_bank_transaction_creator()
            >>> bt_name = creator.create_from_dict(
            ...     transaction_data={
            ...         "date": "2025-10-22",
            ...         "amount": 100.50,
            ...         "currency": "EUR",
            ...         "description": "Monthly donation",
            ...         "reference_number": "DON-2025-001",
            ...         "bank_party_name": "John Doe",
            ...         "bank_party_iban": "NL91ABNA0417164300",
            ...     },
            ...     bank_account="Main Bank Account",
            ...     company="My Company",
            ...     source_type="Donation Import"
            ... )
        """
        # Extract and validate required fields
        date = transaction_data.get("date")
        amount = transaction_data.get("amount")

        if not date:
            frappe.logger().error(f"Missing required field 'date' in transaction_data for {source_type}")
            return None

        if amount is None:
            frappe.logger().error(f"Missing required field 'amount' in transaction_data for {source_type}")
            return None

        # Convert date to proper format if it's a string
        if isinstance(date, str):
            date = getdate(date)

        # Determine deposit/withdrawal based on amount sign
        deposit = float(amount) if amount > 0 else 0.0
        withdrawal = abs(float(amount)) if amount < 0 else 0.0

        # Extract optional fields
        currency = transaction_data.get("currency", "EUR")
        description = transaction_data.get("description", f"{source_type} transaction")
        reference_number = transaction_data.get("reference_number", "")
        transaction_id = transaction_data.get("transaction_id")

        # Check for existing Bank Transaction (idempotency)
        if reference_number:
            existing_bt = self._check_existing_by_reference(reference_number)
            if existing_bt:
                frappe.logger().info(
                    f"Bank Transaction already exists for reference {reference_number}: {existing_bt}"
                )
                return existing_bt

        # Extract party fields
        party_type = transaction_data.get("party_type")
        party = transaction_data.get("party")

        # Extract bank party fields
        bank_party_name = transaction_data.get("bank_party_name")
        bank_party_iban = transaction_data.get("bank_party_iban")
        bank_party_account_number = transaction_data.get("bank_party_account_number")

        # Extract any custom fields (custom_* pattern)
        custom_fields = {
            key: value
            for key, value in transaction_data.items()
            if key.startswith("custom_") and value is not None
        }

        # Create Bank Transaction using centralized method
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
            bank_party_name=bank_party_name,
            bank_party_iban=bank_party_iban,
            bank_party_account_number=bank_party_account_number,
            **custom_fields,
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
        bank_party_name: Optional[str] = None,
        bank_party_iban: Optional[str] = None,
        bank_party_account_number: Optional[str] = None,
        **additional_fields,
    ) -> Optional[str]:
        """
        Internal method to create and submit Bank Transaction using secure operations framework.

        Uses secure_document_operation() to ensure proper permission validation and audit trail.

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
            party_type: Optional party type (Customer, Supplier, Member)
            party: Optional party name
            bank_party_name: Optional counterparty name from bank statement
            bank_party_iban: Optional counterparty IBAN
            bank_party_account_number: Optional counterparty account number
            **additional_fields: Any additional fields to set on Bank Transaction

        Returns:
            Bank Transaction name if created, None on failure
        """
        from frappe.exceptions import DuplicateEntryError

        from verenigingen.utils.secure_operations import secure_document_operation

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

            # Add bank party fields if provided (for SEPA/bank imports)
            if bank_party_name:
                bank_transaction_dict["bank_party_name"] = bank_party_name
            if bank_party_iban:
                bank_transaction_dict["bank_party_iban"] = bank_party_iban
            if bank_party_account_number:
                bank_transaction_dict["bank_party_account_number"] = bank_party_account_number

            # Add any additional custom fields (e.g., Mollie-specific fields)
            for field, value in additional_fields.items():
                if value is not None:
                    bank_transaction_dict[field] = value

            bank_transaction = frappe.get_doc(bank_transaction_dict)

            # Create Bank Transaction using secure operations framework
            # This handles permission validation and creates in draft if user lacks submit permission
            create_result = secure_document_operation(
                operation="create",
                doc=bank_transaction,
                justification=f"Bank Transaction creation from {description[:50]}",
                required_permissions=["Bank Transaction:create"],
                allow_system_user=True,  # Allow system user fallback for webhook/automated contexts
            )

            if not create_result.success:
                error_msg = ", ".join(create_result.errors) if create_result.errors else "Unknown error"
                frappe.logger().error(f"❌ Failed to create Bank Transaction: {error_msg}")
                return None

            # Get the created document
            bank_transaction = create_result.document

            frappe.logger().info(
                f"After create: Bank Transaction {bank_transaction.name} docstatus={bank_transaction.docstatus}"
            )

            # Attempt to submit Bank Transaction using secure operations framework
            # Framework will only submit if current user has submit permission
            # If user lacks permission, document remains in draft state
            submit_result = secure_document_operation(
                operation="submit",
                doc=bank_transaction,
                justification=f"Bank Transaction submission for {reference_number}",
                required_permissions=["Bank Transaction:submit"],
                allow_system_user=False,  # Require actual user permission for submit
            )

            if submit_result.success:
                frappe.logger().info(
                    f"✅ Created and submitted Bank Transaction: {bank_transaction.name} "
                    f"(ref: {reference_number}, amount: {currency} {deposit or withdrawal})"
                )
            else:
                # Document created but not submitted (draft state)
                frappe.logger().info(
                    f"✅ Created Bank Transaction (draft): {bank_transaction.name} "
                    f"(ref: {reference_number}) - user lacks submit permission"
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
