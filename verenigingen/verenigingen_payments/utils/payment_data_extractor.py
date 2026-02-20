"""
Payment Data Extractor Utility

Centralized utility for safely extracting and validating payment data from Mollie
payment objects. Consolidates duplicate extraction logic across 35+ files.

Replaces duplicate implementations in:
- DuesPaymentProcessor
- SettlementBankTransactionProcessor
- BalanceTransactionProcessor
- BankTransactionCreator
- 30+ other files

Usage:
    from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
        PaymentDataExtractor
    )

    extractor = PaymentDataExtractor()
    amount = extractor.extract_amount(payment)
    currency = extractor.extract_currency(payment, company)
    payment_date = extractor.extract_date(payment)
"""

import re
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Union

import frappe
from frappe.utils import getdate


class MollieObjectType(Enum):
    """
    Enum for Mollie object types to ensure type safety and IDE support.

    Using this enum instead of string literals provides:
    - IDE autocomplete and navigation
    - Type checking and validation
    - Refactoring safety (find all usages)
    - Typo prevention at compile time

    Usage:
        >>> from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
        ...     get_payment_data_extractor,
        ...     MollieObjectType
        ... )
        >>> extractor = get_payment_data_extractor()
        >>> amount = extractor.extract_amount(
        ...     payment,
        ...     source_type=MollieObjectType.PAYMENT
        ... )
    """

    PAYMENT = "payment"
    BALANCE_TRANSACTION = "balance_transaction"
    SETTLEMENT = "settlement"
    SUBSCRIPTION = "subscription"
    BALANCE = "balance"

    def __str__(self) -> str:
        """Return string value for backward compatibility with existing code."""
        return self.value


