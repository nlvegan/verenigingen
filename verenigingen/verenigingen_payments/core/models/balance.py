"""
Balance Models for Mollie API
Data structures for balance-related operations
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from .base import Amount, BaseModel, Links


class BalanceStatus(Enum):
    """Balance status types"""

    ACTIVE = "active"
    INACTIVE = "inactive"


class TransferFrequency(Enum):
    """Transfer frequency options"""

    DAILY = "daily"
    TWICE_A_WEEK = "twice-a-week"
    EVERY_MONDAY = "every-monday"
    EVERY_TUESDAY = "every-tuesday"
    EVERY_WEDNESDAY = "every-wednesday"
    EVERY_THURSDAY = "every-thursday"
    EVERY_FRIDAY = "every-friday"
    MONTHLY = "monthly"
    NEVER = "never"


class BalanceAmount(BaseModel):
    """
    Balance amount with currency
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize balance amount"""
        self.currency: Optional[str] = None
        self.value: Optional[str] = None
        super().__init__(data)

    def _post_init(self):
        """Convert value to Decimal"""
        if self.value:
            try:
                self.decimal_value = Decimal(self.value)
            except:
                self.decimal_value = Decimal("0")

    def __str__(self) -> str:
        """String representation"""
        return f"{self.currency} {self.value}"


class Balance(BaseModel):
    """
    Mollie Balance resource

    Represents a balance for a specific currency
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize balance"""
        self.resource: str = "balance"
        self.id: Optional[str] = None
        self.mode: Optional[str] = None
        self.created_at: Optional[str] = None
        self.currency: Optional[str] = None
        self.status: Optional[str] = None
        self.transfer_frequency: Optional[str] = None
        self.transfer_threshold: Optional[Amount] = None
        self.transfer_destination: Optional[Dict[str, Any]] = None
        self.available_amount: Optional[Amount] = None
        self.pending_amount: Optional[Amount] = None
        self._links: Optional[Links] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name in ["transfer_threshold", "available_amount", "pending_amount"]:
            return Amount
        elif attr_name == "_links":
            return Links
        return None

    def _post_init(self):
        """Parse dates"""
        if self.created_at and isinstance(self.created_at, str):
            try:
                self.created_at_datetime = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            except:
                self.created_at_datetime = None

    def is_active(self) -> bool:
        """Check if balance is active"""
        return self.status == BalanceStatus.ACTIVE.value

    def get_total_balance(self) -> Decimal:
        """Get total balance (available + pending)"""
        available = Decimal("0")
        pending = Decimal("0")

        if self.available_amount and hasattr(self.available_amount, "decimal_value"):
            available = self.available_amount.decimal_value

        if self.pending_amount and hasattr(self.pending_amount, "decimal_value"):
            pending = self.pending_amount.decimal_value

        return available + pending


class BalanceTransaction(BaseModel):
    """
    Balance transaction record
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize balance transaction"""
        self.resource: str = "balance_transaction"
        self.id: Optional[str] = None
        self.type: Optional[str] = None
        self.result_amount: Optional[Amount] = None
        self.initial_amount: Optional[Amount] = None
        self.deductions: Optional[List[Dict[str, Any]]] = None
        self.created_at: Optional[str] = None
        self.context: Optional[Dict[str, Any]] = None
        self._links: Optional[Links] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name in ["result_amount", "initial_amount"]:
            return Amount
        elif attr_name == "_links":
            return Links
        return None

    def _post_init(self):
        """Parse dates"""
        if self.created_at and isinstance(self.created_at, str):
            try:
                self.created_at_datetime = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            except:
                self.created_at_datetime = None

    def get_total_deductions(self) -> Decimal:
        """Calculate total deductions"""
        total = Decimal("0")

        if self.deductions:
            for deduction in self.deductions:
                if "amount" in deduction and "value" in deduction["amount"]:
                    try:
                        total += Decimal(deduction["amount"]["value"])
                    except:
                        pass

        return total


class BalanceReport(BaseModel):
    """
    Balance report with transactions
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize balance report"""
        self.resource: str = "balance_report"
        self.id: Optional[str] = None
        self.balance_id: Optional[str] = None
        self.time_zone: Optional[str] = None
        self.from_date: Optional[str] = None
        self.until_date: Optional[str] = None
        self.grouping: Optional[str] = None
        self.totals: Optional[Dict[str, Amount]] = None
        self._links: Optional[Links] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name == "_links":
            return Links
        return None

    def _post_init(self):
        """Parse dates and totals"""
        # Parse dates
        if self.from_date and isinstance(self.from_date, str):
            try:
                self.from_datetime = datetime.fromisoformat(self.from_date.replace("Z", "+00:00"))
            except:
                self.from_datetime = None

        if self.until_date and isinstance(self.until_date, str):
            try:
                self.until_datetime = datetime.fromisoformat(self.until_date.replace("Z", "+00:00"))
            except:
                self.until_datetime = None

        # Parse totals into Amount objects
        if self.totals and isinstance(self.totals, dict):
            parsed_totals = {}
            for key, value in self.totals.items():
                if isinstance(value, dict):
                    parsed_totals[key] = Amount(value)
                else:
                    parsed_totals[key] = value
            self.totals = parsed_totals
