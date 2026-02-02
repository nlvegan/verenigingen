"""
Bank Transaction Creator Service

Reusable service for creating Bank Transactions from various sources
(Mollie payments, settlements, manual imports, etc.)
"""

from typing import Dict, Optional, Tuple

import frappe
from frappe.utils import getdate

from verenigingen.utils.retry_utilities import execute_with_deadlock_retry, is_deadlock_error


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
        party_type: Optional[str] = None,
        party: Optional[str] = None,
        bank_party_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create Bank Transaction from Mollie payment object.

        Args:
            payment: Mollie payment object (from SDK)
            bank_account: ERPNext Bank Account name
            company: Company name (auto-detected if not provided)
            additional_description: Optional text to append to description
            party_type: Optional party type (e.g., "Customer") for linking
            party: Optional party name (e.g., Customer name linked to Donor)
            bank_party_name: Optional counterparty name (e.g., donor name)

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
            party_type=party_type,
            party=party,
            bank_party_name=bank_party_name,
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
        Get Mollie bank account configuration from settings with comprehensive validation.

        Uses centralized MollieConfigurationService with GL account validation.

        NOTE: This method is used for virtual account payment processing, so it skips
        settlement bank account validation. Settlement account is only relevant when
        processing Mollie settlement payouts, not individual payments received.

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
            # Use centralized validation from configuration service
            # Skip settlement account validation - only needed for settlement processing
            mollie_config = get_mollie_config()
            validation_result = mollie_config.validate_all_mollie_accounts(
                raise_on_error=False, skip_settlement_account=True
            )

            if not validation_result["valid"]:
                # Log detailed validation errors
                for error in validation_result["errors"]:
                    frappe.log_error(
                        f"Mollie GL Account validation failed: {error}",
                        "Bank Transaction Creator Configuration Error",
                    )

                # Return first error for immediate feedback
                return {
                    "error": f"Configuration validation failed: {', '.join(validation_result['errors'])}",
                }

            # Get clearing account GL (now validated)
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
        Get default company using centralized configuration service.

        Uses MollieConfigurationService for consistent company resolution with
        proper priority chain (Verenigingen Settings → Global Defaults → User defaults).

        Returns:
            Company name (validated to exist)

        Raises:
            frappe.ValidationError: If no company configured

        Note: This method wraps MollieConfigurationService.get_default_company()
        for backward compatibility within BankTransactionCreator.
        """
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

        return get_mollie_config().get_default_company()

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
        **additional_fields,
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
            **additional_fields: Additional fields to set on Bank Transaction (e.g., custom_member)

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
            **additional_fields,
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
        import time

        from frappe.exceptions import DuplicateEntryError

        from verenigingen.utils.secure_operations import secure_document_operation

        # Deadlock retry configuration
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                # CRITICAL: Double-check for existing Bank Transaction immediately before insert
                # This minimizes the race condition window between check and insert
                existing_bt_name = self._check_existing_by_reference(reference_number)
                if existing_bt_name:
                    frappe.logger().info(
                        f"⏭️ Bank Transaction already exists (caught in retry loop): {existing_bt_name}"
                    )
                    return existing_bt_name

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
                    return bank_transaction.name
                else:
                    # Document created but not submitted (draft state)
                    frappe.logger().info(
                        f"✅ Created Bank Transaction (draft): {bank_transaction.name} "
                        f"(ref: {reference_number}) - user lacks submit permission"
                    )
                    return bank_transaction.name

            except (DuplicateEntryError, frappe.UniqueValidationError) as dup_error:
                # Handle race condition: another process created this Bank Transaction
                # UniqueValidationError is raised by secure_document_operation when IntegrityError occurs
                frappe.logger().info(
                    f"⏭️ Bank Transaction already created (race condition): {reference_number}"
                )

                # Query the existing Bank Transaction - it MUST exist since we got a duplicate error
                existing_bt_name = self._check_existing_by_reference(reference_number)

                if existing_bt_name:
                    frappe.logger().info(
                        f"✅ Successfully recovered from race condition - using existing BT: {existing_bt_name}"
                    )
                    return existing_bt_name
                else:
                    # This should never happen - we got a duplicate error but can't find the record
                    # This could indicate a database issue or the record was created and immediately deleted
                    frappe.logger().error(
                        f"❌ CRITICAL: Got duplicate error for {reference_number} but cannot find existing record. "
                        f"Retrying... (attempt {retry_count + 1}/{max_retries})"
                    )
                    retry_count += 1
                    if retry_count < max_retries:
                        time.sleep(0.1)  # Brief wait before retry
                        continue
                    else:
                        frappe.log_error(
                            f"Race condition recovery failed for {reference_number}: {dup_error}",
                            "Bank Transaction Race Condition Error",
                        )
                        return None

            except frappe.QueryDeadlockError as e:
                # Deadlock detected - retry with exponential backoff
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = 0.1 * (2 ** (retry_count - 1))  # 0.1s, 0.2s, 0.4s
                    frappe.logger().warning(
                        f"⚠️ Deadlock creating Bank Transaction (ref: {reference_number}), "
                        f"retry {retry_count}/{max_retries} after {wait_time}s"
                    )
                    time.sleep(wait_time)
                    continue  # Retry
                else:
                    # Max retries exceeded
                    frappe.logger().error(
                        f"❌ Failed to create Bank Transaction after {max_retries} retries due to deadlocks: {e}"
                    )
                    frappe.log_error(
                        f"Bank Transaction creation failed after {max_retries} deadlock retries for reference {reference_number}: {e}",
                        "Bank Transaction Deadlock Error",
                    )
                    return None

            except Exception as e:
                frappe.logger().error(f"❌ Failed to create Bank Transaction: {e}")
                frappe.log_error(
                    f"Bank Transaction creation failed for reference {reference_number}: {e}",
                    "Bank Transaction Creation Error",
                )
                return None

        # Should never reach here, but safety fallback
        return None

    def link_payment_entry(
        self,
        bt_name: str,
        pe_name: str,
        allocated_amount: Optional[float] = None,
    ) -> bool:
        """
        Link a Payment Entry to a Bank Transaction using ERPNext's reconciliation pattern.

        This method properly reconciles a Bank Transaction with a Payment Entry,
        following the same pattern as ERPNext's Bank Reconciliation Tool.

        The proper ERPNext pattern is:
            bt_doc.add_payment_entries([voucher])
            bt_doc.validate_duplicate_references()
            bt_doc.allocate_payment_entries()
            bt_doc.update_allocated_amount()
            bt_doc.set_status()
            bt_doc.save()

        Includes retry logic for transient errors (deadlocks, timeouts) with
        exponential backoff. Non-retryable errors (validation) fail immediately.

        Args:
            bt_name: Bank Transaction name
            pe_name: Payment Entry name
            allocated_amount: Optional specific amount to allocate (auto-calculated if None)

        Returns:
            True if linked successfully, False otherwise

        Example:
            creator = get_bank_transaction_creator()
            success = creator.link_payment_entry("ACC-BTN-2025-00001", "ACC-PAY-2025-00001")
            if success:
                print("Bank Transaction reconciled with Payment Entry")
        """
        # Check if already linked (idempotent) - do this outside retry loop
        existing_link = frappe.db.exists(
            "Bank Transaction Payments",
            {"parent": bt_name, "payment_entry": pe_name},
        )
        if existing_link:
            frappe.logger().debug(f"BT {bt_name} already linked to PE {pe_name}")
            return True

        def perform_link() -> Tuple[bool, str]:
            """
            Inner function to perform the actual linking.

            Returns:
                Tuple of (success, status_or_error)
            """
            bt_doc = frappe.get_doc("Bank Transaction", bt_name)

            # Use ERPNext's standard reconciliation pattern
            voucher = {
                "payment_doctype": "Payment Entry",
                "payment_name": pe_name,
            }
            bt_doc.add_payment_entries([voucher])  # Adds entry with allocated_amount=0
            bt_doc.validate_duplicate_references()
            bt_doc.allocate_payment_entries()  # Calculates actual allocation
            bt_doc.update_allocated_amount()
            bt_doc.set_status()
            bt_doc.save()

            # Reload to get updated status after save hooks run
            bt_doc.reload()

            # Get actual allocated amount for logging
            actual_allocated = 0
            for pe in bt_doc.payment_entries:
                if pe.payment_entry == pe_name:
                    actual_allocated = pe.allocated_amount
                    break

            # Set clearance date on PE if not already set
            pe_doc = frappe.get_doc("Payment Entry", pe_name)
            if not pe_doc.clearance_date and bt_doc.date:
                pe_doc.db_set("clearance_date", bt_doc.date, update_modified=False)

            return (True, f"allocated: {actual_allocated}, status: {bt_doc.status}")

        try:
            # Use centralized retry logic for transient errors (deadlocks, timeouts)
            success, status_info = execute_with_deadlock_retry(
                perform_link,
                operation_name=f"link BT {bt_name} to PE {pe_name}",
                max_retries=3,
                log_errors=True,
            )

            if success:
                frappe.logger().info(
                    f"✅ Linked Bank Transaction {bt_name} to Payment Entry {pe_name} ({status_info})"
                )
            return success

        except frappe.ValidationError as e:
            # Validation errors are non-retryable - log and fail
            frappe.logger().warning(f"Validation error linking BT {bt_name} to PE {pe_name}: {e}")
            frappe.log_error(
                f"BT-PE link validation failed: BT={bt_name}, PE={pe_name}, error={e}",
                "BT-PE Link Validation Error",
            )
            return False

        except Exception as e:
            # Check if this was a retryable error that exhausted retries
            if is_deadlock_error(e):
                frappe.logger().error(
                    f"Failed to link BT {bt_name} to PE {pe_name} after max retries (deadlock): {e}"
                )
                frappe.log_error(
                    f"BT-PE link failed after retries: BT={bt_name}, PE={pe_name}, error={e}",
                    "BT-PE Link Deadlock Error",
                )
            else:
                frappe.logger().warning(f"Could not link BT {bt_name} to PE {pe_name}: {e}")
                frappe.log_error(
                    f"BT-PE link failed: BT={bt_name}, PE={pe_name}, error={e}",
                    "BT-PE Link Error",
                )
            return False


def get_bank_transaction_creator() -> BankTransactionCreator:
    """
    Factory function to get BankTransactionCreator singleton.

    Returns:
        BankTransactionCreator instance
    """
    return BankTransactionCreator()