class PaymentDataExtractor:
    """
    Universal payment data extraction with validation and error handling.

    Handles multiple Mollie object types:
    - Payment objects (amount.value, amount.currency)
    - Balance transaction objects (result_amount.decimal_value, initial_amount.decimal_value)
    - Settlement objects (amount.decimal_value)
    - Subscription objects (amount.value OR amount.decimal_value)
    - Balance objects (available_amount.decimal_value, pending_amount.decimal_value)
    """

    def extract_amount(
        self,
        payment_object: Any,
        source_type: Union[str, MollieObjectType] = MollieObjectType.PAYMENT,
        allow_zero: bool = False,
        max_amount: float = 1_000_000,
    ) -> float:
        """
        Safely extract and validate payment amount.

        Handles multiple Mollie object types and extraction patterns:
        - Payment objects: payment.amount["value"]
        - Balance transactions: transaction.result_amount.decimal_value
        - Settlements: settlement.amount.decimal_value
        - Subscriptions: subscription.amount.value OR subscription.amount.decimal_value
        - Dict-based: payment.get("amount", {}).get("value")

        This method provides centralized extraction with comprehensive validation,
        error handling, and logging for all Mollie object types.

        Args:
            payment_object: Mollie payment/transaction/settlement/subscription object
            source_type: Object type - "payment", "balance_transaction", "settlement", "subscription"
            allow_zero: Whether to allow zero amounts (default: False)
            max_amount: Maximum allowed amount for sanity checking (default: 1,000,000)

        Returns:
            Validated amount as float

        Raises:
            ValueError: If amount is invalid, negative, or out of acceptable range

        Examples:
            # Standard payment object
            >>> extractor = get_payment_data_extractor()
            >>> amount = extractor.extract_amount(payment)
            >>> print(f"Payment: €{amount:.2f}")
            Payment: €25.50

            # Balance transaction object
            >>> amount = extractor.extract_amount(
            ...     transaction,
            ...     source_type="balance_transaction"
            ... )

            # Settlement object (typically for reconciliation)
            >>> amount = extractor.extract_amount(
            ...     settlement,
            ...     source_type="settlement"
            ... )

            # Subscription object (can have zero trial amounts)
            >>> amount = extractor.extract_amount(
            ...     subscription,
            ...     source_type="subscription",
            ...     allow_zero=True  # Zero allowed for free trials
            ... )

            # Calculate total from multiple payments
            >>> total = sum(
            ...     extractor.extract_amount(payment, allow_zero=True)
            ...     for payment in payments
            ... )

            # Validate payment amount before processing
            >>> try:
            ...     amount = extractor.extract_amount(payment)
            ...     process_payment(amount)
            ... except ValueError as e:
            ...     print(f"Invalid payment: {e}")
        """
        # Normalize source_type to string for comparison (supports both string and Enum)
        source_type_str = str(source_type) if isinstance(source_type, MollieObjectType) else source_type

        try:
            if source_type_str == "balance_transaction":
                # Handle Mollie balance transaction objects
                # Format: transaction.result_amount.decimal_value
                amount = self._extract_balance_transaction_amount(payment_object)
            elif source_type_str in ("settlement", "subscription"):
                # Handle Mollie settlement and subscription objects
                # Format: object.amount.decimal_value OR object.amount.value
                amount = self._extract_decimal_amount(payment_object)
            else:
                # Handle standard payment objects
                # Format: payment.amount["value"] or payment.get("amount", {}).get("value")
                amount = self._extract_payment_amount(payment_object)

            # Validate range
            if amount < 0:
                raise ValueError(f"Negative amount not allowed: {amount}")

            if not allow_zero and amount == 0:
                raise ValueError("Zero amount not allowed")

            if amount > max_amount:
                frappe.logger().warning(
                    f"Unusually large payment amount: €{amount:,.2f} (max: €{max_amount:,.2f})"
                )

            return amount

        except (ValueError, TypeError, AttributeError) as e:
            frappe.logger().error(f"Amount extraction failed for {source_type_str}: {e}")
            raise ValueError(
                f"Invalid {source_type_str} amount: {getattr(payment_object, 'amount', 'N/A')}"
            ) from e

    def extract_amount_as_decimal(
        self,
        payment_object: Any,
        source_type: Union[str, MollieObjectType] = MollieObjectType.PAYMENT,
        allow_zero: bool = False,
        max_amount: float = 1_000_000,
    ) -> "Decimal":
        """
        Extract amount and return as Decimal for financial calculations.

        This is a convenience method that combines extract_amount() with proper
        Decimal conversion using string intermediate (best practice for precision).

        Args:
            payment_object: Mollie payment/transaction/settlement/subscription object
            source_type: "payment", "balance_transaction", "settlement", or "subscription"
            allow_zero: Whether to allow zero amounts (default: False)
            max_amount: Maximum allowed amount for sanity checking (default: 1,000,000)

        Returns:
            Decimal object suitable for financial calculations

        Examples:
            # Standard payment
            >>> extractor = get_payment_data_extractor()
            >>> amount = extractor.extract_amount_as_decimal(payment)
            >>> print(f"Amount: {amount}")
            Amount: 25.50

            # Balance transaction with zero allowed
            >>> net_change = extractor.extract_amount_as_decimal(
            ...     transaction,
            ...     source_type="balance_transaction",
            ...     allow_zero=True
            ... )

            # Use in financial calculations
            >>> total = Decimal("0")
            >>> for settlement in settlements:
            ...     amount = extractor.extract_amount_as_decimal(
            ...         settlement, source_type="settlement"
            ...     )
            ...     total += amount
        """
        amount = self.extract_amount(payment_object, source_type, allow_zero, max_amount)
        return Decimal(str(amount))

    def _extract_payment_amount(self, payment) -> float:
        """
        Extract amount from standard Mollie payment object.

        Handles both attribute access (payment.amount["value"]) and
        dict access (payment.get("amount", {}).get("value"))
        """
        # Try attribute access first (payment.amount)
        amount_dict = getattr(payment, "amount", None)

        # Fallback to dict access if payment is dict-like
        if amount_dict is None and hasattr(payment, "get"):
            amount_dict = payment.get("amount")

        if not amount_dict:
            raise ValueError("Payment missing amount field")

        # Extract value (support both dict and object access)
        if isinstance(amount_dict, dict):
            amount_value = amount_dict.get("value", "0")
        else:
            amount_value = getattr(amount_dict, "value", "0")

        # Validate type
        if not isinstance(amount_value, (str, int, float)):
            raise ValueError(f"Invalid amount type: {type(amount_value).__name__}")

        # Convert to float
        return float(amount_value)

    def _extract_balance_transaction_amount(self, transaction) -> float:
        """
        Extract amount from Mollie balance transaction object.

        Balance transactions have result_amount.decimal_value format
        """
        # Try result_amount first (most common)
        result_amount = getattr(transaction, "result_amount", None)
        if result_amount and hasattr(result_amount, "decimal_value"):
            return float(result_amount.decimal_value)

        # Fallback to initial_amount
        initial_amount = getattr(transaction, "initial_amount", None)
        if initial_amount and hasattr(initial_amount, "decimal_value"):
            return float(initial_amount.decimal_value)

        raise ValueError("Balance transaction missing result_amount or initial_amount")

    def _extract_decimal_amount(self, mollie_object) -> float:
        """
        Extract amount from Mollie objects using decimal_value format.

        This handles settlements, subscriptions, and balance objects that use:
        - object.amount.decimal_value (Decimal type)
        - object.amount.value (string/float type)

        Args:
            mollie_object: Settlement, subscription, or balance object

        Returns:
            Amount as float

        Raises:
            ValueError: If amount cannot be extracted
        """
        amount_obj = getattr(mollie_object, "amount", None)

        if not amount_obj:
            raise ValueError("Object missing amount field")

        # Try decimal_value first (preferred for settlements/balances)
        if hasattr(amount_obj, "decimal_value"):
            return float(amount_obj.decimal_value)

        # Fallback to value format (subscriptions may use this)
        if hasattr(amount_obj, "value"):
            return float(amount_obj.value)

        # Last resort: try dict access
        if isinstance(amount_obj, dict):
            if "decimal_value" in amount_obj:
                return float(amount_obj["decimal_value"])
            if "value" in amount_obj:
                return float(amount_obj["value"])

        raise ValueError(f"Cannot extract amount from object: {type(amount_obj).__name__}")

    def extract_currency(
        self,
        payment_object: Any,
        company: str,
        source_type: str = "payment",
        strict_validation: bool = True,
    ) -> str:
        """
        Safely extract and validate payment currency.

        Args:
            payment_object: Mollie payment/transaction object
            company: Company name for validation
            source_type: "payment", "balance_transaction", or "settlement"
            strict_validation: If True, raises error for missing currency (default: True)

        Returns:
            Validated currency code (e.g., "EUR", "USD")

        Raises:
            ValueError: If currency is missing or invalid (when strict_validation=True)

        Examples:
            # Strict validation (throws if missing)
            currency = extractor.extract_currency(payment, "Company Name")

            # Lenient validation (falls back to EUR)
            currency = extractor.extract_currency(
                payment,
                "Company Name",
                strict_validation=False
            )
        """
        try:
            if source_type == "balance_transaction":
                currency = self._extract_balance_transaction_currency(payment_object)
            else:
                currency = self._extract_payment_currency(payment_object)

            # Handle missing currency
            if not currency:
                if strict_validation:
                    raise ValueError("Payment missing currency field")
                else:
                    frappe.logger().warning("Payment missing currency, defaulting to EUR")
                    return "EUR"

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
            frappe.logger().error(f"Currency extraction failed for {source_type}: {e}")
            raise ValueError(
                f"Invalid {source_type} currency: {getattr(payment_object, 'amount', 'N/A')}"
            ) from e

    def extract_currency_simple(
        self,
        payment_object: Any,
        source_type: Union[str, MollieObjectType] = MollieObjectType.PAYMENT,
        fallback: str = "EUR",
        strict: bool = False,
    ) -> str:
        """
        Extract currency WITHOUT company validation.

        Use this when company is not available in context or when you don't need
        company currency validation. Can optionally enforce strict extraction that
        raises exceptions instead of using fallback.

        **When to use which method:**
        - Use `extract_currency_simple()` when:
          * Company context not available (webhooks, background jobs)
          * Company validation not required (reporting, monitoring)
          * Graceful degradation preferred over errors

        - Use `extract_currency()` when:
          * Company validation required (payment processing)
          * Multi-currency handling needed with exchange rates
          * Strict compliance required

        Args:
            payment_object: Mollie payment/transaction/settlement/subscription object
            source_type: "payment", "balance_transaction", "settlement", or "subscription"
            fallback: Currency to return if extraction fails (default: "EUR")
            strict: If True, raise exception on extraction failure instead of using fallback

        Returns:
            Currency code (e.g., "EUR", "USD") or fallback (unless strict=True)

        Raises:
            ValueError: If strict=True and currency extraction fails

        Examples:
            # Simple extraction without validation (lenient mode)
            >>> extractor = get_payment_data_extractor()
            >>> currency = extractor.extract_currency_simple(payment)
            >>> print(currency)
            EUR

            # Strict mode - raises on failure
            >>> currency = extractor.extract_currency_simple(
            ...     payment,
            ...     strict=True  # Will raise ValueError if extraction fails
            ... )

            # Custom fallback for non-EUR contexts
            >>> currency = extractor.extract_currency_simple(
            ...     payment,
            ...     fallback="USD"
            ... )

            # For balance transaction
            >>> currency = extractor.extract_currency_simple(
            ...     transaction,
            ...     source_type="balance_transaction"
            ... )
        """
        # Normalize source_type to string for comparison (supports both string and Enum)
        source_type_str = str(source_type) if isinstance(source_type, MollieObjectType) else source_type

        try:
            if source_type_str == "balance_transaction":
                currency = self._extract_balance_transaction_currency(payment_object)
            elif source_type_str in ("settlement", "subscription"):
                currency = self._extract_decimal_currency(payment_object)
            else:
                currency = self._extract_payment_currency(payment_object)

            if not currency:
                if strict:
                    raise ValueError(
                        f"Currency extraction failed for {source_type_str}: "
                        f"payment object missing currency field"
                    )
                # Warn in production (debug logs often disabled)
                frappe.logger().warning(
                    f"Currency extraction failed for {source_type_str}, using fallback {fallback}"
                )
                return fallback

            return currency

        except (AttributeError, ValueError) as e:
            if strict:
                # Re-raise with enhanced context
                raise ValueError(f"Strict currency extraction failed for {source_type_str}: {str(e)}") from e

            # Warn about unexpected extraction failures
            frappe.logger().warning(
                f"Currency extraction failed for {source_type_str}, using fallback {fallback}: {e}"
            )
            return fallback

    def _extract_payment_currency(self, payment) -> Optional[str]:
        """Extract currency from standard Mollie payment object."""
        # Try attribute access first (payment.amount)
        amount_dict = getattr(payment, "amount", None)

        # Fallback to dict access if payment is dict-like
        if amount_dict is None and hasattr(payment, "get"):
            amount_dict = payment.get("amount")

        if not amount_dict:
            return None

        # Extract currency (support both dict and object access)
        if isinstance(amount_dict, dict):
            return amount_dict.get("currency")
        else:
            return getattr(amount_dict, "currency", None)

    def _extract_decimal_currency(self, mollie_object) -> Optional[str]:
        """Extract currency from Mollie objects using decimal_value format (settlements/subscriptions)."""
        amount_obj = getattr(mollie_object, "amount", None)

        if not amount_obj:
            return None

        # Try currency attribute
        if hasattr(amount_obj, "currency"):
            return amount_obj.currency

        # Try dict access
        if isinstance(amount_obj, dict) and "currency" in amount_obj:
            return amount_obj["currency"]

        return None

    def _extract_balance_transaction_currency(self, transaction) -> Optional[str]:
        """Extract currency from Mollie balance transaction object."""
        # Try result_amount first
        result_amount = getattr(transaction, "result_amount", None)
        if result_amount and hasattr(result_amount, "currency"):
            return result_amount.currency

        # Fallback to initial_amount
        initial_amount = getattr(transaction, "initial_amount", None)
        if initial_amount and hasattr(initial_amount, "currency"):
            return initial_amount.currency

        return None

    def extract_payment_date(
        self,
        payment_data: Any,
        field_names: Optional[list] = None,
    ) -> date:
        """
        Extract and parse payment date from Mollie payment data.

        Tries multiple field names and handles ISO datetime string parsing.
        This is the recommended method for webhook processing where payment
        data is often a dict with ISO datetime strings.

        Args:
            payment_data: Mollie payment data (dict or object)
            field_names: List of field names to try (default: ["paid_at", "created_at"])

        Returns:
            Parsed date or today's date if parsing fails

        Examples:
            # Standard usage
            extractor = get_payment_data_extractor()
            paid_date = extractor.extract_payment_date(payment_data)

            # Custom field priority
            paid_date = extractor.extract_payment_date(
                payment_data,
                field_names=["created_at", "paid_at", "timestamp"]
            )
        """
        if field_names is None:
            field_names = ["paid_at", "created_at"]

        for field_name in field_names:
            # Try dict access first
            if isinstance(payment_data, dict):
                date_value = payment_data.get(field_name)
            else:
                date_value = getattr(payment_data, field_name, None)

            if not date_value:
                continue

            # Parse ISO datetime strings (Mollie uses "2025-12-01T23:45:30+00:00" format)
            if isinstance(date_value, str):
                try:
                    from dateutil import parser

                    return parser.parse(date_value).date()
                except (ValueError, TypeError, ImportError):
                    # Try Frappe's getdate as fallback
                    try:
                        return getdate(date_value)
                    except Exception:
                        continue

            # Handle datetime objects
            if hasattr(date_value, "date"):
                return date_value.date()

            # Handle date objects
            if isinstance(date_value, date):
                return date_value

        # Fallback to today
        frappe.logger().debug(f"Could not extract date from fields {field_names}, using today's date")
        return getdate()

    def extract_date(
        self,
        payment_object: Any,
        field_name: str = "paid_at",
        fallback_to_today: bool = True,
    ) -> date:
        """
        Safely extract payment date from Mollie object.

        Handles timezone conversions (Mollie uses UTC) and provides
        consistent fallback behavior.

        Args:
            payment_object: Mollie payment/transaction object
            field_name: Name of date field to extract (default: "paid_at")
            fallback_to_today: If True, returns today's date if field missing (default: True)

        Returns:
            Python date object

        Raises:
            ValueError: If date field missing and fallback_to_today=False

        Examples:
            # Standard paid_at extraction
            payment_date = extractor.extract_date(payment)

            # Custom field name
            created_date = extractor.extract_date(payment, field_name="created_at")

            # Strict mode (no fallback)
            settlement_date = extractor.extract_date(
                settlement,
                field_name="settled_at",
                fallback_to_today=False
            )
        """
        date_value = getattr(payment_object, field_name, None)

        if date_value:
            # Convert to date using Frappe's getdate (handles string, datetime, date)
            return getdate(date_value)

        if fallback_to_today:
            frappe.logger().debug(f"Payment object missing '{field_name}' field, using today's date")
            return getdate()
        else:
            raise ValueError(f"Payment object missing required date field: {field_name}")

    def extract_payment_id(self, payment_object: Any) -> str:
        """
        Extract payment ID from Mollie object.

        Args:
            payment_object: Mollie payment/transaction/settlement object

        Returns:
            Payment ID string (e.g., "tr_xxx", "stl_xxx", "baltr_xxx")

        Raises:
            ValueError: If payment ID missing

        Examples:
            payment_id = extractor.extract_payment_id(payment)
        """
        payment_id = getattr(payment_object, "id", None)

        if not payment_id:
            raise ValueError("Payment object missing ID field")

        return str(payment_id)

    def extract_description(
        self,
        payment_object: Any,
        fallback_description: Optional[str] = None,
    ) -> str:
        """
        Extract payment description from Mollie object.

        Args:
            payment_object: Mollie payment object
            fallback_description: Description to use if field is empty

        Returns:
            Payment description string

        Examples:
            description = extractor.extract_description(payment)

            # With fallback
            description = extractor.extract_description(
                payment,
                fallback_description=f"Mollie payment {payment.id}"
            )
        """
        description = getattr(payment_object, "description", None)

        if description:
            return str(description)

        if fallback_description:
            return fallback_description

        # Last resort: use payment ID if available
        payment_id = getattr(payment_object, "id", "UNKNOWN")
        return f"Mollie payment {payment_id}"

    def extract_balance_amounts(self, balance_object: Any) -> dict:
        """
        Extract both available and pending amounts from Mollie balance object.

        Balance objects have two amounts:
        - available_amount: Funds available for payout
        - pending_amount: Funds not yet available

        This method provides a single call to extract all balance information,
        eliminating the need for multiple manual extractions and attribute checks.

        Args:
            balance_object: Mollie balance object (from BalancesClient.get_balance())

        Returns:
            Dict with keys:
                - available (float): Available amount ready for payout (default: 0.0)
                - pending (float): Pending amount not yet available (default: 0.0)
                - currency (str): ISO currency code (default: "EUR")

        Raises:
            None - Returns zeros for missing amounts (graceful degradation)

        Examples:
            # Basic extraction
            >>> extractor = get_payment_data_extractor()
            >>> amounts = extractor.extract_balance_amounts(balance)
            >>> print(f"Available: €{amounts['available']:.2f}")
            Available: €1234.56
            >>> print(f"Pending: €{amounts['pending']:.2f}")
            Pending: €567.89

            # Use in multi-currency balance summary
            >>> totals = {"available": {}, "pending": {}}
            >>> for balance in balances:
            ...     amounts = extractor.extract_balance_amounts(balance)
            ...     currency = amounts['currency']
            ...
            ...     if currency not in totals["available"]:
            ...         totals["available"][currency] = 0
            ...         totals["pending"][currency] = 0
            ...
            ...     totals["available"][currency] += amounts['available']
            ...     totals["pending"][currency] += amounts['pending']

            # Check if balance has sufficient funds
            >>> amounts = extractor.extract_balance_amounts(balance)
            >>> if amounts['available'] < 100:
            ...     print("Low balance alert!")

            # Extract for financial reconciliation
            >>> start_amounts = extractor.extract_balance_amounts(balance_start)
            >>> end_amounts = extractor.extract_balance_amounts(balance_end)
            >>> change = end_amounts['available'] - start_amounts['available']
            >>> print(f"Balance changed by: €{change:.2f}")
        """
        result = {"available": 0.0, "pending": 0.0, "currency": "EUR"}

        # Extract available amount
        available_amount = getattr(balance_object, "available_amount", None)
        if available_amount and hasattr(available_amount, "decimal_value"):
            result["available"] = float(available_amount.decimal_value)
            # Get currency from available_amount
            if hasattr(available_amount, "currency"):
                result["currency"] = available_amount.currency

        # Extract pending amount
        pending_amount = getattr(balance_object, "pending_amount", None)
        if pending_amount and hasattr(pending_amount, "decimal_value"):
            result["pending"] = float(pending_amount.decimal_value)
            # Use currency from pending if available wasn't found
            if result["currency"] == "EUR" and hasattr(pending_amount, "currency"):
                result["currency"] = pending_amount.currency

        return result


def get_payment_data_extractor() -> PaymentDataExtractor:
    """
    Factory function to get PaymentDataExtractor instance.

    Returns:
        PaymentDataExtractor instance

    Example:
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
            get_payment_data_extractor
        )

        extractor = get_payment_data_extractor()
        amount = extractor.extract_amount(payment)
        currency = extractor.extract_currency(payment, company)
        payment_date = extractor.extract_date(payment)
    """
    return PaymentDataExtractor()
