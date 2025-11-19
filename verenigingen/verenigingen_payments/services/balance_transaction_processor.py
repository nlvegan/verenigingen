"""
Balance Transaction Processor
Creates ERPNext Bank Transactions from Mollie Balance Transactions

This processor provides unlimited historical access to Mollie transaction data,
complementing the settlement processor which is limited to 90 days.

Business Workflow:
1. Fetch balance transactions from Mollie (no time limit)
2. Extract payment/settlement context from transaction metadata
3. Create Bank Transactions in ERPNext for reconciliation
4. Handle fees via deductions field

Key Advantages:
- No 90-day limitation (access full transaction history)
- Direct fee information via deductions
- Transaction-level granularity
- Context links to payments and settlements

Security: Uses critical_api decorator for financial operations
Audit: Full logging of all processing activities
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import getdate

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient


class BalanceTransactionProcessor:
    """
    Process Mollie Balance Transactions into ERPNext Bank Transactions.

    Provides unlimited historical access to financial data, overcoming
    the 90-day limitation of the Settlement API.
    """

    def __init__(self):
        self.balances_client = BalancesClient()

        # Use centralized Bank Transaction creator
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        self.bank_tx_creator = get_bank_transaction_creator()

    def process_balance_transactions(
        self,
        balance_id: str,
        from_date: Optional[datetime] = None,
        until_date: Optional[datetime] = None,
        limit: int = 250,
    ) -> Dict:
        """
        Process balance transactions into Bank Transactions.

        Args:
            balance_id: Mollie balance ID (usually primary balance)
            from_date: Start date for transaction retrieval
            until_date: End date for transaction retrieval
            limit: Maximum transactions to process (default: 250)

        Returns:
            dict: {
                "total_transactions": int,
                "processed": int,
                "already_processed": int,
                "errors": int,
                "results": List[Dict] with individual transaction results
            }
        """
        result = {
            "total_transactions": 0,
            "processed": 0,
            "already_processed": 0,
            "errors": 0,
            "results": [],
        }

        try:
            # Fetch balance transactions (no 90-day limit!)
            transactions = self.balances_client.list_balance_transactions(
                balance_id=balance_id,
                from_date=from_date,
                until_date=until_date,
                limit=limit,
            )

            result["total_transactions"] = len(transactions)

            frappe.logger().info(
                f"Processing {len(transactions)} balance transactions from {from_date} to {until_date}"
            )

            for transaction in transactions:
                try:
                    # Process each balance transaction
                    tx_result = self._process_single_transaction(transaction)

                    result["results"].append(tx_result)

                    if tx_result["status"] == "success":
                        result["processed"] += 1
                    elif tx_result["status"] == "already_processed":
                        result["already_processed"] += 1
                    elif tx_result["status"] == "error":
                        result["errors"] += 1

                except Exception as e:
                    error_msg = f"Error processing balance transaction {transaction.id}: {str(e)}"
                    frappe.logger().error(error_msg)
                    result["errors"] += 1
                    result["results"].append(
                        {
                            "transaction_id": transaction.id,
                            "status": "error",
                            "error": str(e),
                        }
                    )

            # Commit all changes
            frappe.db.commit()

            frappe.logger().info(
                f"✅ Balance transaction processing complete: "
                f"{result['processed']} processed, "
                f"{result['already_processed']} already processed, "
                f"{result['errors']} errors"
            )

        except Exception as e:
            frappe.log_error(
                f"Error in balance transaction processing: {str(e)}",
                "Balance Transaction Processing Error",
            )
            result["error"] = str(e)

        return result

    def _process_single_transaction(self, transaction) -> Dict:
        """
        Process a single balance transaction into a Bank Transaction.

        Creates ONE Bank Transaction for each balance transaction:
        - Regular payments: Recorded at gross amount (fees already deducted per-payment)
        - Settlement transactions: Recorded at net amount (what actually hits real bank)
        - Fees recorded in description for visibility and audit trail

        Args:
            transaction: BalanceTransaction object

        Returns:
            dict: Processing result
        """
        result = {
            "transaction_id": transaction.id,
            "status": "pending",
            "bank_transaction": None,
        }

        try:
            # Extract transaction data
            transaction_id = transaction.id
            transaction_type = transaction.type

            # Extract context early (needed for idempotency check)
            context = transaction.context or {}
            payment_id = context.get("paymentId") or context.get("payment_id")
            settlement_id = context.get("settlementId") or context.get("settlement_id")
            payment_description = context.get("paymentDescription") or context.get("payment_description")

            # Detect settlement transactions via settlement_id in context
            # Settlement transactions represent payouts from Mollie virtual balance to real bank
            is_settlement = bool(settlement_id)

            # MULTI-FIELD IDEMPOTENCY CHECK
            # Check for existing Bank Transaction using multiple strategies to prevent duplicates
            # across different Mollie APIs (Payment API, Balance Transaction API, Settlement API)

            # Strategy 1: Check by balance transaction ID in reference_number
            existing_bt = frappe.db.get_value(
                "Bank Transaction", {"reference_number": transaction_id}, "name"
            )

            if existing_bt:
                result["status"] = "already_processed"
                result["bank_transaction"] = existing_bt
                result["message"] = (
                    f"Bank Transaction {existing_bt} already exists (reference_number: {transaction_id})"
                )
                return result

            # Strategy 2: Check by payment ID in reference_number (if available)
            # This prevents duplicates when DuesPaymentProcessor already created a Bank Transaction
            if payment_id:
                existing_bt_by_payment = frappe.db.get_value(
                    "Bank Transaction", {"reference_number": payment_id}, "name"
                )

                if existing_bt_by_payment:
                    result["status"] = "already_processed"
                    result["bank_transaction"] = existing_bt_by_payment
                    result["message"] = (
                        f"Bank Transaction {existing_bt_by_payment} already exists (payment ID: {payment_id})"
                    )
                    frappe.logger().info(
                        f"⏭️ Skipping balance transaction {transaction_id} - "
                        f"Bank Transaction {existing_bt_by_payment} already created from payment {payment_id}"
                    )
                    return result

            # Strategy 3: Check by transaction_id field (unique field)
            # This catches cases where the ID is stored in the unique transaction_id field
            existing_bt_by_txid = frappe.db.get_value(
                "Bank Transaction", {"transaction_id": payment_id if payment_id else transaction_id}, "name"
            )

            if existing_bt_by_txid:
                result["status"] = "already_processed"
                result["bank_transaction"] = existing_bt_by_txid
                result["message"] = (
                    f"Bank Transaction {existing_bt_by_txid} already exists (transaction_id field)"
                )
                frappe.logger().info(
                    f"⏭️ Skipping - Bank Transaction {existing_bt_by_txid} found by transaction_id field"
                )
                return result

            # Extract amounts using centralized extractor
            from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
                get_payment_data_extractor,
            )

            extractor = get_payment_data_extractor()

            # Balance transactions need BOTH result_amount (net) and initial_amount (gross)
            # For now, extract manually since extractor doesn't support dual extraction yet
            result_amount = (
                float(transaction.result_amount.decimal_value)
                if transaction.result_amount and hasattr(transaction.result_amount, "decimal_value")
                else 0.0
            )
            initial_amount = (
                float(transaction.initial_amount.decimal_value)
                if transaction.initial_amount and hasattr(transaction.initial_amount, "decimal_value")
                else 0.0
            )

            # Extract deductions (fees)
            total_deductions = float(transaction.get_total_deductions())

            # Determine deposit/withdrawal direction using initial (gross) amount
            # We want to record the gross amount, not the net after fees
            is_deposit = initial_amount > 0
            deposit = abs(initial_amount) if is_deposit else 0.0
            withdrawal = abs(initial_amount) if not is_deposit else 0.0

            # Get company and bank account using centralized service
            from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
                get_bank_transaction_creator,
            )

            creator = get_bank_transaction_creator()
            config = creator.get_mollie_bank_account_config()

            if config.get("error"):
                result["status"] = "error"
                result["error"] = config["error"]
                return result

            bank_account = config["bank_account"]
            company = config["company"]

            # Use extractor for date and currency extraction
            transaction_date = extractor.extract_date(transaction, field_name="created_at")
            # Currency extraction from balance transaction (tries result_amount.currency first)
            currency = (
                transaction.result_amount.currency
                if transaction.result_amount and hasattr(transaction.result_amount, "currency")
                else "EUR"
            )

            # Build description
            description = self._build_transaction_description(
                transaction_type,
                payment_id,
                settlement_id,
                initial_amount,
                result_amount,
                total_deductions,
                payment_description,
            )

            # Determine transaction_id (unique identifier) for cross-API idempotency
            # Priority: payment_id > settlement_id > balance transaction ID
            # This ensures the same transaction from different Mollie APIs uses the same unique ID
            if payment_id:
                # Payment transaction: Use payment ID for compatibility with DuesPaymentProcessor
                stored_transaction_id = payment_id
                reference_number = payment_id
            elif settlement_id:
                # Settlement transaction: Use settlement ID as primary identifier
                stored_transaction_id = settlement_id
                reference_number = settlement_id
            else:
                # Pure balance transaction: Use balance transaction ID
                stored_transaction_id = transaction_id
                reference_number = transaction_id

            # Create Bank Transaction using centralized service
            # For settlements: Use result_amount (net after fees) since that's what hits the bank
            # For regular payments: Use initial_amount (gross) since fees were already deducted per-payment
            # Fees are recorded in description for visibility
            try:
                # Use result_amount for settlements (net), initial_amount for regular payments (gross)
                amount_to_record = result_amount if is_settlement else initial_amount
                is_deposit = amount_to_record > 0
                deposit = abs(amount_to_record) if is_deposit else 0.0
                withdrawal = abs(amount_to_record) if not is_deposit else 0.0

                # Use centralized BankTransactionCreator service
                bank_transaction_name = creator.create(
                    date=transaction_date,
                    bank_account=bank_account,
                    company=company,
                    deposit=deposit,
                    withdrawal=withdrawal,
                    currency=currency,
                    reference_number=reference_number,
                    description=description,
                    transaction_id=stored_transaction_id,  # Store balance transaction ID
                )

                if not bank_transaction_name:
                    result["status"] = "error"
                    result["error"] = "Failed to create Bank Transaction via centralized service"
                    return result

                result["status"] = "success"
                result["bank_transaction"] = bank_transaction_name
                result["amount"] = amount_to_record
                result["transaction_type"] = transaction_type
                result["payment_id"] = payment_id
                result["settlement_id"] = settlement_id
                if is_settlement:
                    result["fees"] = total_deductions

                log_msg = f"✅ Created Bank Transaction {bank_transaction_name} from balance transaction {transaction_id}"
                if is_settlement:
                    log_msg += (
                        f" (settlement net: {currency} {result_amount}, fees: {currency} {total_deductions})"
                    )
                else:
                    log_msg += f" (amount: {currency} {amount_to_record})"

                frappe.logger().info(log_msg)

            except frappe.exceptions.DuplicateEntryError:
                # Race condition: Another process created the Bank Transaction between our check and creation
                # Re-query to get the existing record
                existing = frappe.db.get_value(
                    "Bank Transaction",
                    {
                        "reference_number": [
                            "in",
                            [transaction_id, payment_id] if payment_id else [transaction_id],
                        ]
                    },
                    "name",
                )

                if existing:
                    result["status"] = "already_processed"
                    result["bank_transaction"] = existing
                    result["message"] = f"Bank Transaction {existing} created by concurrent process"
                    frappe.logger().info(
                        f"⏭️ Detected race condition for transaction {transaction_id} - "
                        f"Bank Transaction {existing} already created"
                    )
                else:
                    # Unexpected: duplicate error but can't find the duplicate
                    result["status"] = "error"
                    result["error"] = "Duplicate entry error occurred but existing Bank Transaction not found"

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            frappe.log_error(
                f"Error processing balance transaction {transaction.id}: {str(e)}",
                "Balance Transaction Processing Error",
            )

        return result

    def _build_transaction_description(
        self,
        transaction_type: str,
        payment_id: Optional[str],
        settlement_id: Optional[str],
        initial_amount: float,
        result_amount: float,
        deductions: float,
        payment_description: Optional[str] = None,
    ) -> str:
        """
        Build human-readable description for Bank Transaction.

        Start with the most important info (payment description) for title_field display.

        Args:
            transaction_type: Type of balance transaction
            payment_id: Linked payment ID (if any)
            settlement_id: Linked settlement ID (if any)
            initial_amount: Gross amount
            result_amount: Net amount
            deductions: Total fees
            payment_description: Human-readable payment description from Mollie

        Returns:
            str: Description text (starts with payment description for title_field)
        """
        # Start with payment description if available (most important for user recognition)
        if payment_description:
            description = payment_description
        else:
            description = f"Mollie {transaction_type.replace('-', ' ').title()}"

        # Add payment ID reference (critical for reconciliation)
        if payment_id:
            description += f" | {payment_id}"

        # Add settlement reference (for settlement transactions)
        if settlement_id:
            description += f" | Settlement: {settlement_id}"

        # Add fee information if deductions exist
        if abs(deductions) >= 0.01:
            description += f" | Fees: EUR {abs(deductions):.2f}"

        # Show gross vs net if different (optional detail at end)
        if abs(initial_amount - result_amount) >= 0.01:
            description += f" (Gross: EUR {abs(initial_amount):.2f}, Net: EUR {abs(result_amount):.2f})"

        return description

    def _validate_configuration(self) -> Dict:
        """
        Validate Mollie and ERPNext configuration.

        Uses centralized MollieConfigurationService with comprehensive GL account validation.
        Balance transactions go to the Mollie clearing account (virtual account),
        not the physical bank account.

        Returns:
            dict: Configuration details or error
        """
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

        try:
            # Use centralized validation from configuration service
            # Skip settlement account validation - balance transactions are from virtual account
            mollie_config = get_mollie_config()
            validation_result = mollie_config.validate_all_mollie_accounts(
                raise_on_error=False, skip_settlement_account=True
            )

            if not validation_result["valid"]:
                # Log detailed validation errors
                for error in validation_result["errors"]:
                    frappe.log_error(
                        f"Mollie GL Account validation failed: {error}",
                        "Balance Transaction Processing Configuration Error",
                    )

                # Return first error for immediate feedback
                return {
                    "status": "error",
                    "error": f"Configuration validation failed: {', '.join(validation_result['errors'])}",
                }

            # Get configuration from helper (bank account lookup)
            config = self.bank_tx_creator.get_mollie_bank_account_config()

            if config.get("error"):
                return {
                    "status": "error",
                    "error": config["error"],
                }

            return {
                "status": "valid",
                "bank_account": config["bank_account"],
                "company": config["company"],
            }

        except frappe.ValidationError as e:
            return {
                "status": "error",
                "error": str(e),
            }

    def get_primary_balance_id(self) -> str:
        """
        Get the primary balance ID for the organization.

        Returns:
            str: Primary balance ID

        Raises:
            frappe.ValidationError: If no primary balance found
        """
        try:
            primary_balance = self.balances_client.get_primary_balance()
            return primary_balance.id
        except Exception as e:
            frappe.throw(
                _("Could not retrieve primary balance: {0}").format(str(e)),
                frappe.ValidationError,
            )

    def process_historical_data(self, months_back: int = 12, batch_size: int = 250) -> Dict:
        """
        Process historical balance transactions in batches.

        Useful for initial data migration or catching up on old transactions.

        Args:
            months_back: Number of months to look back (default: 12)
            batch_size: Transactions per batch (default: 250)

        Returns:
            dict: Overall processing results
        """
        overall_result = {
            "total_processed": 0,
            "total_errors": 0,
            "total_already_processed": 0,
            "batches": [],
        }

        try:
            # Get primary balance
            balance_id = self.get_primary_balance_id()

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=months_back * 30)

            frappe.logger().info(
                f"Starting historical data processing: {months_back} months "
                f"({start_date.date()} to {end_date.date()})"
            )

            # Process in batches
            current_date = start_date
            batch_num = 1

            while current_date < end_date:
                batch_end = min(current_date + timedelta(days=30), end_date)

                frappe.logger().info(
                    f"Processing batch {batch_num}: {current_date.date()} to {batch_end.date()}"
                )

                batch_result = self.process_balance_transactions(
                    balance_id=balance_id,
                    from_date=current_date,
                    until_date=batch_end,
                    limit=batch_size,
                )

                overall_result["batches"].append(
                    {
                        "batch_number": batch_num,
                        "from_date": current_date.isoformat(),
                        "to_date": batch_end.isoformat(),
                        "result": batch_result,
                    }
                )

                overall_result["total_processed"] += batch_result["processed"]
                overall_result["total_errors"] += batch_result["errors"]
                overall_result["total_already_processed"] += batch_result["already_processed"]

                current_date = batch_end
                batch_num += 1

            frappe.logger().info(
                f"✅ Historical processing complete: "
                f"{overall_result['total_processed']} processed, "
                f"{overall_result['total_already_processed']} already processed, "
                f"{overall_result['total_errors']} errors"
            )

        except Exception as e:
            frappe.log_error(
                f"Error in historical data processing: {str(e)}",
                "Balance Historical Processing Error",
            )
            overall_result["error"] = str(e)

        return overall_result
