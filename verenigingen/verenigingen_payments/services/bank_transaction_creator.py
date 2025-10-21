"""
Bank Transaction Creator Service

Reusable service for creating Bank Transactions from various sources
(Mollie payments, settlements, manual imports, etc.)
"""

from typing import Dict, Optional

import frappe
from frappe.utils import getdate


class BankTransactionCreator:
    """Service for creating Bank Transactions with idempotency and validation"""

    def _safe_extract_amount(self, payment) -> float:
        """
        Safely extract and validate payment amount.

        Args:
            payment: Mollie payment object

        Returns:
            Validated amount as float

        Raises:
            ValueError: If amount is invalid or out of acceptable range
        """
        try:
            amount_dict = getattr(payment, "amount", {})
            if not amount_dict:
                raise ValueError("Payment missing amount field")

            amount_value = amount_dict.get("value", "0")

            # Validate type
            if not isinstance(amount_value, (str, int, float)):
                raise ValueError(f"Invalid amount type: {type(amount_value).__name__}")

            # Convert to float
            amount = float(amount_value)

            # Validate range
            if amount < 0:
                raise ValueError(f"Negative amount not allowed: {amount}")

            if amount > 1_000_000:  # Sanity check for unusually large amounts
                frappe.logger().warning(f"Unusually large payment amount: €{amount}")

            if amount == 0:
                raise ValueError("Zero amount not allowed")

            return amount

        except (ValueError, TypeError, AttributeError) as e:
            frappe.logger().error(f"Amount extraction failed: {e}")
            raise ValueError(f"Invalid payment amount: {getattr(payment, 'amount', 'N/A')}") from e

    def _safe_extract_currency(self, payment, company: str) -> str:
        """
        Safely extract and validate payment currency.

        Args:
            payment: Mollie payment object
            company: Company name for validation

        Returns:
            Validated currency code

        Raises:
            ValueError: If currency is missing or invalid
        """
        import re

        try:
            amount_dict = getattr(payment, "amount", {})
            currency = amount_dict.get("currency")

            # Require explicit currency
            if not currency:
                raise ValueError("Payment missing currency field")

            # Validate ISO currency code format (3 uppercase letters)
            if not isinstance(currency, str) or not re.match(r"^[A-Z]{3}$", currency):
                raise ValueError(f"Invalid currency code format: {currency}")

            # Verify against company default
            company_currency = frappe.get_cached_value("Company", company, "default_currency")
            if currency != company_currency:
                frappe.logger().warning(
                    f"Currency mismatch: Payment is {currency}, company uses {company_currency}. "
                    f"Multi-currency transaction may require exchange rate handling."
                )

            return currency

        except (ValueError, AttributeError) as e:
            frappe.logger().error(f"Currency extraction failed: {e}")
            raise ValueError(f"Invalid payment currency: {getattr(payment, 'amount', 'N/A')}") from e

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

        # Safe extraction with validation (can raise ValueError)
        amount = self._safe_extract_amount(payment)
        currency = self._safe_extract_currency(payment, company)

        # Extract other fields
        description = payment.description or f"Mollie payment {payment_id}"
        paid_at = getattr(payment, "paid_at", None)
        payment_date = getdate(paid_at) if paid_at else getdate()

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

    def get_mollie_bank_account_config(self) -> Dict[str, any]:
        """
        Get Mollie bank account configuration from settings.

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
        # Get Mollie settings
        mollie_settings = frappe.get_single("Mollie Settings")
        mollie_clearing_account = getattr(mollie_settings, "mollie_clearing_account", None)

        if not mollie_clearing_account:
            return {
                "error": "Mollie Clearing Account not configured in Mollie Settings",
            }

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

        from verenigingen.security.permission_validator import secure_document_operation

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

            bank_transaction = frappe.get_doc(bank_transaction_dict)

            # Use secure document operation for creation with permission validation
            create_result = secure_document_operation(
                operation="create",
                doc=bank_transaction,
                justification=f"Bank Transaction creation via centralized service: {reference_number}",
                required_permissions=["Bank Transaction:create"],
                allow_system_user=True,
            )

            if not create_result.success:
                frappe.logger().error(
                    f"❌ Permission denied for Bank Transaction creation: {create_result.message}"
                )
                return None

            # Use secure document operation for submission with permission validation
            submit_result = secure_document_operation(
                operation="submit",
                doc=create_result.document,
                justification=f"Auto-submit Bank Transaction: {reference_number}",
                required_permissions=["Bank Transaction:submit"],
                allow_system_user=True,
            )

            if not submit_result.success:
                frappe.logger().error(
                    f"❌ Permission denied for Bank Transaction submission: {submit_result.message}"
                )
                # Cancel the created document if submission fails
                create_result.document.delete()
                return None

            frappe.logger().info(
                f"✅ Created Bank Transaction: {submit_result.document.name} "
                f"(ref: {reference_number}, amount: {currency} {deposit or withdrawal})"
            )

            return submit_result.document.name

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
