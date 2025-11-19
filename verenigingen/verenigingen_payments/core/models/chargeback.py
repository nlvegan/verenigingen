"""
Chargeback Models for Mollie API
Data structures for chargeback-related operations
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional

from .base import Amount, BaseModel, Links


class ChargebackReason(Enum):
    """Chargeback reason codes"""

    DUPLICATE = "duplicate"
    FRAUDULENT = "fraudulent"
    REQUESTED_BY_CUSTOMER = "requested_by_customer"
    UNRECOGNIZED = "unrecognized"
    GENERAL = "general"


class Chargeback(BaseModel):
    """
    Mollie Chargeback resource

    Represents a payment chargeback/dispute
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize chargeback"""
        self.resource: str = "chargeback"
        self.id: Optional[str] = None
        self.amount: Optional[Amount] = None
        self.settlement_amount: Optional[Amount] = None
        self.created_at: Optional[str] = None
        self.reversed_at: Optional[str] = None
        self.payment_id: Optional[str] = None
        self.settlement_id: Optional[str] = None
        self.reason: Optional[Dict[str, str]] = None
        self._links: Optional[Links] = None
        super().__init__(data)

    def _get_nested_model_class(self, attr_name: str) -> Optional[type]:
        """Get model class for nested attribute"""
        if attr_name in ["amount", "settlement_amount"]:
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

        if self.reversed_at and isinstance(self.reversed_at, str):
            try:
                self.reversed_at_datetime = datetime.fromisoformat(self.reversed_at.replace("Z", "+00:00"))
            except:
                self.reversed_at_datetime = None

    def is_reversed(self) -> bool:
        """Check if chargeback has been reversed"""
        return bool(self.reversed_at)

    def get_reason_code(self) -> Optional[str]:
        """Get chargeback reason code"""
        if self.reason and isinstance(self.reason, dict):
            return self.reason.get("code")
        return None

    def get_reason_description(self) -> Optional[str]:
        """Get chargeback reason description"""
        if self.reason and isinstance(self.reason, dict):
            return self.reason.get("description")
        return None

    def get_financial_impact(self) -> Decimal:
        """Calculate total financial impact"""
        impact = Decimal("0")

        # Add chargeback amount
        if self.amount and hasattr(self.amount, "decimal_value"):
            impact += self.amount.decimal_value

        # Add settlement amount (usually includes fees)
        if self.settlement_amount and hasattr(self.settlement_amount, "decimal_value"):
            impact += abs(self.settlement_amount.decimal_value)

        return impact
