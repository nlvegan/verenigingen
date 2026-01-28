"""
Mollie Data Models

Clean data models for Mollie API objects, independent of the API client.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

# Decimal precision for monetary amounts (2 decimal places)
DECIMAL_PLACES = Decimal("0.01")


@dataclass
class Money:
    """Represents a monetary amount with currency."""

    amount: Decimal
    currency: str

    @classmethod
    def from_mollie_api(cls, data: Dict[str, Any]) -> "Money":
        """Create Money object from Mollie API response."""
        return cls(amount=Decimal(data["value"]), currency=data["currency"])

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary format expected by Mollie API."""
        # Use explicit quantize for proper rounding semantics
        formatted_amount = self.amount.quantize(DECIMAL_PLACES, rounding=ROUND_HALF_UP)
        return {"value": str(formatted_amount), "currency": self.currency}


@dataclass
class Customer:
    """Represents a Mollie customer."""

    id: str
    name: str
    email: str
    created_at: datetime
    metadata: Dict[str, Any]

    @classmethod
    def from_mollie_api(cls, data: Dict[str, Any]) -> "Customer":
        """Create Customer object from Mollie API response."""
        return cls(
            id=data["id"],
            name=data["name"],
            email=data["email"],
            created_at=datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00")),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Payment:
    """Represents a Mollie payment."""

    id: str
    amount: Money
    description: str
    status: str
    customer_id: Optional[str]
    subscription_id: Optional[str]
    created_at: datetime
    paid_at: Optional[datetime]
    metadata: Dict[str, Any]
    method: Optional[str]

    @classmethod
    def from_mollie_api(cls, data: Dict[str, Any]) -> "Payment":
        """Create Payment object from Mollie API response."""
        return cls(
            id=data["id"],
            amount=Money.from_mollie_api(data["amount"]),
            description=data["description"],
            status=data["status"],
            customer_id=data.get("customerId"),
            subscription_id=data.get("subscriptionId"),
            created_at=datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00")),
            paid_at=(
                datetime.fromisoformat(data["paidAt"].replace("Z", "+00:00")) if data.get("paidAt") else None
            ),
            metadata=data.get("metadata", {}),
            method=data.get("method"),
        )

    @property
    def is_paid(self) -> bool:
        """Check if payment is paid."""
        return self.status == "paid"

    @property
    def is_pending(self) -> bool:
        """Check if payment is pending."""
        return self.status in ["open", "pending"]

    @property
    def is_failed(self) -> bool:
        """Check if payment failed."""
        return self.status in ["failed", "canceled", "expired"]


@dataclass
class Subscription:
    """Represents a Mollie subscription."""

    id: str
    customer_id: str
    amount: Money
    interval: str
    description: str
    status: str
    created_at: datetime
    next_payment_date: Optional[datetime]
    metadata: Dict[str, Any]

    @classmethod
    def from_mollie_api(cls, data: Dict[str, Any]) -> "Subscription":
        """Create Subscription object from Mollie API response."""
        return cls(
            id=data["id"],
            customer_id=data["customerId"],
            amount=Money.from_mollie_api(data["amount"]),
            interval=data["interval"],
            description=data["description"],
            status=data["status"],
            created_at=datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00")),
            next_payment_date=(
                datetime.fromisoformat(data["nextPaymentDate"].replace("Z", "+00:00"))
                if data.get("nextPaymentDate")
                else None
            ),
            metadata=data.get("metadata", {}),
        )

    @property
    def is_active(self) -> bool:
        """Check if subscription is active."""
        return self.status == "active"

    @property
    def is_canceled(self) -> bool:
        """Check if subscription is canceled."""
        return self.status in ["canceled", "suspended", "completed"]
